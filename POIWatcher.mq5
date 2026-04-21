//+------------------------------------------------------------------+
//|                                                  POIWatcher.mq5  |
//|                    Trading System Auto-Logger & BE Bot for MT5   |
//|                                                                  |
//| Monitors all open positions, auto-logs to POIWatcher backend,    |
//| and automatically moves SL to break even at configurable R:R.    |
//|                                                                  |
//| ─────────────────────────────────────────────────────────────── |
//| INSTALLATION — MetaTrader 5                                      |
//| ─────────────────────────────────────────────────────────────── |
//| 1. In MT5 go to File → Open Data Folder                         |
//| 2. Navigate to:  MQL5 → Experts                                 |
//| 3. Copy POIWatcher.mq5 into that folder                         |
//| 4. Back in MT5 press F4 to open MetaEditor                      |
//| 5. In MetaEditor:  File → Open → POIWatcher.mq5                 |
//| 6. Press F7 to compile — must show 0 errors                     |
//| 7. Close MetaEditor.  In MT5 Navigator press F5 (refresh)       |
//| 8. Drag "POIWatcher" onto ANY chart                             |
//| 9. In the EA popup, configure your inputs in the "Inputs" tab   |
//|10. Make sure "AutoTrading" button (top toolbar) is ON           |
//|11. Tools → Options → Expert Advisors:                           |
//|      ✓ Allow automated trading                                   |
//|      ✓ Allow WebRequest for listed URL                           |
//|      Add URL: https://poiwatcher-backend.onrender.com            |
//|                                                                  |
//| ─────────────────────────────────────────────────────────────── |
//| BROKER COMPATIBILITY                                             |
//| ─────────────────────────────────────────────────────────────── |
//| Tested on / designed to work with:                              |
//|   • MetaQuotes demo server  (default MT5 demo)                  |
//|   • FTMO MT5 server                                              |
//|   • FOREX.com MT5 server                                         |
//|   • Any standard MT5 broker (5-digit or 3-digit pricing)        |
//|                                                                  |
//| ─────────────────────────────────────────────────────────────── |
//| KEY DIFFERENCE FROM MQL4 VERSION                                 |
//| ─────────────────────────────────────────────────────────────── |
//|   • Uses CTrade class for order/position management             |
//|   • PositionSelect / PositionGetXxx instead of OrderSelect      |
//|   • History deals (HistorySelectByPosition) for closed trades   |
//|   • Position tickets are ulong, not int                         |
//|   • MarketInfo() replaced by SymbolInfoDouble/Integer()         |
//|   • AccountEquity() replaced by AccountInfoDouble(ACCOUNT_*)   |
//+------------------------------------------------------------------+
#property copyright "POIWatcher"
#property link      "https://github.com/Chukwuemeka001/poiwatcher-backend"
#property version   "2.00"
#property description "Auto-logger, Break-Even Bot and Trade Execution Pipeline for MT5"

#include <Trade/Trade.mqh>

//=== User configurable inputs =========================================
input string   BackendURL             = "https://poiwatcher-backend.onrender.com";
input bool     EnableAutoBreakEven    = true;
input double   BreakEvenRR            = 1.5;
input bool     EnableAutoLogging      = true;
input int      HeartbeatMinutes       = 5;

//--- Trade Execution Pipeline
input bool     EnableAutoExecution    = false; // OFF by default - must be manually enabled
input string   ExecutionAPIKey        = "";    // Must match EXECUTION_API_KEY on backend
input int      MaxSlippagePips        = 3;     // Max acceptable slippage in pips
input int      ExecutionCheckSeconds  = 5;     // How often to poll backend for approved trades
input double   MaxLotSize             = 1.0;   // Hard safety cap - never execute above this
input bool     AllowLiveExecution     = false; // Allow execution on LIVE when backend is PAPER mode
input int      EmergencyCheckSeconds  = 10;    // How often to poll the emergency stop endpoint

//=== Internal state ===================================================
//--- Position tracking (MQL5 uses ulong position tickets, not int)
ulong    knownPositionTickets[];
double   knownSL[];
double   knownTP[];
bool     beApplied[];
datetime lastHeartbeat  = 0;
datetime lastCheck      = 0;

//--- Execution pipeline state
string   executedTradeIDs[];
datetime lastExecCheck      = 0;
datetime lastEmergencyCheck = 0;
string   lastEmergencyAt    = "";  // unused — kept for future kill-switch use
bool     g_emergencyActive  = false; // true = backend said pause, skip new executions

//--- CTrade instance (MQL5 replacement for OrderSend / OrderModify)
CTrade trade;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("POIWatcher EA v2.00 (MT5) initialised — Backend: ", BackendURL);
   Print("Auto Break Even: ", EnableAutoBreakEven ? "ON" : "OFF",
         " at 1:", DoubleToString(BreakEvenRR, 1), " RR");
   Print("Auto Execution: ", EnableAutoExecution ? "ON" : "OFF",
         " | MaxLot: ", DoubleToString(MaxLotSize, 2),
         " | Check every ", ExecutionCheckSeconds, "s");

   if (EnableAutoExecution && StringLen(ExecutionAPIKey) == 0)
      Print("WARNING: Auto Execution enabled but ExecutionAPIKey is empty!");

   // Diagnostic: print first 4 chars of the key + length so we can verify
   // the input reaches the EA correctly (helps diagnose 401s from backend).
   // Never print the full key.
   int keyLen = StringLen(ExecutionAPIKey);
   if (keyLen == 0)
      Print("POIWatcher EXEC: ExecutionAPIKey is EMPTY (len=0)");
   else
   {
      string keyPrefix = (keyLen >= 4) ? StringSubstr(ExecutionAPIKey, 0, 4) : ExecutionAPIKey;
      Print("POIWatcher EXEC: ExecutionAPIKey loaded — first4='", keyPrefix,
            "' len=", keyLen);
   }

   bool isDemoAcct = (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO);
   Print("Account mode: ", isDemoAcct ? "DEMO" : "LIVE",
         " | AllowLiveExecution=", AllowLiveExecution ? "true" : "false",
         " | Emergency poll every ", EmergencyCheckSeconds, "s");

   // Configure CTrade
   trade.SetExpertMagicNumber(0);
   // Deviation in points: 5-digit broker → 1 pip = 10 points
   trade.SetDeviationInPoints((ulong)MaxSlippagePips * 10);
   trade.SetAsyncMode(false);

   // Snapshot existing open positions so we don't re-log them
   ScanOpenPositions();

   // Initial heartbeat
   SendHeartbeat();
   lastHeartbeat = TimeCurrent();
   lastCheck     = TimeCurrent();

   EventSetTimer(1); // 1-second heartbeat; all logic is self-throttled
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("POIWatcher EA removed (reason=", reason, ")");
}

//+------------------------------------------------------------------+
//| Timer — fires every 1 second; all logic is internally throttled  |
//+------------------------------------------------------------------+
void OnTimer()
{
   datetime now = TimeCurrent();

   // ── Trade monitoring ── (every 60 seconds)
   if (now - lastCheck >= 60)
   {
      lastCheck = now;
      CheckForNewPositions();
      CheckForClosedPositions();
      CheckForModifications();
      if (EnableAutoBreakEven)
         CheckBreakEven();
   }

   // ── Execution pipeline poll ──
   // Skipped entirely when g_emergencyActive is true (backend remote-pause)
   if (EnableAutoExecution && !g_emergencyActive && now - lastExecCheck >= ExecutionCheckSeconds)
   {
      lastExecCheck = now;
      CheckForPendingExecution();
   }
   else if (EnableAutoExecution && g_emergencyActive && now - lastExecCheck >= ExecutionCheckSeconds)
   {
      lastExecCheck = now;
      Print("POIWatcher: Emergency stop ACTIVE — skipping execution poll");
   }

   // ── Emergency stop poll (always active — safety first) ──
   if (now - lastEmergencyCheck >= EmergencyCheckSeconds)
   {
      lastEmergencyCheck = now;
      CheckForEmergencyStop();
   }

   // ── Heartbeat ──
   if (now - lastHeartbeat >= HeartbeatMinutes * 60)
   {
      lastHeartbeat = now;
      SendHeartbeat();
   }
}

//+------------------------------------------------------------------+
//| OnTick — backup driver in case Timer doesn't fire on some       |
//| broker servers (e.g. weekend tick simulation)                   |
//+------------------------------------------------------------------+
void OnTick()
{
   OnTimer();
}

//+------------------------------------------------------------------+
//| Snapshot all currently open positions on startup                 |
//+------------------------------------------------------------------+
void ScanOpenPositions()
{
   ArrayResize(knownPositionTickets, 0);
   ArrayResize(knownSL, 0);
   ArrayResize(knownTP, 0);
   ArrayResize(beApplied, 0);

   int total = PositionsTotal();
   for (int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0) continue;
      if (!PositionSelectByTicket(ticket)) continue;

      string sym   = PositionGetString(POSITION_SYMBOL);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double pt    = SymbolInfoDouble(sym, SYMBOL_POINT);

      int size = ArraySize(knownPositionTickets);
      ArrayResize(knownPositionTickets, size + 1);
      ArrayResize(knownSL, size + 1);
      ArrayResize(knownTP, size + 1);
      ArrayResize(beApplied, size + 1);

      knownPositionTickets[size] = ticket;
      knownSL[size]              = sl;
      knownTP[size]              = PositionGetDouble(POSITION_TP);
      // BE already applied if SL is within 1 point of entry
      beApplied[size]            = (sl > 0 && MathAbs(sl - entry) < pt);
   }

   Print("POIWatcher: Snapshot — ", ArraySize(knownPositionTickets),
         " open position(s) on startup");
}

//+------------------------------------------------------------------+
//| Detect newly opened positions and log them                       |
//+------------------------------------------------------------------+
void CheckForNewPositions()
{
   int total = PositionsTotal();
   for (int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0 || IsKnownPosition(ticket)) continue;
      if (!PositionSelectByTicket(ticket)) continue;

      // Add to tracking arrays
      int size = ArraySize(knownPositionTickets);
      ArrayResize(knownPositionTickets, size + 1);
      ArrayResize(knownSL, size + 1);
      ArrayResize(knownTP, size + 1);
      ArrayResize(beApplied, size + 1);

      knownPositionTickets[size] = ticket;
      knownSL[size]              = PositionGetDouble(POSITION_SL);
      knownTP[size]              = PositionGetDouble(POSITION_TP);
      beApplied[size]            = false;

      string sym  = PositionGetString(POSITION_SYMBOL);
      long   pTyp = PositionGetInteger(POSITION_TYPE);
      Print("POIWatcher: New position — #", ticket, " ", sym,
            " ", (pTyp == POSITION_TYPE_BUY ? "Long" : "Short"));

      if (EnableAutoLogging)
         SendPositionOpen(ticket);
   }
}

//+------------------------------------------------------------------+
//| Detect positions that have been closed and log them              |
//+------------------------------------------------------------------+
void CheckForClosedPositions()
{
   for (int k = ArraySize(knownPositionTickets) - 1; k >= 0; k--)
   {
      ulong ticket = knownPositionTickets[k];

      // PositionSelectByTicket returns false when position is no longer open
      if (PositionSelectByTicket(ticket))
         continue; // still open

      Print("POIWatcher: Position #", ticket, " closed");

      if (EnableAutoLogging)
         SendPositionClose(ticket);

      RemovePosition(k);
   }
}

//+------------------------------------------------------------------+
//| Detect SL/TP modifications and log them                          |
//+------------------------------------------------------------------+
void CheckForModifications()
{
   int total = PositionsTotal();
   for (int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0) continue;
      if (!PositionSelectByTicket(ticket)) continue;

      int idx = GetPositionIndex(ticket);
      if (idx < 0) continue;

      string sym  = PositionGetString(POSITION_SYMBOL);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      double pt    = SymbolInfoDouble(sym, SYMBOL_POINT);

      bool slChanged = (MathAbs(curSL - knownSL[idx]) > pt);
      bool tpChanged = (MathAbs(curTP - knownTP[idx]) > pt);

      if (!slChanged && !tpChanged) continue;

      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      string modification;
      if (slChanged && MathAbs(curSL - entry) < pt * 2)
         modification = "SL moved to BE";
      else if (slChanged && tpChanged)
         modification = "Both";
      else if (slChanged)
         modification = "SL adjusted";
      else
         modification = "TP adjusted";

      Print("POIWatcher: Position modified — #", ticket, " ", sym, " — ", modification);
      knownSL[idx] = curSL;
      knownTP[idx] = curTP;

      if (EnableAutoLogging)
         SendPositionModify(ticket, modification);
   }
}

//+------------------------------------------------------------------+
//| Auto break even — move SL to entry once R:R target is reached   |
//+------------------------------------------------------------------+
void CheckBreakEven()
{
   int total = PositionsTotal();
   for (int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0) continue;
      if (!PositionSelectByTicket(ticket)) continue;

      int idx = GetPositionIndex(ticket);
      if (idx < 0 || beApplied[idx]) continue;

      string sym  = PositionGetString(POSITION_SYMBOL);
      long   pTyp = PositionGetInteger(POSITION_TYPE);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double pt    = SymbolInfoDouble(sym, SYMBOL_POINT);
      double bid   = SymbolInfoDouble(sym, SYMBOL_BID);
      double ask   = SymbolInfoDouble(sym, SYMBOL_ASK);

      if (sl == 0) continue; // no SL set — skip

      double risk = MathAbs(entry - sl);
      if (risk < pt) continue; // degenerate SL

      double currentProfit = (pTyp == POSITION_TYPE_BUY) ? (bid - entry) : (entry - ask);
      double currentRR     = currentProfit / risk;
      if (currentRR < BreakEvenRR) continue;

      // Move SL to entry
      int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double newSL  = NormalizeDouble(entry, digits);

      if (trade.PositionModify(sym, newSL, tp))
      {
         beApplied[idx] = true;
         knownSL[idx]   = newSL;
         Print("POIWatcher: AUTO BE — #", ticket, " ", sym,
               " SL → entry @ RR 1:", DoubleToString(currentRR, 2));
         if (EnableAutoLogging)
            SendPositionModify(ticket, "SL moved to BE");
      }
      else
      {
         Print("POIWatcher: BE FAILED — #", ticket, " ", sym,
               " retcode=", trade.ResultRetcode(),
               " (", trade.ResultRetcodeDescription(), ")");
      }
   }
}


//====================================================================
//  TRADE EXECUTION PIPELINE
//====================================================================

//--- Duplicate-execution guard
bool IsExecutedTradeID(string tradeID)
{
   for (int i = 0; i < ArraySize(executedTradeIDs); i++)
      if (executedTradeIDs[i] == tradeID) return true;
   return false;
}

void MarkTradeExecuted(string tradeID)
{
   int sz = ArraySize(executedTradeIDs);
   ArrayResize(executedTradeIDs, sz + 1);
   executedTradeIDs[sz] = tradeID;
}

bool HasOpenPositionOnSymbol(string symbol)
{
   int total = PositionsTotal();
   for (int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0) continue;
      if (PositionSelectByTicket(ticket) &&
          PositionGetString(POSITION_SYMBOL) == symbol)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Minimal JSON string extractor: "key":"value"                    |
//+------------------------------------------------------------------+
string JsonGetString(const string &json, string key)
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
//| Minimal JSON number extractor: "key":123.45                     |
//+------------------------------------------------------------------+
double JsonGetDouble(const string &json, string key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if (pos < 0) return 0;
   pos += StringLen(search);
   // skip spaces
   while (pos < StringLen(json) && StringGetCharacter(json, pos) == ' ') pos++;
   // find end of value
   int end = pos;
   while (end < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, end);
      if (ch == ',' || ch == '}' || ch == ']') break;
      end++;
   }
   string val = StringSubstr(json, pos, end - pos);
   StringTrimLeft(val);
   StringTrimRight(val);
   // strip surrounding quotes if present (e.g. "true"/"false" booleans parsed as number = 0, handled separately)
   if (StringLen(val) >= 2 &&
       StringGetCharacter(val, 0) == '"' &&
       StringGetCharacter(val, StringLen(val) - 1) == '"')
      val = StringSubstr(val, 1, StringLen(val) - 2);
   return StringToDouble(val);
}

//+------------------------------------------------------------------+
//| HTTP GET with X-Execution-Key header                            |
//+------------------------------------------------------------------+
string HttpGetWithKey(string endpoint)
{
   string url     = BackendURL + endpoint;
   string headers = "Content-Type: application/json\r\n"
                    "X-Execution-Key: " + ExecutionAPIKey + "\r\n";
   char   postData[];
   char   result[];
   string resultHeaders;

   ArrayResize(postData, 0);
   int res = WebRequest("GET", url, headers, 5000, postData, result, resultHeaders);

   if (res == -1)
   {
      int err = GetLastError();
      // MQL5 codes: 4014 = DLL/WebRequest not allowed; 4060 = general HTTP error;
      // 5201 = invalid address / not in allowed list; 5202 = timeout
      if (err == 4014 || err == 4060 || err == 5201)
         Print("POIWatcher EXEC: WebRequest BLOCKED — add  ", BackendURL,
               "  to Tools → Options → Expert Advisors → Allow WebRequest for listed URL");
      else
         Print("POIWatcher EXEC: HTTP error ", err, " on GET ", endpoint);
      return "";
   }

   string response = CharArrayToString(result);
   if (res >= 200 && res < 300) return response;
   Print("POIWatcher EXEC: HTTP ", res, " on GET ", endpoint, " — ", response);
   return "";
}

//+------------------------------------------------------------------+
//| HTTP POST with X-Execution-Key header                           |
//+------------------------------------------------------------------+
void HttpPostWithKey(string endpoint, string jsonBody)
{
   string url     = BackendURL + endpoint;
   string headers = "Content-Type: application/json\r\n"
                    "X-Execution-Key: " + ExecutionAPIKey + "\r\n";
   char   postData[];
   char   result[];
   string resultHeaders;

   StringToCharArray(jsonBody, postData, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(postData, ArraySize(postData) - 1); // remove null terminator

   int res = WebRequest("POST", url, headers, 5000, postData, result, resultHeaders);

   if (res == -1)
   {
      int err = GetLastError();
      if (err == 4014 || err == 4060 || err == 5201)
         Print("POIWatcher EXEC: WebRequest BLOCKED — add  ", BackendURL,
               "  to Tools → Options → Expert Advisors → Allow WebRequest for listed URL");
      else
         Print("POIWatcher EXEC: HTTP error ", err, " on POST ", endpoint);
   }
   else if (res < 200 || res >= 300)
   {
      string response = CharArrayToString(result);
      Print("POIWatcher EXEC: HTTP ", res, " on POST ", endpoint, " — ", response);
   }
}

//+------------------------------------------------------------------+
//| HTTP POST without authentication (public endpoints)             |
//+------------------------------------------------------------------+
void HttpPost(string endpoint, string jsonBody)
{
   string url     = BackendURL + endpoint;
   string headers = "Content-Type: application/json\r\n";
   char   postData[];
   char   result[];
   string resultHeaders;

   StringToCharArray(jsonBody, postData, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(postData, ArraySize(postData) - 1);

   int res = WebRequest("POST", url, headers, 5000, postData, result, resultHeaders);

   if (res == -1)
   {
      int err = GetLastError();
      if (err == 4014 || err == 4060 || err == 5201)
         Print("POIWatcher: WebRequest BLOCKED — add  ", BackendURL,
               "  to Tools → Options → Expert Advisors → Allow WebRequest for listed URL");
      else
         Print("POIWatcher: HTTP error ", err, " on ", endpoint);
   }
   else if (res < 200 || res >= 300)
   {
      string response = CharArrayToString(result);
      Print("POIWatcher: HTTP ", res, " on ", endpoint, " — ", response);
   }
}

//+------------------------------------------------------------------+
//| Poll backend for an approved trade and execute it               |
//+------------------------------------------------------------------+
void CheckForPendingExecution()
{
   if (!EnableAutoExecution) return;
   if (StringLen(ExecutionAPIKey) == 0)
   {
      Print("POIWatcher EXEC: ExecutionAPIKey not set — skipping");
      return;
   }

   // Equity floor safety check
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if (equity < 100.0)
   {
      Print("POIWatcher EXEC: Equity $", DoubleToString(equity, 2),
            " below $100 floor — skipping");
      return;
   }

   // Fetch next approved trade from backend
   string response = HttpGetWithKey("/api/trade");

   // Diagnostic — log every poll so we can see EA activity in MT5 Experts log.
   // Truncate long responses to keep the log readable.
   string logResp = response;
   if (StringLen(logResp) == 0)
      logResp = "<empty/error>";
   else if (StringLen(logResp) > 200)
      logResp = StringSubstr(logResp, 0, 200) + "...";
   Print("POIWatcher EXEC: Polling /api/trade... response: ", logResp);

   if (StringLen(response) == 0) return;

   string status = JsonGetString(response, "status");
   if (status != "trade_ready") return; // "no_trade" or other — nothing to do

   // Extract nested "trade" object
   int tradeStart = StringFind(response, "\"trade\":");
   if (tradeStart < 0) return;
   tradeStart += 8; // skip past "trade":
   string tj = StringSubstr(response, tradeStart); // tj = trade JSON substring

   string tradeID   = JsonGetString(tj, "id");
   string symbol    = JsonGetString(tj, "symbol");
   string direction = JsonGetString(tj, "direction");
   double entry     = JsonGetDouble(tj, "entry");
   double sl        = JsonGetDouble(tj, "sl");
   double tp        = JsonGetDouble(tj, "tp");
   double riskPct   = JsonGetDouble(tj, "risk_percent");
   double lotSize   = JsonGetDouble(tj, "lot_size");
   string paperFlag = JsonGetString(tj, "paper_trading");
   string testFlag  = JsonGetString(tj, "test_only");
   bool   isPaper   = (paperFlag == "true" || paperFlag == "True" || paperFlag == "1");
   bool   isTest    = (testFlag  == "true" || testFlag  == "True" || testFlag  == "1");

   if (StringLen(tradeID) == 0 || StringLen(symbol) == 0)
   {
      Print("POIWatcher EXEC: Malformed trade response — missing id or symbol");
      return;
   }

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if (digits == 0) digits = 5; // sensible default

   Print("POIWatcher EXEC: Trade ready — ", tradeID, " ", symbol, " ", direction,
         " entry=", DoubleToString(entry, digits),
         " sl=",    DoubleToString(sl,    digits),
         " tp=",    DoubleToString(tp,    digits),
         " lot=",   DoubleToString(lotSize, 2),
         (isPaper ? " [PAPER]" : ""), (isTest ? " [TEST]" : ""));

   //── SAFETY CHECKS ──────────────────────────────────────────────

   // 0. TEST trade — full pipeline acknowledgement, no real OrderSend
   if (isTest)
   {
      Print("POIWatcher EXEC: TEST TRADE — pipeline OK, no order placed");
      SendExecutionResultEx(tradeID, 999999, entry, "", true, true);
      MarkTradeExecuted(tradeID);
      return;
   }

   // 0b. Paper-mode guard: refuse if backend is in PAPER mode and this is a LIVE account
   if (isPaper)
   {
      bool isDemo = (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO);
      if (!isDemo && !AllowLiveExecution)
      {
         Print("POIWatcher EXEC: PAPER trade refused — account is LIVE "
               "and AllowLiveExecution=false");
         SendExecutionResultEx(tradeID, 0, 0,
               "Paper trade refused on live account", true, false);
         MarkTradeExecuted(tradeID);
         return;
      }
   }

   // 1. Already executed? (duplicate guard)
   if (IsExecutedTradeID(tradeID))
   {
      Print("POIWatcher EXEC: Trade ", tradeID, " already processed — skipping");
      return;
   }

   // 2. Symbol available?
   double testBid = SymbolInfoDouble(symbol, SYMBOL_BID);
   if (testBid <= 0)
   {
      // Try adding to MarketWatch first (MT5 may not have it subscribed)
      SymbolSelect(symbol, true);
      testBid = SymbolInfoDouble(symbol, SYMBOL_BID);
      if (testBid <= 0)
      {
         Print("POIWatcher EXEC: Symbol ", symbol, " has no price data — REJECTED");
         SendExecutionResultEx(tradeID, 0, 0,
               "Symbol unavailable: " + symbol, isPaper, false);
         MarkTradeExecuted(tradeID);
         return;
      }
   }

   // 3. Market open? (spread > 0 indicates market session)
   long spread = SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   if (spread <= 0)
   {
      Print("POIWatcher EXEC: Market closed for ", symbol, " (spread=0) — will retry");
      return; // NOT marked as executed — will retry next poll cycle
   }

   // 4. One position per symbol (risk management)
   if (HasOpenPositionOnSymbol(symbol))
   {
      Print("POIWatcher EXEC: Position already open on ", symbol, " — REJECTED");
      SendExecutionResultEx(tradeID, 0, 0,
            "Already have an open position on " + symbol, isPaper, false);
      MarkTradeExecuted(tradeID);
      return;
   }

   // 5. Lot size calculation from risk percent
   double calcLot = lotSize;
   if (riskPct > 0 && sl > 0 && entry > 0)
   {
      double riskAmount = equity * (riskPct / 100.0);
      double tickVal    = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize   = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      double slDist     = MathAbs(entry - sl);

      // calcLot = riskAmount / (slDist / tickSize * tickVal)
      //         = riskAmount * tickSize / (slDist * tickVal)
      if (tickVal > 0 && tickSize > 0 && slDist > 0)
      {
         calcLot = (riskAmount * tickSize) / (slDist * tickVal);
         calcLot = NormalizeDouble(calcLot, 2);
      }
   }

   // Clamp to broker constraints
   double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if (calcLot < minLot) calcLot = minLot;
   if (calcLot > maxLot) calcLot = maxLot;
   if (lotStep > 0)
      calcLot = MathFloor(calcLot / lotStep) * lotStep;
   calcLot = NormalizeDouble(calcLot, 2);

   // 6. Hard lot cap
   if (calcLot > MaxLotSize)
   {
      Print("POIWatcher EXEC: Lot ", DoubleToString(calcLot, 2),
            " exceeds MaxLotSize ", DoubleToString(MaxLotSize, 2), " — REJECTED");
      SendExecutionResultEx(tradeID, 0, 0,
            "Lot " + DoubleToString(calcLot, 2) +
            " exceeds max " + DoubleToString(MaxLotSize, 2),
            isPaper, false);
      MarkTradeExecuted(tradeID);
      return;
   }

   //── EXECUTE ────────────────────────────────────────────────────
   double normSL  = NormalizeDouble(sl, digits);
   double normTP  = NormalizeDouble(tp, digits);
   string comment = "POIWatcher_" + tradeID;

   // Re-apply deviation for this specific trade (in case input was changed)
   trade.SetDeviationInPoints((ulong)MaxSlippagePips * 10);

   bool success = false;

   if (direction == "BUY")
   {
      double askPrice = SymbolInfoDouble(symbol, SYMBOL_ASK);
      Print("POIWatcher EXEC: Placing BUY  ", symbol,
            " lot=", DoubleToString(calcLot, 2),
            " ask=", DoubleToString(askPrice, digits),
            " sl=",  DoubleToString(normSL, digits),
            " tp=",  DoubleToString(normTP, digits),
            (isPaper ? " [PAPER]" : ""));
      success = trade.Buy(calcLot, symbol, askPrice, normSL, normTP, comment);
   }
   else if (direction == "SELL")
   {
      double bidPrice = SymbolInfoDouble(symbol, SYMBOL_BID);
      Print("POIWatcher EXEC: Placing SELL ", symbol,
            " lot=", DoubleToString(calcLot, 2),
            " bid=", DoubleToString(bidPrice, digits),
            " sl=",  DoubleToString(normSL, digits),
            " tp=",  DoubleToString(normTP, digits),
            (isPaper ? " [PAPER]" : ""));
      success = trade.Sell(calcLot, symbol, bidPrice, normSL, normTP, comment);
   }
   else
   {
      Print("POIWatcher EXEC: Invalid direction '", direction, "' — REJECTED");
      SendExecutionResultEx(tradeID, 0, 0,
            "Invalid direction: " + direction, isPaper, false);
      MarkTradeExecuted(tradeID);
      return;
   }

   MarkTradeExecuted(tradeID); // Always mark — prevents retry loops on partial failures

   if (success)
   {
      ulong  dealTicket  = trade.ResultDeal();
      double actualEntry = trade.ResultPrice();
      uint   retcode     = trade.ResultRetcode();

      Print("POIWatcher EXEC: SUCCESS — deal #", dealTicket,
            " ", symbol, " ", direction,
            " @ ", DoubleToString(actualEntry, digits),
            " lot=", DoubleToString(calcLot, 2),
            " retcode=", retcode,
            (isPaper ? " [PAPER]" : ""));

      SendExecutionResultEx(tradeID, (int)dealTicket, actualEntry, "", isPaper, false);
   }
   else
   {
      uint   retcode = trade.ResultRetcode();
      string errMsg  = "Order failed: retcode " + IntegerToString(retcode) +
                       " (" + trade.ResultRetcodeDescription() + ")";
      Print("POIWatcher EXEC: FAILED — ", errMsg);
      SendExecutionResultEx(tradeID, 0, 0, errMsg, isPaper, false);
   }
}

//+------------------------------------------------------------------+
//| Send execution result — legacy overload (no paper/test flags)   |
//+------------------------------------------------------------------+
void SendExecutionResult(string tradeID, int ticket, double actualEntry, string error)
{
   SendExecutionResultEx(tradeID, ticket, actualEntry, error, false, false);
}

//+------------------------------------------------------------------+
//| Send execution result to backend with paper/test flags          |
//+------------------------------------------------------------------+
void SendExecutionResultEx(string tradeID, int ticket, double actualEntry,
                           string error, bool paper, bool test)
{
   string json = "{";
   json += "\"id\":\""          + tradeID                           + "\",";
   json += "\"ticket\":"        + IntegerToString(ticket)           +  ",";
   json += "\"actual_entry\":"  + DoubleToString(actualEntry, 5)    +  ",";
   json += "\"paper\":"         + (paper ? "true" : "false")        +  ",";
   json += "\"test\":"          + (test  ? "true" : "false")        +  ",";
   json += "\"timestamp\":\""   + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\"";
   if (StringLen(error) > 0)
      json += ",\"error\":\"" + error + "\"";
   json += "}";

   HttpPostWithKey("/api/trade/executed", json);
}

//+------------------------------------------------------------------+
//| Poll backend for remote-pause flag every EmergencyCheckSeconds  |
//|                                                                  |
//| Uses HttpGetWithKey (requires X-Execution-Key) and reads the    |
//| "emergency" field.  When true, sets g_emergencyActive so that   |
//| OnTimer() skips CheckForPendingExecution.                       |
//|                                                                  |
//| Existing open positions are NOT touched — this is a "pause new  |
//| trades" signal, not a "close everything" kill-switch.           |
//| For the kill-switch (close all positions) use the journal's     |
//| Emergency Stop button which POSTs to /api/execution/emergency_stop
//+------------------------------------------------------------------+
void CheckForEmergencyStop()
{
   if (StringLen(ExecutionAPIKey) == 0) return; // can't auth without key

   // Hits /api/mt5/... on MT5-aware backends, which is a route alias of the
   // legacy /api/mt4/... path. Backend accepts both for compatibility.
   string response = HttpGetWithKey("/api/mt5/emergency-stop");
   if (StringLen(response) == 0) return; // network error or not deployed yet

   string emergencyStr = JsonGetString(response, "emergency");
   bool   nowActive    = (emergencyStr == "true" || emergencyStr == "True" || emergencyStr == "1");

   if (nowActive == g_emergencyActive) return; // no state change — nothing to log

   g_emergencyActive = nowActive;

   if (nowActive)
   {
      string msg = JsonGetString(response, "message");
      Print("POIWatcher: !!! REMOTE PAUSE ACTIVATED — ",
            (StringLen(msg) > 0 ? msg : "EA will stop opening new trades"));
      Print("POIWatcher: Existing positions are UNAFFECTED. "
            "Deactivate via journal Emergency Stop to resume.");
   }
   else
   {
      Print("POIWatcher: Remote pause CLEARED — execution pipeline resumed");
   }
}

//+------------------------------------------------------------------+
//| Close every position whose comment starts with "POIWatcher_"    |
//+------------------------------------------------------------------+
int CloseAllPOIWatcherPositions()
{
   int closed = 0;
   // Iterate from end — closing changes indices
   for (int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0) continue;
      if (!PositionSelectByTicket(ticket)) continue;

      string cmt = PositionGetString(POSITION_COMMENT);
      if (StringFind(cmt, "POIWatcher_") != 0) continue; // comment must start with prefix

      string sym = PositionGetString(POSITION_SYMBOL);
      if (trade.PositionClose(ticket))
      {
         closed++;
         Print("POIWatcher: Emergency-closed #", ticket, " ", sym);
      }
      else
      {
         Print("POIWatcher: Emergency-close FAILED #", ticket, " ", sym,
               " retcode=", trade.ResultRetcode(),
               " (", trade.ResultRetcodeDescription(), ")");
      }
   }
   return closed;
}


//====================================================================
//  BACKEND LOGGING FUNCTIONS
//====================================================================

//+------------------------------------------------------------------+
//| Send position open event to backend                             |
//+------------------------------------------------------------------+
void SendPositionOpen(ulong ticket)
{
   if (!PositionSelectByTicket(ticket)) return;

   string sym    = PositionGetString(POSITION_SYMBOL);
   long   pTyp   = PositionGetInteger(POSITION_TYPE);
   double entry  = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl     = PositionGetDouble(POSITION_SL);
   double tp     = PositionGetDouble(POSITION_TP);
   double lots   = PositionGetDouble(POSITION_VOLUME);
   int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);

   string json = "{";
   json += "\"ticket\":"          + IntegerToString((long)ticket)             + ",";
   json += "\"symbol\":\""        + sym                                       + "\",";
   json += "\"direction\":\""     + (pTyp == POSITION_TYPE_BUY ? "Long" : "Short") + "\",";
   json += "\"entry_price\":"     + DoubleToString(entry, digits)             + ",";
   json += "\"stop_loss\":"       + DoubleToString(sl, digits)                + ",";
   json += "\"take_profit\":"     + DoubleToString(tp, digits)                + ",";
   json += "\"lot_size\":"        + DoubleToString(lots, 2)                   + ",";
   json += "\"timestamp\":\""     + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\",";
   json += "\"account_balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   json += "\"account_equity\":"  + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),  2) + ",";
   json += "\"platform\":\"mt5\"";
   json += "}";

   HttpPost("/mt5/trade-open", json);
}

//+------------------------------------------------------------------+
//| Send position close event to backend                            |
//|                                                                  |
//| MQL5 stores closed-position data in history DEALS.              |
//| HistorySelectByPosition(positionId) loads all deals for the     |
//| position; we find the DEAL_ENTRY_IN for open data and           |
//| DEAL_ENTRY_OUT for close data.                                  |
//+------------------------------------------------------------------+
void SendPositionClose(ulong ticket)
{
   // Load history for this specific position
   // (ticket == positionId for standard MT5 positions)
   bool histOk = HistorySelectByPosition(ticket);
   if (!histOk)
   {
      // Fallback: search last 7 days of history
      HistorySelect(TimeCurrent() - 7 * 86400, TimeCurrent());
   }

   int     dealsTotal  = HistoryDealsTotal();
   ulong   closeDeal   = 0;
   double  closePrice  = 0;
   double  profit      = 0;
   double  swapVal     = 0;
   double  commission  = 0;
   datetime openTime   = 0;
   datetime closeTime  = 0;
   double  entryPrice  = 0;
   string  symbol      = "";
   long    closeDealType = -1; // DEAL_TYPE of the closing deal

   for (int i = 0; i < dealsTotal; i++)
   {
      ulong dTicket = HistoryDealGetTicket(i);
      if (dTicket == 0) continue;

      // Only process deals belonging to this position
      ulong posId = (ulong)HistoryDealGetInteger(dTicket, DEAL_POSITION_ID);
      if (posId != ticket) continue;

      long dealEntry = HistoryDealGetInteger(dTicket, DEAL_ENTRY);

      if (dealEntry == DEAL_ENTRY_IN)
      {
         entryPrice = HistoryDealGetDouble(dTicket, DEAL_PRICE);
         openTime   = (datetime)HistoryDealGetInteger(dTicket, DEAL_TIME);
         if (symbol == "") symbol = HistoryDealGetString(dTicket, DEAL_SYMBOL);
      }
      else if (dealEntry == DEAL_ENTRY_OUT || dealEntry == DEAL_ENTRY_INOUT)
      {
         closeDeal     = dTicket;
         closePrice    = HistoryDealGetDouble(dTicket, DEAL_PRICE);
         profit        = HistoryDealGetDouble(dTicket, DEAL_PROFIT);
         swapVal       = HistoryDealGetDouble(dTicket, DEAL_SWAP);
         commission    = HistoryDealGetDouble(dTicket, DEAL_COMMISSION);
         closeTime     = (datetime)HistoryDealGetInteger(dTicket, DEAL_TIME);
         closeDealType = HistoryDealGetInteger(dTicket, DEAL_TYPE);
         if (symbol == "") symbol = HistoryDealGetString(dTicket, DEAL_SYMBOL);
      }
   }

   if (closeDeal == 0 || symbol == "")
   {
      Print("POIWatcher: Cannot find close deal for position #", ticket,
            " — not logging close");
      return;
   }

   int    digits      = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double pt          = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double pipDiv      = (digits == 3 || digits == 5) ? 10.0 : 1.0;
   double totalProfit = profit + swapVal + commission;

   // Pip calculation
   double pips = 0;
   if (entryPrice > 0 && pt > 0)
   {
      pips = MathAbs(closePrice - entryPrice) / pt / pipDiv;
      if (totalProfit < 0) pips = -pips; // losing trade = negative pips
   }

   // Derive position direction from the close deal type:
   // A SELL deal closes a BUY position; a BUY deal closes a SELL position.
   string direction = "Long";
   if (closeDealType == DEAL_TYPE_BUY)  direction = "Short"; // BUY deal closed a SELL position
   if (closeDealType == DEAL_TYPE_SELL) direction = "Long";  // SELL deal closed a BUY position

   int durationMin = (openTime > 0 && closeTime > 0)
                     ? (int)((closeTime - openTime) / 60) : 0;

   string json = "{";
   json += "\"ticket\":"            + IntegerToString((long)ticket)            + ",";
   json += "\"symbol\":\""          + symbol                                   + "\",";
   json += "\"direction\":\""       + direction                                + "\",";
   json += "\"entry_price\":"       + DoubleToString(entryPrice, digits)       + ",";
   json += "\"exit_price\":"        + DoubleToString(closePrice, digits)       + ",";
   json += "\"profit_loss\":"       + DoubleToString(totalProfit, 2)           + ",";
   json += "\"pips\":"              + DoubleToString(pips, 1)                  + ",";
   json += "\"duration_minutes\":"  + IntegerToString(durationMin)             + ",";
   json += "\"close_reason\":\"Manual close\",";
   json += "\"platform\":\"mt5\"";
   json += "}";

   HttpPost("/mt5/trade-close", json);
}

//+------------------------------------------------------------------+
//| Send position modification event to backend                     |
//+------------------------------------------------------------------+
void SendPositionModify(ulong ticket, string modification)
{
   if (!PositionSelectByTicket(ticket)) return;

   string sym    = PositionGetString(POSITION_SYMBOL);
   int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);

   string json = "{";
   json += "\"ticket\":"       + IntegerToString((long)ticket)                + ",";
   json += "\"symbol\":\""     + sym                                          + "\",";
   json += "\"new_sl\":"       + DoubleToString(PositionGetDouble(POSITION_SL), digits) + ",";
   json += "\"new_tp\":"       + DoubleToString(PositionGetDouble(POSITION_TP), digits) + ",";
   json += "\"modification\":\"" + modification                               + "\",";
   json += "\"platform\":\"mt5\"";
   json += "}";

   HttpPost("/mt5/trade-modify", json);
}

//+------------------------------------------------------------------+
//| Send heartbeat to backend                                       |
//+------------------------------------------------------------------+
void SendHeartbeat()
{
   int openCount = PositionsTotal(); // MQL5: all open positions

   string json = "{";
   json += "\"connected\":true,";
   json += "\"open_trades\":"     + IntegerToString(openCount)                           + ",";
   json += "\"account_balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   json += "\"account_equity\":"  + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),  2) + ",";
   json += "\"timestamp\":\""     + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS)  + "\",";
   json += "\"platform\":\"mt5\"";
   json += "}";

   HttpPost("/mt5/status", json);
}


//====================================================================
//  POSITION ARRAY HELPERS
//====================================================================

bool IsKnownPosition(ulong ticket)
{
   for (int i = 0; i < ArraySize(knownPositionTickets); i++)
      if (knownPositionTickets[i] == ticket) return true;
   return false;
}

int GetPositionIndex(ulong ticket)
{
   for (int i = 0; i < ArraySize(knownPositionTickets); i++)
      if (knownPositionTickets[i] == ticket) return i;
   return -1;
}

void RemovePosition(int idx)
{
   int last = ArraySize(knownPositionTickets) - 1;
   if (idx < last)
   {
      knownPositionTickets[idx] = knownPositionTickets[last];
      knownSL[idx]              = knownSL[last];
      knownTP[idx]              = knownTP[last];
      beApplied[idx]            = beApplied[last];
   }
   ArrayResize(knownPositionTickets, last);
   ArrayResize(knownSL,              last);
   ArrayResize(knownTP,              last);
   ArrayResize(beApplied,            last);
}
//+------------------------------------------------------------------+
