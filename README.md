# Trading Alert Backend

Python Flask backend for price monitoring, Telegram alerts, and AI level suggestions.
Works with the [Trade Journal app](https://chukwuemeka001.github.io/trading-tools-/trade-log.html).

## Features

- **Price Monitoring** — Checks BTCUSDT price every 30s via Binance public API
- **Telegram Alerts** — Fires alerts when price crosses your levels
- **AI Level Suggestions** — Claude analyzes candle data using your exact trading system framework
- **Gist Storage** — Alerts stored in the same Gist as your trade journal

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

1. Push this `alert-backend` folder to a **new GitHub repository**
   ```bash
   cd alert-backend
   git init
   git add -A
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/trading-alert-backend.git
   git push -u origin main
   ```

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
2. Go to the **Price Alerts** tab
3. Click the **gear icon** and enter your Render backend URL (e.g. `https://trading-alert-backend.onrender.com`)
4. Test by adding a price alert
5. Test the AI Second Opinion button

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

## Security

- All credentials stored as environment variables — never hardcoded
- CORS restricted to GitHub Pages domain only
- Broker API keys are **never** sent to this backend — they stay in browser cookies only
- Gist token needs only `gist` scope

## Architecture

```
Binance API ──→ Flask Backend ──→ Telegram Bot
                    │                    │
                    ├── Gist (alerts)    └── Your phone
                    │
                    └── Claude API (AI levels)
```

The backend runs a background thread that polls Binance every 30 seconds. When price crosses an alert level, it fires a Telegram message and marks the alert as triggered in the Gist.
