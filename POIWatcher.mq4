//+------------------------------------------------------------------+
//|                                                  POIWatcher.mq4  |
//|                              Trading System Auto-Logger & BE Bot |
//|                                                                  |
//| Monitors all open trades, auto-logs to POIWatcher backend,       |
//| and automatically moves SL to break even at configurable RR.     |
//|                                                                  |
//| INSTALLATION:                                                    |
//| 1. Copy this file to: MT4/MQL4/Experts/POIWatcher.mq4           |
//| 2. Open MetaEditor (F4 in MT4) → File → Open → POIWatcher.mq4  |
//| 3. Click Compile (F7) — should show 0 errors                    |
//| 4. Back in MT4: View → Navigator → Expert Advisors              |
//| 5. Drag "POIWatcher" onto ANY chart                              |
//| 6. In the popup, go to "Inputs" tab to configure settings       |
//| 7. Make sure "AutoTrading" button (top toolbar) is ON            |
//| 8. Tools → Options → Expert Advisors:                            |
//|    ✓ Allow automated trading                                     |
//|    ✓ Allow WebRequest for listed URL                             |
//|    Add your backend URL to the allowed list                      |
//+------------------------------------------------------------------+
#property copyright "POIWatcher"
#property link      "https://github.com/Chukwuemeka001/poiwatcher-backend"
#property version   "1.00"
#property strict

//--- User configurable inputs
input string   BackendURL        = "https://poiwatcher-backend.onrender.com";
input bool     EnableAutoBreakEven = true;
input double   BreakEvenRR       = 1.5;
input bool     EnableAutoLogging = true;
input int      HeartbeatMinutes  = 5;

//--- Internal state
int      knownTickets[];       // tickets we already know about
double   knownSL[];            // last known SL for each ticket
double   knownTP[];            // last known TP for each ticket
bool     beApplied[];          // whether BE was already applied
datetime lastHeartbeat = 0;
datetime lastCheck     = 0;

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("POIWatcher EA initialized — Backend: ", BackendURL);
   Print("Auto Break Even: ", EnableAutoBreakEven ? "ON" : "OFF",
         " at 1:", DoubleToString(BreakEvenRR, 1), " RR");

   // Scan existing trades on startup
   ScanOpenTrades();

   // Send initial heartbeat
   SendHeartbeat();
   lastHeartbeat = TimeCurrent();
   lastCheck     = TimeCurrent();

   EventSetTimer(1); // tick every second, logic throttles internally
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("POIWatcher EA removed");
}

//+------------------------------------------------------------------+
//| Timer event — main loop                                          |
//+------------------------------------------------------------------+
void OnTimer()
{
   datetime now = TimeCurrent();

   // Check trades every 60 seconds
   if (now - lastCheck >= 60)
   {
      lastCheck = now;
      CheckForNewTrades();
      CheckForClosedTrades();
      CheckForModifications();

      if (EnableAutoBreakEven)
         CheckBreakEven();
   }

   // Heartbeat
   if (now - lastHeartbeat >= HeartbeatMinutes * 60)
   {
      lastHeartbeat = now;
      SendHeartbeat();
   }
}

//+------------------------------------------------------------------+
//| Scan existing open trades on startup                             |
//+------------------------------------------------------------------+
void ScanOpenTrades()
{
   ArrayResize(knownTickets, 0);
   ArrayResize(knownSL, 0);
   ArrayResize(knownTP, 0);
   ArrayResize(beApplied, 0);

   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if (OrderType() > OP_SELL) continue; // skip pending orders

      int size = ArraySize(knownTickets);
      ArrayResize(knownTickets, size + 1);
      ArrayResize(knownSL, size + 1);
      ArrayResize(knownTP, size + 1);
      ArrayResize(beApplied, size + 1);

      knownTickets[size] = OrderTicket();
      knownSL[size]      = OrderStopLoss();
      knownTP[size]      = OrderTakeProfit();

      // Check if BE already applied (SL == entry)
      beApplied[size] = (MathAbs(OrderStopLoss() - OrderOpenPrice()) < Point);
   }

   Print("POIWatcher: Found ", ArraySize(knownTickets), " open trades on startup");
}

//+------------------------------------------------------------------+
//| Check for newly opened trades                                    |
//+------------------------------------------------------------------+
void CheckForNewTrades()
{
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if (OrderType() > OP_SELL) continue;

      int ticket = OrderTicket();
      if (IsKnownTicket(ticket)) continue;

      // New trade found!
      int size = ArraySize(knownTickets);
      ArrayResize(knownTickets, size + 1);
      ArrayResize(knownSL, size + 1);
      ArrayResize(knownTP, size + 1);
      ArrayResize(beApplied, size + 1);

      knownTickets[size] = ticket;
      knownSL[size]      = OrderStopLoss();
      knownTP[size]      = OrderTakeProfit();
      beApplied[size]    = false;

      Print("POIWatcher: New trade detected — #", ticket, " ", OrderSymbol(),
            " ", (OrderType() == OP_BUY ? "Long" : "Short"));

      if (EnableAutoLogging)
         SendTradeOpen(ticket);
   }
}

//+------------------------------------------------------------------+
//| Check for closed trades                                          |
//+------------------------------------------------------------------+
void CheckForClosedTrades()
{
   for (int k = ArraySize(knownTickets) - 1; k >= 0; k--)
   {
      int ticket = knownTickets[k];
      bool stillOpen = false;

      for (int i = OrdersTotal() - 1; i >= 0; i--)
      {
         if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
         if (OrderTicket() == ticket) { stillOpen = true; break; }
      }

      if (!stillOpen)
      {
         // Trade closed — find it in history
         if (OrderSelect(ticket, SELECT_BY_TICKET))
         {
            Print("POIWatcher: Trade closed — #", ticket, " ", OrderSymbol(),
                  " P&L: ", DoubleToString(OrderProfit(), 2));

            if (EnableAutoLogging)
               SendTradeClose(ticket);
         }

         // Remove from arrays
         RemoveTicket(k);
      }
   }
}

//+------------------------------------------------------------------+
//| Check for SL/TP modifications                                   |
//+------------------------------------------------------------------+
void CheckForModifications()
{
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if (OrderType() > OP_SELL) continue;

      int ticket = OrderTicket();
      int idx = GetTicketIndex(ticket);
      if (idx < 0) continue;

      bool slChanged = MathAbs(OrderStopLoss() - knownSL[idx]) > Point;
      bool tpChanged = MathAbs(OrderTakeProfit() - knownTP[idx]) > Point;

      if (slChanged || tpChanged)
      {
         string modification = "";
         if (slChanged && MathAbs(OrderStopLoss() - OrderOpenPrice()) < Point * 2)
            modification = "SL moved to BE";
         else if (slChanged && tpChanged)
            modification = "Both";
         else if (slChanged)
            modification = "SL adjusted";
         else
            modification = "TP adjusted";

         Print("POIWatcher: Trade modified — #", ticket, " ", modification);

         knownSL[idx] = OrderStopLoss();
         knownTP[idx] = OrderTakeProfit();

         if (EnableAutoLogging)
            SendTradeModify(ticket, modification);
      }
   }
}

//+------------------------------------------------------------------+
//| Auto break even check                                            |
//+------------------------------------------------------------------+
void CheckBreakEven()
{
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if (OrderType() > OP_SELL) continue;

      int ticket = OrderTicket();
      int idx = GetTicketIndex(ticket);
      if (idx < 0 || beApplied[idx]) continue;

      double entry = OrderOpenPrice();
      double sl    = OrderStopLoss();
      double bid   = MarketInfo(OrderSymbol(), MODE_BID);
      double ask   = MarketInfo(OrderSymbol(), MODE_ASK);

      if (sl == 0) continue; // no SL set

      double risk   = MathAbs(entry - sl);
      if (risk < Point) continue;

      double currentProfit;
      if (OrderType() == OP_BUY)
         currentProfit = bid - entry;
      else
         currentProfit = entry - ask;

      double currentRR = currentProfit / risk;

      if (currentRR >= BreakEvenRR)
      {
         // Move SL to entry (break even)
         double newSL = entry;

         bool result;
         if (OrderType() == OP_BUY)
            result = OrderModify(ticket, entry, newSL, OrderTakeProfit(), 0, clrLime);
         else
            result = OrderModify(ticket, entry, newSL, OrderTakeProfit(), 0, clrRed);

         if (result)
         {
            beApplied[idx] = true;
            knownSL[idx]   = newSL;
            Print("POIWatcher: AUTO BE — #", ticket, " ", OrderSymbol(),
                  " SL moved to entry at RR 1:", DoubleToString(currentRR, 1));

            if (EnableAutoLogging)
               SendTradeModify(ticket, "SL moved to BE");
         }
         else
         {
            Print("POIWatcher: BE modify failed — #", ticket,
                  " Error: ", GetLastError());
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Send trade open to backend                                       |
//+------------------------------------------------------------------+
void SendTradeOpen(int ticket)
{
   if (!OrderSelect(ticket, SELECT_BY_TICKET)) return;

   string json = "{";
   json += "\"ticket\":" + IntegerToString(ticket) + ",";
   json += "\"symbol\":\"" + OrderSymbol() + "\",";
   json += "\"direction\":\"" + (OrderType() == OP_BUY ? "Long" : "Short") + "\",";
   json += "\"entry_price\":" + DoubleToString(OrderOpenPrice(), (int)MarketInfo(OrderSymbol(), MODE_DIGITS)) + ",";
   json += "\"stop_loss\":" + DoubleToString(OrderStopLoss(), (int)MarketInfo(OrderSymbol(), MODE_DIGITS)) + ",";
   json += "\"take_profit\":" + DoubleToString(OrderTakeProfit(), (int)MarketInfo(OrderSymbol(), MODE_DIGITS)) + ",";
   json += "\"lot_size\":" + DoubleToString(OrderLots(), 2) + ",";
   json += "\"timestamp\":\"" + TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS) + "\",";
   json += "\"account_balance\":" + DoubleToString(AccountBalance(), 2) + ",";
   json += "\"account_equity\":" + DoubleToString(AccountEquity(), 2);
   json += "}";

   HttpPost("/mt4/trade-open", json);
}

//+------------------------------------------------------------------+
//| Send trade close to backend                                      |
//+------------------------------------------------------------------+
void SendTradeClose(int ticket)
{
   if (!OrderSelect(ticket, SELECT_BY_TICKET)) return;

   double entryPrice = OrderOpenPrice();
   double closePrice = OrderClosePrice();
   double profit     = OrderProfit() + OrderSwap() + OrderCommission();

   // Calculate pips
   double pointVal = MarketInfo(OrderSymbol(), MODE_POINT);
   int    digits   = (int)MarketInfo(OrderSymbol(), MODE_DIGITS);
   double pipDiv   = (digits == 3 || digits == 5) ? 10.0 : 1.0;
   double pips     = MathAbs(closePrice - entryPrice) / pointVal / pipDiv;
   if ((OrderType() == OP_BUY && closePrice < entryPrice) ||
       (OrderType() == OP_SELL && closePrice > entryPrice))
      pips = -pips;

   // Duration
   int durationMin = (int)((OrderCloseTime() - OrderOpenTime()) / 60);

   // Close reason
   string reason = "Manual close";
   double tp = OrderTakeProfit();
   double sl = OrderStopLoss();
   if (tp > 0 && MathAbs(closePrice - tp) < pointVal * 3)
      reason = "TP hit";
   else if (sl > 0 && MathAbs(closePrice - sl) < pointVal * 3)
      reason = "SL hit";

   string json = "{";
   json += "\"ticket\":" + IntegerToString(ticket) + ",";
   json += "\"symbol\":\"" + OrderSymbol() + "\",";
   json += "\"direction\":\"" + (OrderType() == OP_BUY ? "Long" : "Short") + "\",";
   json += "\"entry_price\":" + DoubleToString(entryPrice, digits) + ",";
   json += "\"exit_price\":" + DoubleToString(closePrice, digits) + ",";
   json += "\"profit_loss\":" + DoubleToString(profit, 2) + ",";
   json += "\"pips\":" + DoubleToString(pips, 1) + ",";
   json += "\"duration_minutes\":" + IntegerToString(durationMin) + ",";
   json += "\"close_reason\":\"" + reason + "\"";
   json += "}";

   HttpPost("/mt4/trade-close", json);
}

//+------------------------------------------------------------------+
//| Send trade modification to backend                               |
//+------------------------------------------------------------------+
void SendTradeModify(int ticket, string modification)
{
   if (!OrderSelect(ticket, SELECT_BY_TICKET)) return;

   int digits = (int)MarketInfo(OrderSymbol(), MODE_DIGITS);

   string json = "{";
   json += "\"ticket\":" + IntegerToString(ticket) + ",";
   json += "\"symbol\":\"" + OrderSymbol() + "\",";
   json += "\"new_sl\":" + DoubleToString(OrderStopLoss(), digits) + ",";
   json += "\"new_tp\":" + DoubleToString(OrderTakeProfit(), digits) + ",";
   json += "\"modification\":\"" + modification + "\"";
   json += "}";

   HttpPost("/mt4/trade-modify", json);
}

//+------------------------------------------------------------------+
//| Send heartbeat to backend                                        |
//+------------------------------------------------------------------+
void SendHeartbeat()
{
   int openCount = 0;
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if (OrderType() <= OP_SELL) openCount++;
   }

   string json = "{";
   json += "\"connected\":true,";
   json += "\"open_trades\":" + IntegerToString(openCount) + ",";
   json += "\"account_balance\":" + DoubleToString(AccountBalance(), 2) + ",";
   json += "\"account_equity\":" + DoubleToString(AccountEquity(), 2) + ",";
   json += "\"timestamp\":\"" + TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS) + "\"";
   json += "}";

   HttpPost("/mt4/status", json);
}

//+------------------------------------------------------------------+
//| HTTP POST helper via WebRequest                                  |
//+------------------------------------------------------------------+
void HttpPost(string endpoint, string jsonBody)
{
   string url = BackendURL + endpoint;
   string headers = "Content-Type: application/json\r\n";
   char   postData[];
   char   result[];
   string resultHeaders;

   StringToCharArray(jsonBody, postData, 0, WHOLE_ARRAY, CP_UTF8);
   // Remove null terminator
   ArrayResize(postData, ArraySize(postData) - 1);

   int timeout = 5000; // 5 seconds

   int res = WebRequest("POST", url, headers, timeout, postData, result, resultHeaders);

   if (res == -1)
   {
      int err = GetLastError();
      if (err == 4060)
         Print("POIWatcher: WebRequest blocked — add ", BackendURL,
               " to Tools → Options → Expert Advisors → Allow WebRequest");
      else
         Print("POIWatcher: HTTP error ", err, " on ", endpoint);
   }
   else if (res >= 200 && res < 300)
   {
      // Success — silent
   }
   else
   {
      string response = CharArrayToString(result);
      Print("POIWatcher: HTTP ", res, " on ", endpoint, " — ", response);
   }
}

//+------------------------------------------------------------------+
//| Array helpers                                                     |
//+------------------------------------------------------------------+
bool IsKnownTicket(int ticket)
{
   for (int i = 0; i < ArraySize(knownTickets); i++)
      if (knownTickets[i] == ticket) return true;
   return false;
}

int GetTicketIndex(int ticket)
{
   for (int i = 0; i < ArraySize(knownTickets); i++)
      if (knownTickets[i] == ticket) return i;
   return -1;
}

void RemoveTicket(int idx)
{
   int last = ArraySize(knownTickets) - 1;
   if (idx < last)
   {
      knownTickets[idx] = knownTickets[last];
      knownSL[idx]      = knownSL[last];
      knownTP[idx]      = knownTP[last];
      beApplied[idx]    = beApplied[last];
   }
   ArrayResize(knownTickets, last);
   ArrayResize(knownSL, last);
   ArrayResize(knownTP, last);
   ArrayResize(beApplied, last);
}

//+------------------------------------------------------------------+
//| OnTick — also check (backup for Timer)                           |
//+------------------------------------------------------------------+
void OnTick()
{
   // Timer handles everything, OnTick is just a backup
   // in case Timer doesn't fire on some brokers
   OnTimer();
}
//+------------------------------------------------------------------+
