# POIWatcher Backend

Python Flask backend for price monitoring, Telegram alerts, AI level suggestions, and MT4 trade auto-logging.
Works with the [Trade Journal app](https://chukwuemeka001.github.io/trading-tools-/trade-log.html).

## Features

- **Price Monitoring** — Checks BTCUSDT price every 60s via Kraken/CoinCap/CoinGecko
- **Telegram Alerts** — Fires alerts when price crosses your levels
- **AI Level Suggestions** — Claude analyzes candle data using your exact trading system framework
- **MT4 Auto-Logging** — Expert Advisor sends trade open/close/modify events to backend
- **Break Even Automation** — EA auto-moves SL to entry at configurable RR
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

### Step 3 — Deploy to Render

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
   | `GIST_ID` | `bc004e07ada6586fc4492590f80b182b` (already set) |
   | `ALLOWED_ORIGIN` | `https://chukwuemeka001.github.io` (already set) |

5. Deploy — Render will auto-detect the `render.yaml` config

### Step 4 — Connect Journal App

1. Open your Trade Journal: https://chukwuemeka001.github.io/trading-tools-/trade-log.html
2. Go to the **Alerts** tab
3. Enter your Render backend URL (e.g. `https://poiwatcher-backend.onrender.com`)
4. Click **Save** — should show "Connected"
5. Test by adding a price alert
6. Test the AI Second Opinion button

### Step 5 — Install MT4 Expert Advisor

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
   - Check ✓ "Allow automated trading"
   - Check ✓ "Allow WebRequest for listed URL"
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

## Architecture

```
MT4 Terminal ──→ POIWatcher EA ──→ Flask Backend ──→ Telegram Bot
                                       │                    │
Kraken/CoinCap ──→ Price Monitor ──────┤                    └── Your phone
                                       │
                                       ├── GitHub Gist (trades + alerts)
                                       │
                                       └── Claude API (AI levels)
```

- Backend polls Kraken every 60 seconds for price alerts
- MT4 EA sends trade events and heartbeats to backend
- All data syncs to GitHub Gist for the journal app
- Telegram notifications for alerts, trade opens, closes, and break even

## Security

- All credentials stored as environment variables — never hardcoded
- CORS restricted to GitHub Pages domain only
- MT4 EA communicates via HTTPS — no API keys needed for trade logging
- Broker API keys stay in browser cookies only — never sent to backend
- Gist token needs only `gist` scope
