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
input string   BackendURL           = "https://poiwatcher-backend.onrender.com";
input bool     EnableAutoBreakEven  = true;
input double   BreakEvenRR          = 1.5;
input bool     EnableAutoLogging    = true;
input int      HeartbeatMinutes     = 5;

//--- Trade Execution Pipeline inputs
input bool     EnableAutoExecution  = false;  // OFF by default — user must enable
input string   ExecutionAPIKey      = "";     // Must match EXECUTION_API_KEY on backend
input int      MaxSlippagePips      = 3;      // Max slippage in pips for execution
input int      ExecutionCheckSeconds = 5;     // How often to poll for approved trades
input double   MaxLotSize           = 1.0;    // Safety cap — never execute above this
input bool     AllowLiveExecution   = false;  // Must be true to execute on a LIVE account when backend is in PAPER mode? See README.
input int      EmergencyCheckSeconds = 10;    // How often to poll the emergency stop endpoint

//--- Internal state
int      knownTickets[];       // tickets we already know about
double   knownSL[];            // last known SL for each ticket
double   knownTP[];            // last known TP for each ticket
bool     beApplied[];          // whether BE was already applied
datetime lastHeartbeat = 0;
datetime lastCheck     = 0;

//--- Execution pipeline state
string   executedTradeIDs[];   // trade IDs already executed (prevent duplicates)
datetime lastExecCheck = 0;    // last time we checked for pending trades
datetime lastEmergencyCheck = 0; // last time we polled emergency stop
string   lastEmergencyAt = "";   // last emergency timestamp we acted on

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("POIWatcher EA initialized — Backend: ", BackendURL);
   Print("Auto Break Even: ", EnableAutoBreakEven ? "ON" : "OFF",
         " at 1:", DoubleToString(BreakEvenRR, 1), " RR");
   Print("Auto Execution: ", EnableAutoExecution ? "ON" : "OFF",
         " | Max lot: ", DoubleToString(MaxLotSize, 2),
         " | Check every ", ExecutionCheckSeconds, "s");
   if (EnableAutoExecution && StringLen(ExecutionAPIKey) == 0)
      Print("WARNING: Auto Execution enabled but ExecutionAPIKey is empty!");

   bool isDemoAcct = (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO);
   Print("Account mode: ", (isDemoAcct ? "DEMO" : "LIVE"),
         " | AllowLiveExecution=", (AllowLiveExecution ? "true" : "false"),
         " | Emergency poll: ", EmergencyCheckSeconds, "s");

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

   // Check for pending trade executions
   if (EnableAutoExecution && now - lastExecCheck >= ExecutionCheckSeconds)
   {
      lastExecCheck = now;
      CheckForPendingExecution();
   }

   // Check emergency stop (always, even if execution disabled — safety first)
   if (now - lastEmergencyCheck >= EmergencyCheckSeconds)
   {
      lastEmergencyCheck = now;
      CheckForEmergencyStop();
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
//| TRADE EXECUTION PIPELINE                                         |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| Check if a trade ID was already executed                         |
//+------------------------------------------------------------------+
bool IsExecutedTradeID(string tradeID)
{
   for (int i = 0; i < ArraySize(executedTradeIDs); i++)
      if (executedTradeIDs[i] == tradeID) return true;
   return false;
}

//+------------------------------------------------------------------+
//| Mark a trade ID as executed                                       |
//+------------------------------------------------------------------+
void MarkTradeExecuted(string tradeID)
{
   int sz = ArraySize(executedTradeIDs);
   ArrayResize(executedTradeIDs, sz + 1);
   executedTradeIDs[sz] = tradeID;
}

//+------------------------------------------------------------------+
//| Check if we already have an open trade on this symbol            |
//+------------------------------------------------------------------+
bool HasOpenTradeOnSymbol(string symbol)
{
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if (OrderType() > OP_SELL) continue;
      if (OrderSymbol() == symbol) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Simple JSON string value extractor                               |
//+------------------------------------------------------------------+
string JsonGetString(string json, string key)
{
   string search = "\"" + key + "\":\"";
   int pos = StringFind(json, search);
   if (pos < 0) return "";
   pos += StringLen(search);
   int end = StringFind(json, "\"", pos);
   if (end < 0) return "";
   return StringSubstr(json, pos, end - pos);
}

//+------------------------------------------------------------------+
//| Simple JSON number value extractor                               |
//+------------------------------------------------------------------+
double JsonGetDouble(string json, string key)
{
   // Try "key":value (number without quotes)
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if (pos < 0) return 0;
   pos += StringLen(search);
   // Skip whitespace
   while (pos < StringLen(json) && StringGetCharacter(json, pos) == ' ') pos++;
   // Find end (comma, brace, or bracket)
   int end = pos;
   while (end < StringLen(json))
   {
      int ch = StringGetCharacter(json, end);
      if (ch == ',' || ch == '}' || ch == ']') break;
      end++;
   }
   string val = StringSubstr(json, pos, end - pos);
   StringTrimRight(val);
   StringTrimLeft(val);
   // Remove quotes if present
   if (StringGetCharacter(val, 0) == '"')
      val = StringSubstr(val, 1, StringLen(val) - 2);
   return StringToDouble(val);
}

//+------------------------------------------------------------------+
//| HTTP GET with execution key header                               |
//+------------------------------------------------------------------+
string HttpGetWithKey(string endpoint)
{
   string url = BackendURL + endpoint;
   string headers = "Content-Type: application/json\r\nX-Execution-Key: " + ExecutionAPIKey + "\r\n";
   char   postData[];
   char   result[];
   string resultHeaders;

   ArrayResize(postData, 0);

   int res = WebRequest("GET", url, headers, 5000, postData, result, resultHeaders);

   if (res == -1)
   {
      int err = GetLastError();
      if (err == 4060)
         Print("POIWatcher EXEC: WebRequest blocked — add ", BackendURL,
               " to Tools → Options → Expert Advisors → Allow WebRequest");
      else
         Print("POIWatcher EXEC: HTTP error ", err, " on GET ", endpoint);
      return "";
   }

   string response = CharArrayToString(result);

   if (res >= 200 && res < 300)
      return response;

   Print("POIWatcher EXEC: HTTP ", res, " on GET ", endpoint, " — ", response);
   return "";
}

//+------------------------------------------------------------------+
//| HTTP POST with execution key header                              |
//+------------------------------------------------------------------+
void HttpPostWithKey(string endpoint, string jsonBody)
{
   string url = BackendURL + endpoint;
   string headers = "Content-Type: application/json\r\nX-Execution-Key: " + ExecutionAPIKey + "\r\n";
   char   postData[];
   char   result[];
   string resultHeaders;

   StringToCharArray(jsonBody, postData, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(postData, ArraySize(postData) - 1);

   int res = WebRequest("POST", url, headers, 5000, postData, result, resultHeaders);

   if (res == -1)
   {
      Print("POIWatcher EXEC: HTTP error ", GetLastError(), " on POST ", endpoint);
   }
   else if (res >= 200 && res < 300)
   {
      // Success
   }
   else
   {
      string response = CharArrayToString(result);
      Print("POIWatcher EXEC: HTTP ", res, " on POST ", endpoint, " — ", response);
   }
}

//+------------------------------------------------------------------+
//| Check for pending trades and execute                             |
//+------------------------------------------------------------------+
void CheckForPendingExecution()
{
   if (!EnableAutoExecution) return;
   if (StringLen(ExecutionAPIKey) == 0)
   {
      Print("POIWatcher EXEC: ExecutionAPIKey not set — skipping");
      return;
   }

   // Safety: minimum equity floor
   if (AccountEquity() < 100.0)
   {
      Print("POIWatcher EXEC: Account equity $", DoubleToString(AccountEquity(), 2),
            " below $100 safety floor — skipping");
      return;
   }

   // Fetch pending trade from backend
   string response = HttpGetWithKey("/api/trade");
   if (StringLen(response) == 0) return;

   // Check status
   string status = JsonGetString(response, "status");
   if (status != "trade_ready") return; // no_trade or other

   // Extract trade fields from nested "trade" object
   // Find the trade object substring
   int tradeStart = StringFind(response, "\"trade\":");
   if (tradeStart < 0) return;
   tradeStart += 8; // skip past "trade":
   string tradeJson = StringSubstr(response, tradeStart);

   string tradeID    = JsonGetString(tradeJson, "id");
   string symbol     = JsonGetString(tradeJson, "symbol");
   string direction  = JsonGetString(tradeJson, "direction");
   double entry      = JsonGetDouble(tradeJson, "entry");
   double sl         = JsonGetDouble(tradeJson, "sl");
   double tp         = JsonGetDouble(tradeJson, "tp");
   double riskPct    = JsonGetDouble(tradeJson, "risk_percent");
   double lotSize    = JsonGetDouble(tradeJson, "lot_size");
   double beTrigger  = JsonGetDouble(tradeJson, "be_trigger_rr");
   string journalID  = JsonGetString(tradeJson, "journal_trade_id");
   string paperFlag  = JsonGetString(tradeJson, "paper_trading");
   string testFlag   = JsonGetString(tradeJson, "test_only");
   bool   isPaper    = (paperFlag == "true" || paperFlag == "True" || paperFlag == "1");
   bool   isTest     = (testFlag == "true" || testFlag == "True" || testFlag == "1");

   if (StringLen(tradeID) == 0 || StringLen(symbol) == 0)
   {
      Print("POIWatcher EXEC: Invalid trade data — missing ID or symbol");
      return;
   }

   Print("POIWatcher EXEC: Trade ready — ", tradeID, " ", symbol, " ", direction,
         " Entry:", DoubleToString(entry, 5), " SL:", DoubleToString(sl, 5),
         " TP:", DoubleToString(tp, 5), " Lot:", DoubleToString(lotSize, 2),
         (isPaper ? " [PAPER]" : ""), (isTest ? " [TEST]" : ""));

   // ── SAFETY CHECKS ──

   // 0. TEST trade — never call OrderSend, just acknowledge end-to-end
   if (isTest)
   {
      Print("POIWatcher EXEC: TEST TRADE received — pipeline OK, no OrderSend");
      SendExecutionResultEx(tradeID, 999999, entry, "", true, true);
      MarkTradeExecuted(tradeID);
      return;
   }

   // 0b. PAPER mode + LIVE account guard. If backend says paper, EA must be on a demo account
   //     (or the user has explicitly opted in via AllowLiveExecution).
   if (isPaper)
   {
      bool isDemo = (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO);
      if (!isDemo && !AllowLiveExecution)
      {
         Print("POIWatcher EXEC: Backend in PAPER mode but account is LIVE and AllowLiveExecution=false — REJECTED");
         SendExecutionResultEx(tradeID, 0, 0, "Paper trade refused on live account", true, false);
         MarkTradeExecuted(tradeID);
         return;
      }
   }

   // 1. Already executed?
   if (IsExecutedTradeID(tradeID))
   {
      Print("POIWatcher EXEC: Trade ", tradeID, " already executed — skipping");
      return;
   }

   // 2. Symbol available in MT4?
   double testBid = MarketInfo(symbol, MODE_BID);
   if (testBid <= 0)
   {
      Print("POIWatcher EXEC: Symbol ", symbol, " not available in MT4 — REJECTED");
      SendExecutionResult(tradeID, 0, 0, "Symbol not available in MT4: " + symbol);
      MarkTradeExecuted(tradeID);
      return;
   }

   // 3. Market open?
   int spread = (int)MarketInfo(symbol, MODE_SPREAD);
   if (spread <= 0)
   {
      Print("POIWatcher EXEC: Market appears closed for ", symbol, " (spread=0) — skipping");
      return; // Don't mark as executed — retry next cycle
   }

   // 4. Already have open trade on same symbol?
   if (HasOpenTradeOnSymbol(symbol))
   {
      Print("POIWatcher EXEC: Already have open trade on ", symbol, " — REJECTED");
      SendExecutionResult(tradeID, 0, 0, "Already have open trade on " + symbol);
      MarkTradeExecuted(tradeID);
      return;
   }

   // 5. Calculate lot size from risk percent if needed
   double calcLot = lotSize;
   if (riskPct > 0 && sl > 0 && entry > 0)
   {
      double riskAmount = AccountEquity() * (riskPct / 100.0);
      double slDistPoints = MathAbs(entry - sl) / MarketInfo(symbol, MODE_POINT);
      double tickValue = MarketInfo(symbol, MODE_TICKVALUE);
      if (tickValue > 0 && slDistPoints > 0)
      {
         calcLot = riskAmount / (slDistPoints * tickValue);
         calcLot = NormalizeDouble(calcLot, 2);
      }
   }

   // Apply lot size constraints
   double minLot = MarketInfo(symbol, MODE_MINLOT);
   double maxLot = MarketInfo(symbol, MODE_MAXLOT);
   double lotStep = MarketInfo(symbol, MODE_LOTSTEP);
   if (calcLot < minLot) calcLot = minLot;
   if (calcLot > maxLot) calcLot = maxLot;

   // Round to lot step
   if (lotStep > 0)
      calcLot = MathFloor(calcLot / lotStep) * lotStep;
   calcLot = NormalizeDouble(calcLot, 2);

   // 6. Lot size safety cap
   if (calcLot > MaxLotSize)
   {
      Print("POIWatcher EXEC: Calculated lot ", DoubleToString(calcLot, 2),
            " exceeds MaxLotSize ", DoubleToString(MaxLotSize, 2), " — REJECTED");
      SendExecutionResult(tradeID, 0, 0,
            "Lot size " + DoubleToString(calcLot, 2) + " exceeds max " + DoubleToString(MaxLotSize, 2));
      MarkTradeExecuted(tradeID);
      return;
   }

   // ── EXECUTE TRADE ──
   int cmd = -1;
   if (direction == "BUY")  cmd = OP_BUY;
   if (direction == "SELL") cmd = OP_SELL;
   if (cmd < 0)
   {
      Print("POIWatcher EXEC: Invalid direction '", direction, "' — REJECTED");
      SendExecutionResult(tradeID, 0, 0, "Invalid direction: " + direction);
      MarkTradeExecuted(tradeID);
      return;
   }

   int digits = (int)MarketInfo(symbol, MODE_DIGITS);
   double price;
   if (cmd == OP_BUY)
      price = MarketInfo(symbol, MODE_ASK);
   else
      price = MarketInfo(symbol, MODE_BID);

   // Slippage in points
   int slippagePoints = MaxSlippagePips;
   if (digits == 3 || digits == 5)
      slippagePoints = MaxSlippagePips * 10;

   string comment = "POIWatcher_" + tradeID;

   double normSL = NormalizeDouble(sl, digits);
   double normTP = NormalizeDouble(tp, digits);

   Print("POIWatcher EXEC: Executing ", (cmd == OP_BUY ? "BUY" : "SELL"), " ",
         symbol, " ", DoubleToString(calcLot, 2), " lots @ ",
         DoubleToString(price, digits), " SL:", DoubleToString(normSL, digits),
         " TP:", DoubleToString(normTP, digits), " slip:", slippagePoints);

   int ticket = OrderSend(symbol, cmd, calcLot, price, slippagePoints,
                          normSL, normTP, comment, 0, 0,
                          cmd == OP_BUY ? clrLime : clrRed);

   MarkTradeExecuted(tradeID); // Always mark to prevent retry loops

   if (ticket > 0)
   {
      // Success!
      if (OrderSelect(ticket, SELECT_BY_TICKET))
      {
         double actualEntry = OrderOpenPrice();
         Print("POIWatcher EXEC: SUCCESS — Ticket #", ticket,
               " ", symbol, " ", (cmd == OP_BUY ? "BUY" : "SELL"),
               " @ ", DoubleToString(actualEntry, digits),
               " Lot: ", DoubleToString(calcLot, 2),
               (isPaper ? " [PAPER]" : ""));

         SendExecutionResultEx(tradeID, ticket, actualEntry, "", isPaper, false);
      }
   }
   else
   {
      int err = GetLastError();
      string errMsg = "OrderSend failed: error " + IntegerToString(err);
      Print("POIWatcher EXEC: FAILED — ", errMsg, " for ", symbol);
      SendExecutionResultEx(tradeID, 0, 0, errMsg, isPaper, false);
   }
}

//+------------------------------------------------------------------+
//| Send execution result to backend (legacy, no paper/test flags)   |
//+------------------------------------------------------------------+
void SendExecutionResult(string tradeID, int ticket, double actualEntry, string error)
{
   SendExecutionResultEx(tradeID, ticket, actualEntry, error, false, false);
}

//+------------------------------------------------------------------+
//| Send execution result to backend with paper/test flags           |
//+------------------------------------------------------------------+
void SendExecutionResultEx(string tradeID, int ticket, double actualEntry, string error, bool paper, bool test)
{
   string json = "{";
   json += "\"id\":\"" + tradeID + "\",";
   json += "\"ticket\":" + IntegerToString(ticket) + ",";
   json += "\"actual_entry\":" + DoubleToString(actualEntry, 5) + ",";
   json += "\"paper\":" + (paper ? "true" : "false") + ",";
   json += "\"test\":" + (test ? "true" : "false") + ",";
   json += "\"timestamp\":\"" + TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS) + "\"";
   if (StringLen(error) > 0)
      json += ",\"error\":\"" + error + "\"";
   json += "}";

   HttpPostWithKey("/api/trade/executed", json);
}

//+------------------------------------------------------------------+
//| Emergency stop — poll backend; close all POIWatcher_ trades       |
//+------------------------------------------------------------------+
void CheckForEmergencyStop()
{
   // GET /api/mt4/emergency-stop (no auth required for read)
   string url = BackendURL + "/api/mt4/emergency-stop";
   string headers = "Content-Type: application/json\r\n";
   char   postData[];
   char   result[];
   string resultHeaders;

   ArrayResize(postData, 0);

   int res = WebRequest("GET", url, headers, 5000, postData, result, resultHeaders);
   if (res < 200 || res >= 300) return;

   string response = CharArrayToString(result);
   string activeStr = JsonGetString(response, "active");
   bool active = (activeStr == "true" || activeStr == "True" || activeStr == "1");
   if (!active) return;

   string at = JsonGetString(response, "at");
   if (at == lastEmergencyAt) return; // already handled this one

   Print("POIWatcher: !!! EMERGENCY STOP received (at=", at, ") — closing all POIWatcher_ positions");
   int closed = CloseAllPOIWatcherTrades();
   lastEmergencyAt = at;

   // Acknowledge to backend so it can clear the flag
   string ackJson = "{\"closed_count\":" + IntegerToString(closed) +
                    ",\"timestamp\":\"" + TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS) + "\"}";

   string ackHeaders = "Content-Type: application/json\r\nX-Execution-Key: " + ExecutionAPIKey + "\r\n";
   char   ackData[];
   char   ackResult[];
   string ackResultHeaders;
   StringToCharArray(ackJson, ackData, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(ackData, ArraySize(ackData) - 1);

   int ackRes = WebRequest("DELETE", BackendURL + "/api/mt4/emergency-stop", ackHeaders, 5000,
                           ackData, ackResult, ackResultHeaders);
   if (ackRes < 200 || ackRes >= 300)
      Print("POIWatcher: emergency-stop DELETE returned HTTP ", ackRes);
   else
      Print("POIWatcher: emergency-stop acknowledged (closed ", closed, ")");
}

//+------------------------------------------------------------------+
//| Close every order whose comment starts with POIWatcher_           |
//+------------------------------------------------------------------+
int CloseAllPOIWatcherTrades()
{
   int closed = 0;
   // Iterate from the end — closing changes the index
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if (OrderType() > OP_SELL) continue; // skip pending orders

      string cmt = OrderComment();
      if (StringFind(cmt, "POIWatcher_") != 0) continue;

      double price;
      if (OrderType() == OP_BUY)
         price = MarketInfo(OrderSymbol(), MODE_BID);
      else
         price = MarketInfo(OrderSymbol(), MODE_ASK);

      int slip = MaxSlippagePips;
      int digits = (int)MarketInfo(OrderSymbol(), MODE_DIGITS);
      if (digits == 3 || digits == 5) slip = MaxSlippagePips * 10;

      bool ok = OrderClose(OrderTicket(), OrderLots(), price, slip, clrYellow);
      if (ok)
      {
         closed++;
         Print("POIWatcher: emergency-closed ticket #", OrderTicket(), " ", OrderSymbol());
      }
      else
      {
         Print("POIWatcher: emergency-close FAILED ticket #", OrderTicket(),
               " err=", GetLastError());
      }
   }
   return closed;
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
