# POIWatcher Backend

Python Flask backend for price monitoring, Telegram alerts, AI level suggestions, MT4 trade auto-logging, and Binance exchange integration.
Works with the [Trade Journal app](https://chukwuemeka001.github.io/trading-tools-/trade-log.html).

## Features

- **Price Monitoring** — Checks BTCUSDT/ETHUSDT every 60s via Bitunix → CoinGecko → CoinCap fallback chain
- **Telegram Alerts** — Fires alerts when price crosses your levels
- **AI Level Suggestions** — Claude analyzes candle data using your exact trading system framework
- **MT5 Auto-Logging** — Expert Advisor sends trade open/close/modify events to backend
- **Break Even Automation** — EA + Bitunix monitor auto-move SL to entry at configurable RR
- **Bitunix Futures Integration** — Primary crypto venue: place orders, auto-close logging, 1:5 R:R BE
- **Binance Exchange Integration** — Optional spot account + balance tracking
- **1:5 R:R Break Even Alerts** — Telegram notification + auto-SL when positions reach 1:5 R:R
- **Per-Venue Kill Switches** — Independent emergency stops for MT5 and Bitunix
- **Gist Storage** — Alerts and trades stored in the same Gist as your trade journal

## Setup Guide

### Step 1 — Create Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (looks like `123456:ABC-DEF...`)
4. Start a chat with your new bot (send it any message)
5. Get your **chat ID**:
   - Search for **@userinfobot** on Telegram
   - Send it any message — it replies with your chat ID
   - Or visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` after messaging your bot

### Step 2 — Get Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Copy it — you'll need it for the AI level suggestion feature

### Step 3 — Get Binance API Key (Optional)

1. Log into [binance.com](https://www.binance.com) (global, not .ca)
2. Go to **API Management**
3. Create a new API key
4. Set permissions:
   - Read Info — **YES**
   - Enable Spot Trading — NO (read-only is sufficient)
   - Enable Withdrawals — **NO** (never enable this)
5. Copy the **API Key** and **Secret Key**

> **Note:** If Binance is geo-blocked in your region, the backend will auto-detect this and disable the Binance sync with a warning logged.

### Step 3b — Get Bitunix API Key (Primary Crypto Venue)

Bitunix is the primary crypto futures venue — the backend uses it for live price data,
balance tracking, order execution, automatic break-even at 1:5 R:R, and post-close journal
reconciliation.

1. Log into [bitunix.com](https://www.bitunix.com)
2. Go to **API Management** in your account settings
3. Create a new API key — set a label like `poiwatcher-render`
4. Set permissions:

   | Permission | Setting |
   |------------|---------|
   | Read account / positions / orders | **YES** |
   | Place / cancel orders (futures)   | **YES** (only if you want auto-execution; read-only mode is fine for journal-only) |
   | Withdrawals                       | **NO** (never enable) |

5. **IP Whitelist** — Restrict the key to Render's outbound IPs. Find them in your Render
   service dashboard under **Settings → Outbound IPs** and paste them into Bitunix's
   whitelist field.
6. Copy the **API Key** and **API Secret** — you'll only see the secret once.

> **Auth model:** Bitunix uses a double-SHA256 signing scheme (not HMAC) over
> `nonce + timestamp + apiKey + queryParams + body`. The backend handles this — you only
> need to supply the key and secret as env vars.

### Step 4 — Deploy to Render

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New Web Service**
3. Connect your GitHub repo
4. Add these **environment variables** in Render dashboard:

   | Variable | Value |
   |----------|-------|
   | `TELEGRAM_BOT_TOKEN` | Your bot token from Step 1 |
   | `TELEGRAM_CHAT_ID` | Your chat ID from Step 1 |
   | `GITHUB_GIST_TOKEN` | Your GitHub PAT with `gist` scope |
   | `ANTHROPIC_API_KEY` | Your Anthropic API key from Step 2 |
   | `BINANCE_API_KEY` | Your Binance API key from Step 3 (optional) |
   | `BINANCE_API_SECRET` | Your Binance secret from Step 3 (optional) |
   | `BITUNIX_API_KEY` | Your Bitunix API key from Step 3b |
   | `BITUNIX_API_SECRET` | Your Bitunix secret from Step 3b |
   | `BITUNIX_DEFAULT_LEVERAGE` | `10` (default; override per-trade in API body) |
   | `BITUNIX_MARGIN_MODE` | `CROSS` or `ISOLATION` (default `CROSS`) |
   | `EXECUTION_API_KEY` | Random secret — required for `/api/trade/*` and `/bitunix/trade/*` |
   | `PAPER_TRADING_MODE` | `true` to simulate Bitunix orders without sending them; `false` for live |
   | `GIST_ID` | `bc004e07ada6586fc4492590f80b182b` (already set) |
   | `ALLOWED_ORIGIN` | `https://chukwuemeka001.github.io` (already set) |

5. Deploy — Render will auto-detect the `render.yaml` config

### Step 5 — Connect Journal App

1. Open your Trade Journal: https://chukwuemeka001.github.io/trading-tools-/trade-log.html
2. Go to the **Alerts** tab
3. Enter your Render backend URL (e.g. `https://poiwatcher-backend.onrender.com`)
4. Click **Save** — should show "Connected"
5. Exchange status indicator in the nav bar will show green when connected

### Step 6 — Install MT4 Expert Advisor

1. **Copy the EA file:**
   - Copy `POIWatcher.mq4` to your MT4 installation:
   - `C:\Users\[YOU]\AppData\Roaming\MetaQuotes\Terminal\[ID]\MQL4\Experts\`
   - Or in MT4: File → Open Data Folder → MQL4 → Experts

2. **Compile the EA:**
   - Open MetaEditor (press F4 in MT4)
   - File → Open → select `POIWatcher.mq4`
   - Press F7 (Compile) — should show "0 errors"
   - Close MetaEditor

3. **Allow WebRequest:**
   - In MT4: Tools → Options → Expert Advisors
   - Check "Allow automated trading"
   - Check "Allow WebRequest for listed URL"
   - Click "Add" and enter your backend URL:
     `https://poiwatcher-backend.onrender.com`
   - Click OK

4. **Attach to chart:**
   - In MT4: View → Navigator (Ctrl+N)
   - Expand "Expert Advisors"
   - Drag "POIWatcher" onto any chart
   - In the popup, go to **Inputs** tab:
     - `BackendURL` — your Render URL
     - `EnableAutoBreakEven` — true (recommended)
     - `BreakEvenRR` — 1.5 (move SL to entry at 1:1.5 RR)
     - `EnableAutoLogging` — true
     - `HeartbeatMinutes` — 5
   - Click OK

5. **Verify:**
   - Make sure the "AutoTrading" button in MT4 toolbar is ON (green)
   - You should see a smiley face on the chart
   - Check the Experts tab (Ctrl+E) for "POIWatcher EA initialized"
   - In your journal app, the MT4 indicator should turn green

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/alerts` | Get all alerts from Gist |
| `POST` | `/alerts` | Add new alert |
| `PUT` | `/alerts/:id` | Update/re-arm alert |
| `DELETE` | `/alerts/:id` | Remove alert |
| `GET` | `/price/:symbol` | Get current price |
| `POST` | `/ai-levels` | Get AI level suggestions |
| `POST` | `/mt4/trade-open` | Log new trade from MT4 EA |
| `POST` | `/mt4/trade-close` | Log trade close from MT4 EA |
| `POST` | `/mt4/trade-modify` | Log SL/TP modification |
| `POST` `/GET` | `/mt4/status` | EA heartbeat |
| `GET` | `/mt4/connection` | MT4 connection status |
| `GET` | `/mt4/open-trades` | Currently open MT4 trades |
| `GET` | `/binance/account` | Binance balance and open orders |
| `GET` | `/exchange/status` | Connection status for all exchanges |
| `GET` | `/bitunix/exchange/status` | Bitunix-only connection status |
| `GET` | `/bitunix/account` | Bitunix futures balance + position/order counts |
| `GET` | `/bitunix/ticker/:symbol` | Bitunix public market ticker |
| `GET` | `/bitunix/positions` | Currently open Bitunix positions |
| `GET` | `/bitunix/orders/pending` | Pending Bitunix limit/stop orders |
| `POST` | `/bitunix/trade/execute` | Place a futures order on Bitunix (X-Execution-Key) |
| `POST` | `/bitunix/trade/cancel` | Cancel a Bitunix order by id (X-Execution-Key) |
| `GET/POST/DELETE` | `/api/bitunix/emergency-stop` | Bitunix-only kill switch (X-Execution-Key) |
| `GET/POST/DELETE` | `/api/mt5/emergency-stop` | MT5-only EA pause (X-Execution-Key) |

## Architecture

```
MT5 Terminal ──→ POIWatcher EA ──→ Flask Backend ──→ Telegram Bot
                                       │                    │
Bitunix/CoinGecko/CoinCap ──→ Price ──┤                    └── Your phone
                                       │
Bitunix Private (futures) ─────────────┤  ← primary execution venue
Binance Private (spot, optional) ──────┤
                                       ├── GitHub Gist (trades + alerts)
                                       │
                                       └── Claude API (AI levels)
```

- Price chain: **Bitunix → CoinGecko → CoinCap** (cached 45s, with cooldown on 429s)
- Exchange sync loop runs every 60s — pulls Bitunix balance + positions + close history,
  then Binance balance (if configured)
- Bitunix close monitor matches each closing fill to the journal row using a 3-tier
  strategy: `clientId` → `orderId` → fuzzy (same symbol + same UTC date + entry within
  0.5%). Unmatched fills are still persisted as auto-logged rows tagged
  `reviewNeeded: true`.
- Bitunix position monitor moves SL to entry once price reaches 1:5 R:R and fires a
  Telegram notification
- MT5 EA sends trade events and heartbeats to backend; per-venue kill switches let you
  pause MT5 and Bitunix independently
- All data syncs to GitHub Gist for the journal app
- Telegram notifications for alerts, trade opens, closes, and break even

## Security

- All credentials stored as environment variables — never hardcoded
- API keys and secrets are **never** logged, exported, or included in Gist data
- API keys are **never** included in Claude AI exports or Telegram messages
- CORS restricted to GitHub Pages domain only
- MT5 EA communicates via HTTPS — no API keys needed for trade logging
- Broker API keys stay in browser cookies only — never sent to backend
- Gist token needs only `gist` scope
- Binance requests signed with HMAC-SHA256 per Binance documentation
- Bitunix requests signed with double-SHA256 per Bitunix documentation; rate-limited to
  10 req/sec at the client level
- Bitunix API key should be IP-whitelisted to Render's outbound IPs and set to
  read-only or read+trade — **never** with withdrawal permission
- If a Bitunix or Binance call returns an auth error, that venue's sync is disabled
  automatically (no repeated bad requests until restart)
- Per-venue kill switches: `/api/mt5/emergency-stop` and `/api/bitunix/emergency-stop`
  are independent — flipping one does not affect the other
