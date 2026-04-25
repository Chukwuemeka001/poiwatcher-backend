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
input string   OrderType              = "LIMIT"; // "LIMIT" or "MARKET" — LIMIT places pending orders at trade.entry
input int      LimitExpiryHours       = 24;    // Cancel unfilled limit orders after this many hours

//=== Internal state ===================================================
//--- Position tracking (MQL5 uses ulong position tickets, not int)
ulong    knownPositionTickets[];
double   knownSL[];
double   knownTP[];
bool     beApplied[];
//--- Journal-link tracking (parallel to knownPositionTickets[] by INDEX).
//    When the EA fetches a trade from /api/trade, the backend returns
//    `journal_trade_id` — the ID of the journal entry that spawned the trade.
//    We stash it here alongside the planned entry/sl/tp so that when the
//    position eventually closes we can send a close payload the backend
//    can match back to the right Gist entry.
string   knownJournalIDs[];
double   knownPlannedEntry[];
double   knownPlannedSL[];
double   knownPlannedTP[];
datetime lastHeartbeat  = 0;
datetime lastCheck      = 0;

//--- Execution pipeline state
string   executedTradeIDs[];
datetime lastExecCheck      = 0;
datetime lastEmergencyCheck = 0;
datetime lastPendingCheck   = 0;   // 60-second pending-limit-order monitor
string   lastEmergencyAt    = "";  // unused — kept for future kill-switch use
bool     g_emergencyActive  = false; // true = backend said pause, skip new executions

//--- Pending limit order tracking — parallel arrays keyed by the same index.
//    When a BuyLimit/SellLimit is placed we push a row here; CheckPendingLimitOrders
//    iterates every 60s to detect fills (position appeared) vs expiry (neither
//    pending order nor position found).
ulong    pendingOrderTickets[];    // MT5 pending-order ticket returned by trade.ResultOrder()
string   pendingOrderTradeIDs[];   // Backend trade id (same one EA got from /api/trade)
string   pendingOrderJournalIDs[]; // Journal entry id — forwarded on fill/close so backend can match to Gist
string   pendingOrderSymbols[];
string   pendingOrderDirections[]; // "BUY" or "SELL"
double   pendingOrderEntry[];      // Limit price the order was placed at
double   pendingOrderSL[];
double   pendingOrderTP[];
datetime pendingOrderPlacedAt[];
datetime pendingOrderExpiresAt[];
bool     pendingOrderIsPaper[];    // carry paper flag through so fill notification reflects it

//--- Journal-ID cache: bridges /api/trade → CheckForNewPositions detection.
//    Populated when the EA fetches an approved trade (indexed by backend tradeID);
//    consumed when CheckForNewPositions or limit-fill detection sees a position
//    with matching comment. Entries expire/remove after the position is linked.
string   tradeJournalCache_BackendID[];
string   tradeJournalCache_JournalID[];
double   tradeJournalCache_PlannedEntry[];
double   tradeJournalCache_PlannedSL[];
double   tradeJournalCache_PlannedTP[];

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
         " | Check every ", ExecutionCheckSeconds, "s",
         " | OrderType: ", OrderType,
         (OrderType == "LIMIT" ? " | LimitExpiry: " + IntegerToString(LimitExpiryHours) + "h" : ""));

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

   // Note: startup debug handshake to /api/debug/key-echo was removed once
   // the key-mismatch bug was confirmed fixed. The first4+len print above
   // is enough for ongoing diagnostics; the echo endpoint no longer exists
   // on the backend.

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

   // ── Pending limit order monitor ── (every 60 seconds)
   // Always-on when auto-execution is on, so limit orders placed earlier are
   // still tracked even if the EA is disabled for new fetches.
   if (ArraySize(pendingOrderTickets) > 0 && now - lastPendingCheck >= 60)
   {
      lastPendingCheck = now;
      CheckPendingLimitOrders();
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
   ArrayResize(knownJournalIDs, 0);
   ArrayResize(knownPlannedEntry, 0);
   ArrayResize(knownPlannedSL, 0);
   ArrayResize(knownPlannedTP, 0);

   int total = PositionsTotal();
   for (int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0) continue;
      if (!PositionSelectByTicket(ticket)) continue;

      string sym   = PositionGetString(POSITION_SYMBOL);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double pt    = SymbolInfoDouble(sym, SYMBOL_POINT);

      int size = ArraySize(knownPositionTickets);
      ArrayResize(knownPositionTickets, size + 1);
      ArrayResize(knownSL, size + 1);
      ArrayResize(knownTP, size + 1);
      ArrayResize(beApplied, size + 1);
      ArrayResize(knownJournalIDs, size + 1);
      ArrayResize(knownPlannedEntry, size + 1);
      ArrayResize(knownPlannedSL, size + 1);
      ArrayResize(knownPlannedTP, size + 1);

      knownPositionTickets[size] = ticket;
      knownSL[size]              = sl;
      knownTP[size]              = tp;
      beApplied[size]            = (sl > 0 && MathAbs(sl - entry) < pt);
      // Positions snapshotted on startup weren't registered this session —
      // no journal id available. Backend will fall back to ticket/fuzzy match.
      knownJournalIDs[size]      = "";
      knownPlannedEntry[size]    = entry;
      knownPlannedSL[size]       = sl;
      knownPlannedTP[size]       = tp;
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

      // ── Try to recover journal_trade_id from comment ────────────────
      // Market orders set comment = "POIWatcher_<backendTradeID>" and we
      // stored a backendID → journalID map when the trade was fetched from
      // /api/trade. Limit-order fills register directly via AddKnownPositionWithJournal.
      string comment   = PositionGetString(POSITION_COMMENT);
      string journalID = LookupJournalIDByBackendComment(comment);
      double pEntry    = PositionGetDouble(POSITION_PRICE_OPEN);
      double pSL       = PositionGetDouble(POSITION_SL);
      double pTP       = PositionGetDouble(POSITION_TP);
      // Prefer planned levels from cache (intent) over live levels (which may
      // already reflect post-fill broker-side adjustments).
      double cEntry = LookupPlannedEntryByBackendComment(comment);
      double cSL    = LookupPlannedSLByBackendComment(comment);
      double cTP    = LookupPlannedTPByBackendComment(comment);
      if (cEntry > 0) pEntry = cEntry;
      if (cSL    > 0) pSL    = cSL;
      if (cTP    > 0) pTP    = cTP;
      // Drop the cache entry once linked — keeps the cache small.
      string backendID = ExtractBackendIDFromComment(comment);
      if (StringLen(backendID) > 0 && StringLen(journalID) > 0)
         RemoveTradeJournalCacheEntry(backendID);

      int size = ArraySize(knownPositionTickets);
      ArrayResize(knownPositionTickets, size + 1);
      ArrayResize(knownSL, size + 1);
      ArrayResize(knownTP, size + 1);
      ArrayResize(beApplied, size + 1);
      ArrayResize(knownJournalIDs, size + 1);
      ArrayResize(knownPlannedEntry, size + 1);
      ArrayResize(knownPlannedSL, size + 1);
      ArrayResize(knownPlannedTP, size + 1);

      knownPositionTickets[size] = ticket;
      knownSL[size]              = PositionGetDouble(POSITION_SL);
      knownTP[size]              = PositionGetDouble(POSITION_TP);
      beApplied[size]            = false;
      knownJournalIDs[size]      = journalID;
      knownPlannedEntry[size]    = pEntry;
      knownPlannedSL[size]       = pSL;
      knownPlannedTP[size]       = pTP;

      string sym  = PositionGetString(POSITION_SYMBOL);
      long   pTyp = PositionGetInteger(POSITION_TYPE);
      Print("POIWatcher: New position — #", ticket, " ", sym,
            " ", (pTyp == POSITION_TYPE_BUY ? "Long" : "Short"),
            (StringLen(journalID) > 0 ? " (journal=" + journalID + ")" : " (no journal link)"));

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
//  JOURNAL-LINK CACHE  (bridges /api/trade → CheckForNewPositions)
//====================================================================
//  When the EA fetches an approved trade from /api/trade we cache the
//  journal_trade_id (and planned levels) keyed by the BACKEND tradeID
//  that ends up in the position comment as "POIWatcher_<tradeID>".
//  CheckForNewPositions reads the position comment and looks the cache
//  up to attach the journal id to the open position. Limit-order fills
//  consume the cache the same way through CheckPendingLimitOrders.
//+------------------------------------------------------------------+
void AddTradeJournalCacheEntry(string backendID, string journalID,
                               double entry, double sl, double tp)
{
   if (StringLen(backendID) == 0) return;

   // De-dup: if the same backend id is already cached, refresh in place.
   for (int i = 0; i < ArraySize(tradeJournalCache_BackendID); i++)
   {
      if (tradeJournalCache_BackendID[i] == backendID)
      {
         tradeJournalCache_JournalID[i]     = journalID;
         tradeJournalCache_PlannedEntry[i]  = entry;
         tradeJournalCache_PlannedSL[i]     = sl;
         tradeJournalCache_PlannedTP[i]     = tp;
         return;
      }
   }

   int sz = ArraySize(tradeJournalCache_BackendID);
   ArrayResize(tradeJournalCache_BackendID,    sz + 1);
   ArrayResize(tradeJournalCache_JournalID,    sz + 1);
   ArrayResize(tradeJournalCache_PlannedEntry, sz + 1);
   ArrayResize(tradeJournalCache_PlannedSL,    sz + 1);
   ArrayResize(tradeJournalCache_PlannedTP,    sz + 1);

   tradeJournalCache_BackendID[sz]    = backendID;
   tradeJournalCache_JournalID[sz]    = journalID;
   tradeJournalCache_PlannedEntry[sz] = entry;
   tradeJournalCache_PlannedSL[sz]    = sl;
   tradeJournalCache_PlannedTP[sz]    = tp;
}

void RemoveTradeJournalCacheEntry(string backendID)
{
   if (StringLen(backendID) == 0) return;
   for (int i = 0; i < ArraySize(tradeJournalCache_BackendID); i++)
   {
      if (tradeJournalCache_BackendID[i] != backendID) continue;
      // Shift left.
      for (int j = i; j < ArraySize(tradeJournalCache_BackendID) - 1; j++)
      {
         tradeJournalCache_BackendID[j]    = tradeJournalCache_BackendID[j + 1];
         tradeJournalCache_JournalID[j]    = tradeJournalCache_JournalID[j + 1];
         tradeJournalCache_PlannedEntry[j] = tradeJournalCache_PlannedEntry[j + 1];
         tradeJournalCache_PlannedSL[j]    = tradeJournalCache_PlannedSL[j + 1];
         tradeJournalCache_PlannedTP[j]    = tradeJournalCache_PlannedTP[j + 1];
      }
      int sz = ArraySize(tradeJournalCache_BackendID) - 1;
      ArrayResize(tradeJournalCache_BackendID,    sz);
      ArrayResize(tradeJournalCache_JournalID,    sz);
      ArrayResize(tradeJournalCache_PlannedEntry, sz);
      ArrayResize(tradeJournalCache_PlannedSL,    sz);
      ArrayResize(tradeJournalCache_PlannedTP,    sz);
      return;
   }
}

//--- Pull the backend tradeID out of "POIWatcher_<tradeID>" position comment.
//    Returns "" if the comment doesn't follow the expected format.
string ExtractBackendIDFromComment(string comment)
{
   string prefix = "POIWatcher_";
   int p = StringFind(comment, prefix);
   if (p < 0) return "";
   return StringSubstr(comment, p + StringLen(prefix));
}

string LookupJournalIDByBackendComment(string comment)
{
   string backendID = ExtractBackendIDFromComment(comment);
   if (StringLen(backendID) == 0) return "";
   for (int i = 0; i < ArraySize(tradeJournalCache_BackendID); i++)
      if (tradeJournalCache_BackendID[i] == backendID)
         return tradeJournalCache_JournalID[i];
   return "";
}

double LookupPlannedEntryByBackendComment(string comment)
{
   string backendID = ExtractBackendIDFromComment(comment);
   if (StringLen(backendID) == 0) return 0.0;
   for (int i = 0; i < ArraySize(tradeJournalCache_BackendID); i++)
      if (tradeJournalCache_BackendID[i] == backendID)
         return tradeJournalCache_PlannedEntry[i];
   return 0.0;
}

double LookupPlannedSLByBackendComment(string comment)
{
   string backendID = ExtractBackendIDFromComment(comment);
   if (StringLen(backendID) == 0) return 0.0;
   for (int i = 0; i < ArraySize(tradeJournalCache_BackendID); i++)
      if (tradeJournalCache_BackendID[i] == backendID)
         return tradeJournalCache_PlannedSL[i];
   return 0.0;
}

double LookupPlannedTPByBackendComment(string comment)
{
   string backendID = ExtractBackendIDFromComment(comment);
   if (StringLen(backendID) == 0) return 0.0;
   for (int i = 0; i < ArraySize(tradeJournalCache_BackendID); i++)
      if (tradeJournalCache_BackendID[i] == backendID)
         return tradeJournalCache_PlannedTP[i];
   return 0.0;
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

   string tradeID        = JsonGetString(tj, "id");
   string symbol         = JsonGetString(tj, "symbol");
   string direction      = JsonGetString(tj, "direction");
   double entry          = JsonGetDouble(tj, "entry");
   double sl             = JsonGetDouble(tj, "sl");
   double tp             = JsonGetDouble(tj, "tp");
   double riskPct        = JsonGetDouble(tj, "risk_percent");
   double lotSize        = JsonGetDouble(tj, "lot_size");
   string paperFlag      = JsonGetString(tj, "paper_trading");
   string testFlag       = JsonGetString(tj, "test_only");
   // Backend forwards the original journal entry id (e.g. "trade_001") so that
   // when this trade closes we can match the close event back to the right Gist
   // row. Stored in a small bridge cache keyed by backend tradeID until the
   // resulting position is detected.
   string journalTradeID = JsonGetString(tj, "journal_trade_id");
   bool   isPaper        = (paperFlag == "true" || paperFlag == "True" || paperFlag == "1");
   bool   isTest         = (testFlag  == "true" || testFlag  == "True" || testFlag  == "1");

   if (StringLen(tradeID) == 0 || StringLen(symbol) == 0)
   {
      Print("POIWatcher EXEC: Malformed trade response — missing id or symbol");
      return;
   }

   // Stash the journal id keyed by backend tradeID for later linkage.
   AddTradeJournalCacheEntry(tradeID, journalTradeID, entry, sl, tp);

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
   double normSL    = NormalizeDouble(sl,    digits);
   double normTP    = NormalizeDouble(tp,    digits);
   double normEntry = NormalizeDouble(entry, digits);
   string comment   = "POIWatcher_" + tradeID;

   // Re-apply deviation for this specific trade (in case input was changed)
   trade.SetDeviationInPoints((ulong)MaxSlippagePips * 10);

   bool success = false;

   if (OrderType == "LIMIT")
   {
      //── LIMIT ORDER branch ─────────────────────────────────────
      datetime expiryTime = TimeCurrent() + (datetime)(LimitExpiryHours * 3600);

      if (direction == "BUY")
      {
         Print("POIWatcher EXEC: Placing BUY LIMIT  ", symbol,
               " lot=", DoubleToString(calcLot, 2),
               " @ ", DoubleToString(normEntry, digits),
               " sl=", DoubleToString(normSL, digits),
               " tp=", DoubleToString(normTP, digits),
               " expiry=", TimeToString(expiryTime, TIME_DATE | TIME_MINUTES),
               (isPaper ? " [PAPER]" : ""));
         success = trade.BuyLimit(calcLot, normEntry, symbol, normSL, normTP,
                                  ORDER_TIME_SPECIFIED, expiryTime, comment);
      }
      else if (direction == "SELL")
      {
         Print("POIWatcher EXEC: Placing SELL LIMIT ", symbol,
               " lot=", DoubleToString(calcLot, 2),
               " @ ", DoubleToString(normEntry, digits),
               " sl=", DoubleToString(normSL, digits),
               " tp=", DoubleToString(normTP, digits),
               " expiry=", TimeToString(expiryTime, TIME_DATE | TIME_MINUTES),
               (isPaper ? " [PAPER]" : ""));
         success = trade.SellLimit(calcLot, normEntry, symbol, normSL, normTP,
                                   ORDER_TIME_SPECIFIED, expiryTime, comment);
      }
      else
      {
         Print("POIWatcher EXEC: Invalid direction '", direction, "' — REJECTED");
         SendExecutionResultEx(tradeID, 0, 0,
               "Invalid direction: " + direction, isPaper, false);
         MarkTradeExecuted(tradeID);
         return;
      }

      MarkTradeExecuted(tradeID);

      if (success)
      {
         ulong orderTicket = trade.ResultOrder();
         Print("POIWatcher EXEC: LIMIT ORDER PLACED — order #", orderTicket,
               " ", symbol, " ", direction,
               " @ ", DoubleToString(normEntry, digits),
               " lot=", DoubleToString(calcLot, 2),
               (isPaper ? " [PAPER]" : ""));

         // Register for monitoring
         AddPendingLimitOrder(orderTicket, tradeID, symbol, direction,
                              normEntry, normSL, normTP, expiryTime, isPaper);

         // Notify backend that limit order was placed
         SendLimitOrderPlaced(tradeID, orderTicket, symbol, direction,
                              normEntry, normSL, normTP, expiryTime);
      }
      else
      {
         uint   retcode = trade.ResultRetcode();
         string errMsg  = "Limit order failed: retcode " + IntegerToString(retcode) +
                          " (" + trade.ResultRetcodeDescription() + ")";
         Print("POIWatcher EXEC: FAILED — ", errMsg);
         SendExecutionResultEx(tradeID, 0, 0, errMsg, isPaper, false);
      }
   }
   else
   {
      //── MARKET ORDER branch (existing behaviour) ────────────────
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
//| Pending limit order tracking helpers                            |
//+------------------------------------------------------------------+
void AddPendingLimitOrder(ulong ticket, string tradeID, string sym, string dir,
                           double entry, double pSL, double pTP,
                           datetime expiresAt, bool isPaper)
{
   int sz = ArraySize(pendingOrderTickets);
   ArrayResize(pendingOrderTickets,     sz + 1);
   ArrayResize(pendingOrderTradeIDs,    sz + 1);
   ArrayResize(pendingOrderJournalIDs,  sz + 1);
   ArrayResize(pendingOrderSymbols,     sz + 1);
   ArrayResize(pendingOrderDirections,  sz + 1);
   ArrayResize(pendingOrderEntry,       sz + 1);
   ArrayResize(pendingOrderSL,          sz + 1);
   ArrayResize(pendingOrderTP,          sz + 1);
   ArrayResize(pendingOrderPlacedAt,    sz + 1);
   ArrayResize(pendingOrderExpiresAt,   sz + 1);
   ArrayResize(pendingOrderIsPaper,     sz + 1);

   pendingOrderTickets[sz]     = ticket;
   pendingOrderTradeIDs[sz]    = tradeID;
   // Pull the matching journal id out of the cache so we have it on hand
   // even after the cache entry is consumed by CheckForNewPositions. Useful
   // for the limit-fill backend notification.
   pendingOrderJournalIDs[sz]  = LookupJournalIDByBackendComment("POIWatcher_" + tradeID);
   pendingOrderSymbols[sz]     = sym;
   pendingOrderDirections[sz]  = dir;
   pendingOrderEntry[sz]       = entry;
   pendingOrderSL[sz]          = pSL;
   pendingOrderTP[sz]          = pTP;
   pendingOrderPlacedAt[sz]    = TimeCurrent();
   pendingOrderExpiresAt[sz]   = expiresAt;
   pendingOrderIsPaper[sz]     = isPaper;

   Print("POIWatcher: Pending limit order registered — ticket #", ticket,
         " tradeID=", tradeID,
         " journal=", (StringLen(pendingOrderJournalIDs[sz]) > 0 ? pendingOrderJournalIDs[sz] : "(none)"),
         " ", sym, " ", dir,
         " @ ", DoubleToString(entry, 5),
         " expires=", TimeToString(expiresAt, TIME_DATE | TIME_MINUTES));
}

void RemovePendingOrder(int idx)
{
   int last = ArraySize(pendingOrderTickets) - 1;
   if (idx < last)
   {
      pendingOrderTickets[idx]     = pendingOrderTickets[last];
      pendingOrderTradeIDs[idx]    = pendingOrderTradeIDs[last];
      pendingOrderJournalIDs[idx]  = pendingOrderJournalIDs[last];
      pendingOrderSymbols[idx]     = pendingOrderSymbols[last];
      pendingOrderDirections[idx]  = pendingOrderDirections[last];
      pendingOrderEntry[idx]       = pendingOrderEntry[last];
      pendingOrderSL[idx]          = pendingOrderSL[last];
      pendingOrderTP[idx]          = pendingOrderTP[last];
      pendingOrderPlacedAt[idx]    = pendingOrderPlacedAt[last];
      pendingOrderExpiresAt[idx]   = pendingOrderExpiresAt[last];
      pendingOrderIsPaper[idx]     = pendingOrderIsPaper[last];
   }
   ArrayResize(pendingOrderTickets,     last);
   ArrayResize(pendingOrderTradeIDs,    last);
   ArrayResize(pendingOrderJournalIDs,  last);
   ArrayResize(pendingOrderSymbols,     last);
   ArrayResize(pendingOrderDirections,  last);
   ArrayResize(pendingOrderEntry,       last);
   ArrayResize(pendingOrderSL,          last);
   ArrayResize(pendingOrderTP,          last);
   ArrayResize(pendingOrderPlacedAt,    last);
   ArrayResize(pendingOrderExpiresAt,   last);
   ArrayResize(pendingOrderIsPaper,     last);
}

//+------------------------------------------------------------------+
//| Monitor pending limit orders — runs every 60 seconds            |
//|                                                                  |
//| For each tracked limit order:                                    |
//|   • If a position with the matching comment exists → FILLED      |
//|   • If the pending order is gone and no position found → EXPIRED |
//+------------------------------------------------------------------+
void CheckPendingLimitOrders()
{
   datetime now = TimeCurrent();

   for (int i = ArraySize(pendingOrderTickets) - 1; i >= 0; i--)
   {
      ulong    pTicket  = pendingOrderTickets[i];
      string   tradeID  = pendingOrderTradeIDs[i];
      string   sym      = pendingOrderSymbols[i];
      string   dir      = pendingOrderDirections[i];
      double   limEntry = pendingOrderEntry[i];
      double   limSL    = pendingOrderSL[i];
      double   limTP    = pendingOrderTP[i];
      datetime expAt    = pendingOrderExpiresAt[i];
      bool     paper    = pendingOrderIsPaper[i];

      // ── Step 1: scan open positions for a fill matching our comment ──
      string   matchComment = "POIWatcher_" + tradeID;
      bool     filled       = false;
      ulong    fillTicket   = 0;
      double   fillPrice    = 0;

      int total = PositionsTotal();
      for (int p = total - 1; p >= 0; p--)
      {
         ulong pt = PositionGetTicket(p);
         if (pt == 0) continue;
         if (!PositionSelectByTicket(pt)) continue;
         if (PositionGetString(POSITION_COMMENT) == matchComment)
         {
            filled     = true;
            fillTicket = pt;
            fillPrice  = PositionGetDouble(POSITION_PRICE_OPEN);
            break;
         }
      }

      if (filled)
      {
         int    digits   = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
         double pt2      = SymbolInfoDouble(sym, SYMBOL_POINT);
         double pipDiv   = (digits == 3 || digits == 5) ? 10.0 : 1.0;
         double slipPips = (pt2 > 0 && pipDiv > 0) ? MathAbs(fillPrice - limEntry) / pt2 / pipDiv : 0;

         double posLots = 0;
         if (PositionSelectByTicket(fillTicket))
            posLots = PositionGetDouble(POSITION_VOLUME);

         Print("POIWatcher: Limit FILLED — #", fillTicket,
               " ", sym, " ", dir,
               " planned=", DoubleToString(limEntry, digits),
               " actual=",  DoubleToString(fillPrice, digits),
               " slip=",    DoubleToString(slipPips, 1), " pips",
               (paper ? " [PAPER]" : ""));

         // POST fill to /mt5/trade-open with limit metadata.
         // Pass through the cached journal id so the backend can pre-link this
         // fill to its source journal entry without waiting for the close.
         string fillJournalID = pendingOrderJournalIDs[i];
         SendLimitOrderFilled(tradeID, fillTicket, sym, dir,
                              limEntry, fillPrice, limSL, limTP, posLots, paper,
                              fillJournalID);

         RemovePendingOrder(i);
         continue;
      }

      // ── Step 2: check if the pending order still exists ──
      bool orderStillOpen = false;
      int pending = OrdersTotal();
      for (int o = pending - 1; o >= 0; o--)
      {
         ulong ot = OrderGetTicket(o);
         if (ot == pTicket) { orderStillOpen = true; break; }
      }

      if (!orderStillOpen)
      {
         // Order gone AND no matching position → expired or cancelled
         string reason = (now >= expAt) ? "expired" : "cancelled";
         Print("POIWatcher: Limit order ", reason, " — #", pTicket,
               " ", sym, " ", dir,
               " @ ", DoubleToString(limEntry, 5));

         SendLimitOrderExpiredOrCancelled(tradeID, pTicket, sym, dir,
                                          limEntry, expAt, reason);
         RemovePendingOrder(i);
      }
      // else: still pending — nothing to do this cycle
   }
}

//+------------------------------------------------------------------+
//| Notify backend: limit order placed                              |
//+------------------------------------------------------------------+
void SendLimitOrderPlaced(string tradeID, ulong orderTicket, string sym, string dir,
                           double entry, double pSL, double pTP, datetime expiresAt)
{
   string json = "{";
   json += "\"id\":\""           + tradeID                                                  + "\",";
   json += "\"order_ticket\":"   + IntegerToString((long)orderTicket)                       +  ",";
   json += "\"symbol\":\""       + sym                                                      + "\",";
   json += "\"direction\":\""    + dir                                                      + "\",";
   json += "\"entry\":"          + DoubleToString(entry, 5)                                 +  ",";
   json += "\"sl\":"             + DoubleToString(pSL,   5)                                 +  ",";
   json += "\"tp\":"             + DoubleToString(pTP,   5)                                 +  ",";
   json += "\"expires_at\":\""   + TimeToString(expiresAt, TIME_DATE | TIME_SECONDS)        + "\",";
   json += "\"timestamp\":\""    + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS)    + "\"";
   json += "}";

   HttpPostWithKey("/api/trade/limit-placed", json);
}

//+------------------------------------------------------------------+
//| Notify backend: limit order filled → POST /mt5/trade-open       |
//+------------------------------------------------------------------+
void SendLimitOrderFilled(string tradeID, ulong fillTicket, string sym, string dir,
                           double plannedEntry, double actualEntry,
                           double pSL, double pTP, double lots, bool isPaper,
                           string journalTradeID)
{
   int    digits   = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double pt       = SymbolInfoDouble(sym, SYMBOL_POINT);
   double pipDiv   = (digits == 3 || digits == 5) ? 10.0 : 1.0;
   double slipPips = (pt > 0 && pipDiv > 0) ? MathAbs(actualEntry - plannedEntry) / pt / pipDiv : 0;

   string json = "{";
   json += "\"ticket\":"              + IntegerToString((long)fillTicket)                        +  ",";
   json += "\"symbol\":\""            + sym                                                      + "\",";
   json += "\"direction\":\""         + (dir == "BUY" ? "Long" : "Short")                       + "\",";
   json += "\"entry_price\":"         + DoubleToString(actualEntry,  digits)                     +  ",";
   json += "\"stop_loss\":"           + DoubleToString(pSL,          digits)                     +  ",";
   json += "\"take_profit\":"         + DoubleToString(pTP,          digits)                     +  ",";
   json += "\"lot_size\":"            + DoubleToString(lots, 2)                                  +  ",";
   json += "\"order_type\":\"limit\",";
   json += "\"planned_entry\":"       + DoubleToString(plannedEntry, digits)                     +  ",";
   json += "\"actual_entry\":"        + DoubleToString(actualEntry,  digits)                     +  ",";
   json += "\"slippage\":"            + DoubleToString(slipPips, 1)                              +  ",";
   json += "\"execution_queue_id\":\"" + tradeID                                                 + "\",";
   if (StringLen(journalTradeID) > 0)
      json += "\"journal_trade_id\":\"" + journalTradeID                                         + "\",";
   json += "\"account_balance\":"     + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2)    +  ",";
   json += "\"account_equity\":"      + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),  2)    +  ",";
   json += "\"timestamp\":\""         + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS)    + "\",";
   json += "\"platform\":\"mt5\"";
   json += "}";

   HttpPost("/mt5/trade-open", json);
}

//+------------------------------------------------------------------+
//| Notify backend: limit order expired or cancelled                |
//+------------------------------------------------------------------+
void SendLimitOrderExpiredOrCancelled(string tradeID, ulong orderTicket, string sym,
                                       string dir, double entry, datetime expiresAt,
                                       string reason)
{
   string json = "{";
   json += "\"id\":\""          + tradeID                                               + "\",";
   json += "\"order_ticket\":"  + IntegerToString((long)orderTicket)                    +  ",";
   json += "\"symbol\":\""      + sym                                                   + "\",";
   json += "\"direction\":\""   + dir                                                   + "\",";
   json += "\"entry\":"         + DoubleToString(entry, 5)                              +  ",";
   json += "\"reason\":\"limit_order_" + reason                                         + "\",";
   json += "\"expires_at\":\""  + TimeToString(expiresAt, TIME_DATE | TIME_SECONDS)    + "\",";
   json += "\"timestamp\":\""   + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\"";
   json += "}";

   HttpPostWithKey("/api/trade/cancelled", json);
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
//|                                                                  |
//| Payload includes journal_trade_id (so the backend can match the  |
//| close to its source Gist entry), signed actual_rr, signed pips,  |
//| close_reason derived from DEAL_REASON, and the planned levels    |
//| captured at execution time.                                      |
//+------------------------------------------------------------------+
void SendPositionClose(ulong ticket)
{
   // Pull session metadata BEFORE history is consulted — RemovePosition
   // hasn't run yet so the index is still valid.
   int    posIdx       = GetPositionIndex(ticket);
   string journalID    = (posIdx >= 0) ? knownJournalIDs[posIdx]   : "";
   double plannedEntry = (posIdx >= 0) ? knownPlannedEntry[posIdx] : 0;
   double plannedSL    = (posIdx >= 0) ? knownPlannedSL[posIdx]    : 0;
   double plannedTP    = (posIdx >= 0) ? knownPlannedTP[posIdx]    : 0;

   // Load history for this specific position
   // (ticket == positionId for standard MT5 positions)
   bool histOk = HistorySelectByPosition(ticket);
   if (!histOk)
   {
      // Fallback: search last 7 days of history
      HistorySelect(TimeCurrent() - 7 * 86400, TimeCurrent());
   }

   int      dealsTotal    = HistoryDealsTotal();
   ulong    closeDeal     = 0;
   double   closePrice    = 0;
   double   profit        = 0;
   double   swapVal       = 0;
   double   commission    = 0;
   datetime openTime      = 0;
   datetime closeTime     = 0;
   double   entryPrice    = 0;
   string   symbol        = "";
   long     closeDealType = -1; // DEAL_TYPE of the closing deal
   long     closeReasonId = -1; // DEAL_REASON of the closing deal

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
         closeReasonId = HistoryDealGetInteger(dTicket, DEAL_REASON);
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

   // Derive position direction from the close deal type:
   // A SELL deal closes a BUY position; a BUY deal closes a SELL position.
   string direction = "Long";
   if (closeDealType == DEAL_TYPE_BUY)  direction = "Short"; // BUY deal closed a SELL position
   if (closeDealType == DEAL_TYPE_SELL) direction = "Long";  // SELL deal closed a BUY position
   bool isLong = (direction == "Long");

   // SIGNED pip calculation. Long: close - entry; Short: entry - close.
   // Use the actual fill price as the entry reference (entryPrice from
   // DEAL_ENTRY_IN), not the planned entry — pips reflects what the
   // *position* did, not what the strategy planned.
   double pips = 0;
   if (entryPrice > 0 && pt > 0)
   {
      double rawPipDist = (isLong ? (closePrice - entryPrice)
                                  : (entryPrice - closePrice)) / pt / pipDiv;
      pips = rawPipDist; // already signed
   }

   int durationMin = (openTime > 0 && closeTime > 0)
                     ? (int)((closeTime - openTime) / 60) : 0;

   //── close_reason: derived from DEAL_REASON, with Break-Even override ──
   //
   // DEAL_REASON_SL/TP are unambiguous. CLIENT/MOBILE/WEB/EXPERT are all
   // user-initiated → "Manual Close". If the broker doesn't tag the deal
   // (closeReasonId == -1) or returns an unknown reason, default to manual.
   //
   // Break-Even override: if the close price sits roughly on the planned
   // entry AND the position had its SL pulled to entry (BE applied), we
   // categorise the close as "Break Even" regardless of what DEAL_REASON
   // says. This catches the BE-stop-out case which DEAL_REASON_SL would
   // otherwise classify as "SL Hit".
   string closeReason = "Manual Close";
   if      (closeReasonId == DEAL_REASON_TP) closeReason = "TP Hit";
   else if (closeReasonId == DEAL_REASON_SL) closeReason = "SL Hit";
   else if (closeReasonId == DEAL_REASON_SO) closeReason = "Stop Out";

   if (plannedEntry > 0 && pt > 0)
   {
      double bePipDist  = MathAbs(closePrice - plannedEntry) / pt / pipDiv;
      bool   beApp      = (posIdx >= 0) ? beApplied[posIdx] : false;
      // ≤ 1 pip away from planned entry AND BE was active → Break Even
      if (bePipDist <= 1.0 && beApp)
         closeReason = "Break Even";
   }

   //── Signed Actual R:R ────────────────────────────────────────────────
   //
   //   long:   actual_rr = (close - planned_entry) / |planned_entry - planned_sl|
   //   short:  actual_rr = (planned_entry - close) / |planned_entry - planned_sl|
   //   BE:     actual_rr = 0
   //
   // Falls back to 0 if planned levels are unavailable (e.g. position was
   // snapshotted at startup and never linked to a journal entry).
   double actualRR = 0;
   if (closeReason == "Break Even")
   {
      actualRR = 0;
   }
   else if (plannedEntry > 0 && plannedSL > 0)
   {
      double riskDist = MathAbs(plannedEntry - plannedSL);
      if (riskDist > 0)
      {
         double signedDist = isLong ? (closePrice - plannedEntry)
                                    : (plannedEntry - closePrice);
         actualRR = signedDist / riskDist;
      }
   }

   string json = "{";
   json += "\"ticket\":"            + IntegerToString((long)ticket)            + ",";
   if (StringLen(journalID) > 0)
      json += "\"journal_trade_id\":\"" + journalID                            + "\",";
   json += "\"symbol\":\""          + symbol                                   + "\",";
   json += "\"direction\":\""       + direction                                + "\",";
   json += "\"entry_price\":"       + DoubleToString(entryPrice, digits)       + ",";
   json += "\"exit_price\":"        + DoubleToString(closePrice, digits)       + ",";
   json += "\"profit_loss\":"       + DoubleToString(totalProfit, 2)           + ",";
   json += "\"pips\":"              + DoubleToString(pips, 1)                  + ",";
   json += "\"duration_minutes\":"  + IntegerToString(durationMin)             + ",";
   json += "\"close_reason\":\""    + closeReason                              + "\",";
   json += "\"actual_rr\":"         + DoubleToString(actualRR, 2)              + ",";
   json += "\"planned_entry\":"     + DoubleToString(plannedEntry, digits)     + ",";
   json += "\"planned_sl\":"        + DoubleToString(plannedSL,    digits)     + ",";
   json += "\"planned_tp\":"        + DoubleToString(plannedTP,    digits)     + ",";
   json += "\"deal_reason_id\":"    + IntegerToString((int)closeReasonId)      + ",";
   json += "\"platform\":\"mt5\"";
   json += "}";

   Print("POIWatcher: Closing payload — ticket=", ticket,
         " journal=", (StringLen(journalID) > 0 ? journalID : "(none)"),
         " reason=", closeReason,
         " rr=", DoubleToString(actualRR, 2),
         " pips=", DoubleToString(pips, 1),
         " pl=", DoubleToString(totalProfit, 2));

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
      knownJournalIDs[idx]      = knownJournalIDs[last];
      knownPlannedEntry[idx]    = knownPlannedEntry[last];
      knownPlannedSL[idx]       = knownPlannedSL[last];
      knownPlannedTP[idx]       = knownPlannedTP[last];
   }
   ArrayResize(knownPositionTickets, last);
   ArrayResize(knownSL,              last);
   ArrayResize(knownTP,              last);
   ArrayResize(beApplied,            last);
   ArrayResize(knownJournalIDs,      last);
   ArrayResize(knownPlannedEntry,    last);
   ArrayResize(knownPlannedSL,       last);
   ArrayResize(knownPlannedTP,       last);
}
//+------------------------------------------------------------------+
