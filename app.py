"""
Trading Alert Backend — Flask server for price monitoring, Telegram alerts,
and AI level suggestions using Emeka's BTCUSDT Trading System framework.

Deployed on Render free tier. All secrets via environment variables.
"""

import os
import json
import time
import uuid
import hashlib
import hmac
import base64
import threading
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

# ── Config ──────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://chukwuemeka001.github.io")
CORS(app, origins=[ALLOWED_ORIGIN])

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GITHUB_GIST_TOKEN = os.environ.get("GITHUB_GIST_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GIST_ID = os.environ.get("GIST_ID", "bc004e07ada6586fc4492590f80b182b")
GIST_FILE = "trade-journal.json"

# ── Exchange API credentials ──
KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.environ.get("KRAKEN_API_SECRET", "")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# ── Symbol mapping for multi-source APIs ──
SYMBOL_MAP = {
    "BTCUSDT": {"coingecko": "bitcoin", "kraken": "XBTUSD", "coincap": "bitcoin"},
    "ETHUSDT": {"coingecko": "ethereum", "kraken": "ETHUSD", "coincap": "ethereum"},
}

POLL_INTERVAL = 60   # seconds — reduced from 30 to avoid rate limits
RETRY_INTERVAL = 60  # seconds on API failure
CACHE_TTL = 45       # seconds — serve cached price if fresher than this

# ── Trading system document (embedded for AI prompt) ───
TRADING_SYSTEM = r"""
BTCUSDT Trading System — Personal Framework & Rules
Version 2.0

1. System Overview
Market: BTCUSDT (Bitcoin / Tether USD)
Style: Pure price action — zero indicators
Approach: Top-down multi-timeframe analysis
Timeframes: Monthly > Weekly > Daily > 4H > 1H > 30min > 15min > 5min > 3min
Core edge: Structure + Liquidity + Sponsored Candle confirmation

2. Core Concepts & Definitions

2.1 Break of Structure (BOS)
When price breaks a significant previous high (bullish BOS) or significant previous low (bearish BOS).
- A BOS is created by price breaking a significant structural high or low
- The BOS level becomes a permanent key reference point for future price action
- After a BOS, the FIRST low (bullish BOS) or FIRST high (bearish BOS) that forms = LIQUIDITY ($$)
- BOS on higher timeframes carry significantly more weight than lower TF BOS
- Not every structural break qualifies — must be a SIGNIFICANT high or low, not minor noise

2.2 Major Break of Structure (MBOS)
A BOS built on a foundation of fully validated and confirmed structural lows/highs. Carries significantly more weight than a regular BOS.
- An MBOS occurs when the structure beneath/above it has already been fully tested and validated
- The previous structure's liquidity must have been taken before the MBOS forms
- MBOS levels are the most important reference points on any chart — treat them with the highest weight

2.3 Liquidity ($$)
Areas where price fakes out market participants before making the real move. Predictable based on structure.
- PRIMARY RULE: After EVERY BOS, the FIRST low/high that forms = liquidity ($$)
- Two types of liquidity relative to each BOS:
  - Secondary liquidity — first low/high directly after the BOS
  - Primary liquidity — low/high just below/above the mbms area (deeper level)
- The market hunts liquidity BEFORE making the real move — this is deliberate, not random

2.4 Minor Break in Market Structure (mbms) — Primary Point of Interest
The first minor structural break that signals a larger, more significant BOS is coming.
- The mbms is the market's FIRST signal that a bigger move is being prepared
- The mbms area IS the Primary POI — the deepest pullback target in any move
- ANYTHING below/above the mbms is considered the PRIMARY area — primary liquidity lives here
- When price does NOT have enough distance and momentum after a BOS -> expect it to return to the mbms/Primary POI

2.5 The Two POI Hierarchy
Every BOS creates two zones of interest. The KEY FILTER between them is distance and momentum.
- Secondary POI: First low/high directly after BOS. Used when BOS had STRONG distance and momentum.
- Primary POI (mbms area): Below/above the mbms level. Used when BOS had WEAK distance and momentum. Highest conviction.
- STRONG distance + STRONG momentum after BOS -> Secondary POI is sufficient
- WEAK distance + WEAK momentum after BOS -> Primary POI will likely be tested

2.6 Structural Lows and Highs
- TYPE 1 — Fully mitigated structural low: Price came all the way to Primary POI, took the liquidity, then broke a high. FULLY CONFIRMED.
- TYPE 2 — Secondary POI structural low: Price reacted from secondary POI with distance/momentum, then broke a high.
- TRUSTED HIGH/LOW: When pri POI has been properly mitigated AND price made a new high/low
- TRUSTED BOS: A BOS that forms after the pri POI has been properly mitigated — highest conviction BOS

2.7 Sponsored Candle (SC)
The last prominent candle(s) before a significant move begins in either direction.
- BULLISH SC: Last prominent bearish candle(s) before a significant bullish move
- BEARISH SC: Last prominent bullish candle(s) before a significant bearish move
- Typically appears at the mbms area / Primary POI
- The SC is marked as a GREY ZONE on the chart — not a single candle but a zone of interest

3. Top-Down Analysis Process
Always start from the highest TF and work down. Never start from a low TF.
- Monthly: MBOS levels, major $$ liquidity, overall trend direction, SC zones
- Weekly: BOS levels, mbms areas, secondary and primary liquidity zones, SC zones
- Daily: Refine POI areas, confirm mbms, identify SC zones, determine if sec or pri POI likely
- 4H: Confirm structure, find liquidity not visible on daily, identify SC zone boundaries
- 1H/30min: Fine-tune entry zones, confirm mbms, watch for SC candle forming
- 15min/5min: Confirm mbms on entry TF, identify SC candle, wait for HH+HL or LL+LH confirmation
- 3min: Fine-tune exact entry, confirm SC reaction, watch for trusted BOS on this TF

4. Entry Rules
Bullish: HTF bullish bias -> identify $$ -> apply distance/momentum filter -> wait for liquidity sweep -> drop to LTF for SC -> wait for mbms -> wait for HH+HL -> enter long
Bearish: HTF bearish bias -> identify $$ -> apply distance/momentum filter -> wait for liquidity sweep -> drop to LTF for SC -> wait for mbms -> wait for LL+LH -> enter short

5. Core Principles
- The question is always: IF it buys — where? IF it sells — where?
- Wait for price action after every significant BOS before committing
- Distance and momentum are the filter between secondary and primary POI
- Liquidity is predictable — the market hunts stops before making the real move
- The mbms is always the first warning — when you see it, prepare for the bigger BOS
- If price leaves without confirmation — let it go. Next setup always comes

Glossary:
BOS = Break of Structure | MBOS = Major Break of Structure | $$ = Liquidity
mbms = Minor Break in Market Structure | Primary POI = mbms area (deepest pullback target)
Secondary POI = First liquidity zone directly after BOS | SC = Sponsored Candle (grey zone)
Trusted BOS = BOS after primary POI properly mitigated | HTF = Higher timeframe | LTF = Lower timeframe
"""

# ── Gist helpers ────────────────────────────────────────

def _gist_headers():
    return {
        "Authorization": f"token {GITHUB_GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def gist_read():
    """Read the full Gist data (trade journal + alerts)."""
    try:
        r = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=_gist_headers(), timeout=15)
        r.raise_for_status()
        content = r.json()["files"][GIST_FILE]["content"]
        return json.loads(content)
    except Exception as e:
        logging.error("Gist read failed: %s", e)
        return None


def gist_write(data):
    """Write updated data back to Gist."""
    try:
        payload = {"files": {GIST_FILE: {"content": json.dumps(data, indent=2)}}}
        r = requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=_gist_headers(), json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error("Gist write failed: %s", e)
        return False


def get_alerts():
    """Get alerts array from Gist."""
    data = gist_read()
    if data is None:
        return []
    return data.get("alerts", [])


def save_alerts(alerts):
    """Save alerts array back to Gist, preserving other keys."""
    data = gist_read()
    if data is None:
        data = {}
    data["alerts"] = alerts
    return gist_write(data)


# ── Price helpers (multi-source with cache + rate limit tracking) ──

# Cache: { symbol: { "price": float, "time": float } }
_price_cache = {}
# Per-source cooldown: { source_name: earliest_retry_time }
_source_cooldown = {}

def _get_symbol_ids(symbol):
    """Get API-specific IDs for a symbol."""
    return SYMBOL_MAP.get(symbol.upper(), {
        "coingecko": symbol.lower().replace("usdt", ""),
        "kraken": symbol.upper().replace("USDT", "USD"),
        "coincap": symbol.lower().replace("usdt", ""),
    })


def _is_cooled_down(source_name):
    """Check if a source is still in rate-limit cooldown."""
    until = _source_cooldown.get(source_name, 0)
    if time.time() < until:
        return False
    return True


def _set_cooldown(source_name, seconds=60):
    """Put a source on cooldown after a 429."""
    _source_cooldown[source_name] = time.time() + seconds
    logging.warning("%s rate limited — cooling down for %ds", source_name, seconds)


def _price_kraken(symbol):
    """PRIMARY — Kraken (free, no rate limits on public tier)."""
    ids = _get_symbol_ids(symbol)
    pair = ids["kraken"]
    r = requests.get("https://api.kraken.com/0/public/Ticker",
                      params={"pair": pair}, timeout=10)
    if r.status_code == 429:
        _set_cooldown("Kraken")
        r.raise_for_status()
    r.raise_for_status()
    data = r.json()
    if data.get("error") and len(data["error"]):
        raise ValueError(data["error"][0])
    result = data["result"]
    key = list(result.keys())[0]
    return float(result[key]["c"][0])


def _price_coincap(symbol):
    """BACKUP — CoinCap (free, no geo restrictions)."""
    ids = _get_symbol_ids(symbol)
    r = requests.get(f"https://api.coincap.io/v2/assets/{ids['coincap']}", timeout=10)
    if r.status_code == 429:
        _set_cooldown("CoinCap")
        r.raise_for_status()
    r.raise_for_status()
    return float(r.json()["data"]["priceUsd"])


def _price_coingecko(symbol):
    """SECOND BACKUP — CoinGecko (strict rate limits on free tier)."""
    ids = _get_symbol_ids(symbol)
    r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                      params={"ids": ids["coingecko"], "vs_currencies": "usd"}, timeout=10)
    if r.status_code == 429:
        _set_cooldown("CoinGecko")
        r.raise_for_status()
    r.raise_for_status()
    data = r.json()
    return float(data[ids["coingecko"]]["usd"])


def get_price(symbol="BTCUSDT"):
    """Get price: check cache first, then Kraken → CoinCap → CoinGecko with cooldowns."""
    now = time.time()

    # 1. Return cached price if still fresh
    cached = _price_cache.get(symbol)
    if cached and (now - cached["time"]) < CACHE_TTL:
        return cached["price"]

    # 2. Try sources in order, skipping any on cooldown
    sources = [
        ("Kraken", _price_kraken),
        ("CoinCap", _price_coincap),
        ("CoinGecko", _price_coingecko),
    ]
    last_err = None
    for name, fn in sources:
        if not _is_cooled_down(name):
            logging.debug("Skipping %s — on cooldown", name)
            continue
        try:
            price = fn(symbol)
            logging.info("Price from %s: %s = $%.2f", name, symbol, price)
            _price_cache[symbol] = {"price": price, "time": now}
            return price
        except Exception as e:
            logging.warning("Price fetch from %s failed: %s", name, e)
            last_err = e

    # 3. All sources failed — return stale cache if available
    if cached:
        age = int(now - cached["time"])
        logging.warning("All sources failed — using cached price (%ds old)", age)
        return cached["price"]

    raise RuntimeError(f"All price sources failed for {symbol}: {last_err}")


def get_klines(symbol="BTCUSDT", interval="1d", limit=200):
    """Get OHLCV candle data. Tries Kraken first, falls back to CoinGecko."""
    if _is_cooled_down("Kraken"):
        try:
            return _klines_kraken(symbol, interval, limit)
        except Exception as e:
            logging.warning("Kraken klines failed: %s — trying CoinGecko", e)
    if _is_cooled_down("CoinGecko"):
        try:
            return _klines_coingecko(symbol, interval, limit)
        except Exception as e:
            logging.warning("CoinGecko klines failed: %s", e)
    raise RuntimeError(f"All kline sources failed for {symbol}")


def _klines_coingecko(symbol, interval, limit):
    """Fetch OHLCV from CoinGecko (free, no auth)."""
    ids = _get_symbol_ids(symbol)
    # Map interval to CoinGecko days parameter
    interval_days = {
        "3m": 1, "5m": 1, "15m": 1, "30m": 2, "1h": 4,
        "4h": 14, "1d": limit, "1w": limit * 7, "1M": limit * 30,
    }
    days = min(interval_days.get(interval, limit), 365)
    r = requests.get(f"https://api.coingecko.com/api/v3/coins/{ids['coingecko']}/ohlc",
                      params={"vs_currency": "usd", "days": days}, timeout=15)
    r.raise_for_status()
    candles = []
    for k in r.json():
        candles.append({
            "time": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).isoformat(),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": 0,  # CoinGecko OHLC doesn't include volume
        })
    return candles[-limit:]  # trim to requested limit


def _klines_kraken(symbol, interval, limit):
    """Fetch OHLCV from Kraken (free, no geo restrictions)."""
    ids = _get_symbol_ids(symbol)
    # Map interval to Kraken minutes
    interval_map = {
        "1m": 1, "3m": 5, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440, "1w": 10080, "1M": 21600,
    }
    kraken_interval = interval_map.get(interval, 1440)
    r = requests.get("https://api.kraken.com/0/public/OHLC",
                      params={"pair": ids["kraken"], "interval": kraken_interval}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("error") and len(data["error"]):
        raise ValueError(data["error"][0])
    result = data["result"]
    key = [k for k in result.keys() if k != "last"][0]
    candles = []
    for k in result[key]:
        candles.append({
            "time": datetime.fromtimestamp(float(k[0]), tz=timezone.utc).isoformat(),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[6]),
        })
    return candles[-limit:]


# ── Telegram helper ─────────────────────────────────────

JOURNAL_URL = "https://chukwuemeka001.github.io/trading-tools-/trade-log.html"

def send_telegram(text):
    """Send message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram not configured — skipping alert")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error("Telegram send failed: %s", e)
        return False


def format_alert_message(alert, current_price):
    """Format the Telegram alert message using exact trading system lingo."""
    symbol = alert["symbol"]
    price = alert["price"]
    label = alert["label"]
    direction = alert.get("direction", "crosses_below")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if direction == "crosses_below":
        crossed_text = "Above \u2192 Below"
    else:
        crossed_text = "Below \u2192 Above"

    msg = (
        f"\U0001f6a8 <b>PRICE ALERT \u2014 {symbol}</b>\n\n"
        f"\U0001f4cd Level: <b>${price:,.2f}</b>\n"
        f"\U0001f3f7 Zone: <b>{label}</b>\n"
        f"\U0001f4ca Crossed: {crossed_text}\n"
        f"\u23f0 Time: {now}\n"
        f"\U0001f4b0 Current price: ${current_price:,.2f}\n\n"
        f"\U0001f3af <b>Per your system:</b>\n"
        f"   \u2022 Check LTF for SC candle confirmation\n"
        f"   \u2022 Look for mbms on entry TF\n"
        f"   \u2022 Wait for HH+HL or LL+LH before entry\n\n"
        f"\U0001f4f1 <a href=\"{JOURNAL_URL}\">Open your journal</a>"
    )
    return msg


# ── Price monitor (background thread) ──────────────────

last_prices = {}  # symbol -> last known price

def check_alerts():
    """Check all active alerts against current prices."""
    alerts = get_alerts()
    if not alerts:
        return

    # Group alerts by symbol
    symbols = set(a["symbol"] for a in alerts if a.get("active") and not a.get("triggered"))
    if not symbols:
        return

    changed = False
    for symbol in symbols:
        try:
            price = get_price(symbol)
        except Exception as e:
            logging.error("Price fetch failed for %s: %s", symbol, e)
            continue

        prev = last_prices.get(symbol)
        last_prices[symbol] = price

        if prev is None:
            continue  # Need two readings to detect a cross

        for alert in alerts:
            if alert["symbol"] != symbol or not alert.get("active") or alert.get("triggered"):
                continue

            level = alert["price"]
            direction = alert.get("direction", "crosses_below")

            fired = False
            if direction == "crosses_below" and prev >= level and price < level:
                fired = True
            elif direction == "crosses_above" and prev <= level and price > level:
                fired = True

            if fired:
                logging.info("ALERT FIRED: %s %s at %s (price=%s)", symbol, alert["label"], level, price)
                msg = format_alert_message(alert, price)
                send_telegram(msg)
                alert["triggered"] = True
                alert["triggered_at"] = datetime.now(timezone.utc).isoformat()
                changed = True

    if changed:
        save_alerts(alerts)


def price_monitor_loop():
    """Background loop that checks alerts every POLL_INTERVAL seconds."""
    logging.info("Price monitor started (interval=%ds)", POLL_INTERVAL)
    while True:
        try:
            check_alerts()
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            logging.error("Monitor error: %s — retrying in %ds", e, RETRY_INTERVAL)
            time.sleep(RETRY_INTERVAL)


# ── Flask routes ────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


@app.route("/alerts", methods=["GET"])
def list_alerts():
    alerts = get_alerts()
    return jsonify(alerts)


@app.route("/alerts", methods=["POST"])
def create_alert():
    body = request.json
    if not body or not body.get("symbol") or not body.get("price"):
        return jsonify({"error": "symbol and price required"}), 400

    alert = {
        "id": str(uuid.uuid4())[:8],
        "symbol": body["symbol"].upper(),
        "price": float(body["price"]),
        "label": body.get("label", "Custom"),
        "direction": body.get("direction", "crosses_below"),
        "active": True,
        "triggered": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "triggered_at": None,
    }

    alerts = get_alerts()
    alerts.append(alert)
    if save_alerts(alerts):
        return jsonify(alert), 201
    return jsonify({"error": "Failed to save to Gist"}), 500


@app.route("/alerts/<alert_id>", methods=["PUT"])
def update_alert(alert_id):
    body = request.json or {}
    alerts = get_alerts()
    found = None
    for a in alerts:
        if a["id"] == alert_id:
            found = a
            break
    if not found:
        return jsonify({"error": "Alert not found"}), 404

    # Re-arm: reset triggered state
    if body.get("rearm"):
        found["triggered"] = False
        found["triggered_at"] = None
        found["active"] = True

    # Toggle active
    if "active" in body:
        found["active"] = body["active"]

    # Update fields
    for key in ("symbol", "price", "label", "direction"):
        if key in body:
            found[key] = body[key]
    if "price" in body:
        found["price"] = float(found["price"])

    if save_alerts(alerts):
        return jsonify(found)
    return jsonify({"error": "Failed to save to Gist"}), 500


@app.route("/alerts/<alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    alerts = get_alerts()
    new_alerts = [a for a in alerts if a["id"] != alert_id]
    if len(new_alerts) == len(alerts):
        return jsonify({"error": "Alert not found"}), 404
    if save_alerts(new_alerts):
        return jsonify({"ok": True})
    return jsonify({"error": "Failed to save to Gist"}), 500


@app.route("/price/<symbol>", methods=["GET"])
def price_endpoint(symbol):
    try:
        p = get_price(symbol.upper())
        return jsonify({"symbol": symbol.upper(), "price": p})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/ai-levels", methods=["POST"])
def ai_levels():
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "Anthropic API key not configured"}), 500

    body = request.json or {}
    symbol = body.get("symbol", "BTCUSDT").upper()
    timeframe = body.get("timeframe", "1d")
    limit = min(int(body.get("candle_limit", 200)), 500)

    # Map UI timeframe labels to Binance intervals
    tf_map = {
        "1M": "1M", "1W": "1w", "1D": "1d", "1d": "1d",
        "4H": "4h", "4h": "4h", "1H": "1h", "1h": "1h",
        "30min": "30m", "30m": "30m", "15min": "15m", "15m": "15m",
        "5min": "5m", "5m": "5m", "3min": "3m", "3m": "3m",
    }
    interval = tf_map.get(timeframe, "1d")

    # 1. Fetch candles from Binance
    try:
        candles = get_klines(symbol, interval, limit)
    except Exception as e:
        return jsonify({"error": f"Failed to fetch candles: {e}"}), 502

    # 2. Format OHLCV for Claude
    ohlcv_text = f"Symbol: {symbol} | Timeframe: {timeframe} | Candles: {len(candles)}\n\n"
    ohlcv_text += "Time | Open | High | Low | Close | Volume\n"
    ohlcv_text += "-" * 70 + "\n"
    for c in candles:
        ohlcv_text += f"{c['time']} | {c['open']:.2f} | {c['high']:.2f} | {c['low']:.2f} | {c['close']:.2f} | {c['volume']:.0f}\n"

    # 3. Send to Claude
    system_prompt = f"""You are analyzing price action for a trader who uses the following framework:

{TRADING_SYSTEM}

Analyze the provided OHLCV candle data and identify key levels using ONLY the concepts from this framework:

- BOS levels (significant highs/lows that were broken)
- MBOS levels (major breaks built on validated structure)
- $$ liquidity zones (first low/high after each BOS)
- mbms areas (minor structure breaks telegraphing bigger BOS)
- Primary POI zones (below/above mbms)
- SC zones (last prominent candle before significant moves)

For each level identified return:
- Level type (BOS / MBOS / $$ Secondary / $$ Primary / mbms / Primary POI / SC Zone)
- Price level (exact number)
- Significance (High / Medium / Low)
- Brief reasoning in the trader's own lingo

Return ONLY a JSON array. No prose. No explanation outside the JSON. Format:
[
  {{
    "type": "BOS",
    "price": 70000,
    "significance": "High",
    "reasoning": "Major structural break after higher high at 125k, first significant low formed here becomes $$ secondary"
  }}
]

Use the trader's exact terminology throughout.
Maximum 8-10 levels per analysis.
Focus on the most significant levels only.
Do not identify noise — only what matters."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Analyze this OHLCV data and identify key levels:\n\n{ohlcv_text}"}],
        )

        response_text = message.content[0].text.strip()

        # Parse JSON from response (handle markdown code blocks)
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])

        levels = json.loads(response_text)
        return jsonify({"levels": levels, "symbol": symbol, "timeframe": timeframe})

    except json.JSONDecodeError as e:
        logging.error("AI response parse error: %s\nRaw: %s", e, response_text[:500])
        return jsonify({"error": "AI response was not valid JSON", "raw": response_text[:500]}), 502
    except Exception as e:
        logging.error("AI analysis failed: %s", e)
        return jsonify({"error": f"AI analysis failed: {e}"}), 502


# ── MT4 Integration ─────────────────────────────────────

# In-memory MT4 connection state
_mt4_status = {
    "connected": False,
    "last_heartbeat": None,
    "open_trades": 0,
    "account_balance": 0,
    "account_equity": 0,
}


def get_trades():
    """Get trades array from Gist."""
    data = gist_read()
    if data is None:
        return []
    # trades may be stored as top-level array or under "trades" key
    if isinstance(data, list):
        return data
    return data.get("trades", data.get("data", []))


def save_trades(trades_list):
    """Save trades array back to Gist, preserving other keys."""
    data = gist_read()
    if data is None:
        data = {}
    if isinstance(data, list):
        # Legacy format — migrate to dict
        data = {"trades": data}
    # Determine which key trades are stored under
    if "data" in data and isinstance(data["data"], list):
        data["data"] = trades_list
    else:
        data["trades"] = trades_list
    return gist_write(data)


def mt4_trade_to_journal(body):
    """Convert MT4 trade-open payload to journal trade format."""
    now = datetime.now(timezone.utc).isoformat()
    entry = float(body.get("entry_price", 0))
    sl = float(body.get("stop_loss", 0))
    tp = float(body.get("take_profit", 0))
    sl_dist = abs(entry - sl) if sl else 0
    tp_dist = abs(tp - entry) if tp else 0
    planned_rr = (tp_dist / sl_dist) if sl_dist > 0 else 0

    return {
        "id": "mt4_" + str(body.get("ticket", "")),
        "market": "BTC/USDT" if "BTC" in body.get("symbol", "").upper() else "Forex",
        "pair": body.get("symbol", ""),
        "direction": body.get("direction", "Long").lower(),
        "timeframe": "",
        "setup": "",
        "dateOpen": body.get("timestamp", now),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "size": str(body.get("lot_size", "")),
        "risk": 0,
        "plannedRR": round(planned_rr, 2),
        "confidence": 0,
        "conditions": [],
        "rationale": "",
        "preChart": "",
        # System analysis fields — to be filled by user
        "htfBias": "", "poiType": "", "bosTF": "", "liqTaken": "",
        "mbmsConfirmed": "", "scVisible": "", "entryConfirmation": "",
        "distMomentum": "", "poiLevel": "",
        # Status
        "status": "open",
        "dateClose": None, "exitPrice": None, "actualPnL": None,
        "outcome": None, "actualRR": None,
        "review": "", "postChart": "", "rating": 0,
        # Post-trade review
        "scRespected": None, "mbmsPlayedOut": None, "htfAligned": None,
        "liqProperlyTaken": None, "expectedVsActual": "",
        "whatDifferently": "", "lessonLearned": "", "executionRating": 0,
        # MT4 metadata
        "source": "mt4",
        "mt4Ticket": body.get("ticket"),
        "mt4Balance": body.get("account_balance"),
        "mt4Equity": body.get("account_equity"),
        # Meta
        "createdAt": now,
        "updatedAt": now,
    }


@app.route("/mt4/trade-open", methods=["POST"])
def mt4_trade_open():
    body = request.json
    if not body or not body.get("ticket"):
        return jsonify({"error": "ticket required"}), 400

    trade = mt4_trade_to_journal(body)
    trades_list = get_trades()
    # Check if trade already exists
    existing = [t for t in trades_list if t.get("id") == trade["id"]]
    if existing:
        return jsonify({"ok": True, "message": "Trade already logged"}), 200

    trades_list.append(trade)
    save_trades(trades_list)

    # Telegram notification
    direction = body.get("direction", "Long")
    symbol = body.get("symbol", "")
    entry = body.get("entry_price", 0)
    sl = body.get("stop_loss", 0)
    tp = body.get("take_profit", 0)
    lot = body.get("lot_size", 0)

    msg = (
        f"\U0001f4ca <b>Trade opened on MT4!</b>\n\n"
        f"<b>{symbol}</b> — {direction}\n"
        f"\U0001f4cd Entry: <b>${entry}</b>\n"
        f"\U0001f6d1 SL: ${sl} | \U0001f3af TP: ${tp}\n"
        f"\U0001f4e6 Lot size: {lot}\n\n"
        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open your journal to add your analysis!</a>"
    )
    send_telegram(msg)

    logging.info("MT4 trade opened: #%s %s %s @ %s", body.get("ticket"), symbol, direction, entry)
    return jsonify({"ok": True, "trade_id": trade["id"]}), 201


@app.route("/mt4/trade-close", methods=["POST"])
def mt4_trade_close():
    body = request.json
    if not body or not body.get("ticket"):
        return jsonify({"error": "ticket required"}), 400

    trade_id = "mt4_" + str(body["ticket"])
    trades_list = get_trades()
    found = None
    for t in trades_list:
        if t.get("id") == trade_id:
            found = t
            break

    if not found:
        return jsonify({"error": "Trade not found in journal"}), 404

    # Update trade
    exit_price = float(body.get("exit_price", 0))
    pnl = float(body.get("profit_loss", 0))
    entry = found.get("entry", 0)
    sl = found.get("sl", 0)
    sl_dist = abs(entry - sl) if sl else 0
    exit_dist = abs(exit_price - entry)
    actual_rr = (exit_dist / sl_dist) if sl_dist > 0 else 0

    found["status"] = "closed"
    found["exitPrice"] = exit_price
    found["actualPnL"] = pnl
    found["dateClose"] = body.get("timestamp", datetime.now(timezone.utc).isoformat())
    found["actualRR"] = round(actual_rr, 2)

    # Determine outcome
    if pnl > 0:
        found["outcome"] = "win"
    elif pnl < 0:
        found["outcome"] = "loss"
    else:
        found["outcome"] = "be"

    found["updatedAt"] = datetime.now(timezone.utc).isoformat()
    found["mt4CloseReason"] = body.get("close_reason", "Manual close")
    found["mt4Pips"] = body.get("pips", 0)
    found["mt4Duration"] = body.get("duration_minutes", 0)

    save_trades(trades_list)

    # Telegram notification
    symbol = body.get("symbol", found.get("pair", ""))
    direction = body.get("direction", found.get("direction", ""))
    outcome_emoji = "\u2705" if pnl > 0 else ("\U0001f534" if pnl < 0 else "\u2796")
    outcome_text = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAK EVEN")
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"

    msg = (
        f"{outcome_emoji} <b>Trade closed — {outcome_text}</b>\n\n"
        f"<b>{symbol}</b> — {direction}\n"
        f"\U0001f4cd Entry: ${entry} \u2192 Exit: ${exit_price}\n"
        f"\U0001f4b0 P&L: <b>{pnl_str}</b>\n"
        f"\U0001f4ca Actual RR: 1:{actual_rr:.1f}\n"
        f"\u23f1 Duration: {body.get('duration_minutes', 0)} min\n"
        f"\U0001f4a1 Reason: {body.get('close_reason', 'Manual')}\n\n"
        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal to add post-trade review!</a>"
    )
    send_telegram(msg)

    logging.info("MT4 trade closed: #%s %s P&L=%s", body.get("ticket"), symbol, pnl_str)
    return jsonify({"ok": True})


@app.route("/mt4/trade-modify", methods=["POST"])
def mt4_trade_modify():
    body = request.json
    if not body or not body.get("ticket"):
        return jsonify({"error": "ticket required"}), 400

    trade_id = "mt4_" + str(body["ticket"])
    trades_list = get_trades()
    found = None
    for t in trades_list:
        if t.get("id") == trade_id:
            found = t
            break

    if not found:
        return jsonify({"error": "Trade not found in journal"}), 404

    modification = body.get("modification", "")
    if body.get("new_sl") is not None:
        found["sl"] = float(body["new_sl"])
    if body.get("new_tp") is not None:
        found["tp"] = float(body["new_tp"])
    found["updatedAt"] = datetime.now(timezone.utc).isoformat()

    # Recalculate planned RR if TP changed
    entry = found.get("entry", 0)
    sl = found.get("sl", 0)
    tp = found.get("tp", 0)
    sl_dist = abs(entry - sl) if sl else 0
    tp_dist = abs(tp - entry) if tp else 0
    if sl_dist > 0:
        found["plannedRR"] = round(tp_dist / sl_dist, 2)

    save_trades(trades_list)

    # Telegram for BE
    symbol = body.get("symbol", found.get("pair", ""))
    if "BE" in modification.upper() or "BREAK" in modification.upper():
        potential = abs(tp - entry) * float(found.get("size", 0) or 1)
        msg = (
            f"\U0001f512 <b>Break even set on {symbol}!</b>\n\n"
            f"Trade is now risk free!\n"
            f"\U0001f3af Target still: ${tp}\n"
            f"\U0001f4b0 Potential profit: ${potential:.2f}\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">View in journal</a>"
        )
        send_telegram(msg)

    logging.info("MT4 trade modified: #%s %s — %s", body.get("ticket"), symbol, modification)
    return jsonify({"ok": True})


@app.route("/mt4/status", methods=["POST", "GET"])
def mt4_status():
    if request.method == "POST":
        body = request.json or {}
        _mt4_status["connected"] = True
        _mt4_status["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        _mt4_status["open_trades"] = body.get("open_trades", 0)
        _mt4_status["account_balance"] = body.get("account_balance", 0)
        _mt4_status["account_equity"] = body.get("account_equity", 0)

        # Save connection status to Gist
        data = gist_read()
        if data and isinstance(data, dict):
            data["mt4_status"] = _mt4_status
            gist_write(data)

        return jsonify({"ok": True})

    # GET — return status
    return jsonify(_mt4_status)


@app.route("/mt4/connection", methods=["GET"])
def mt4_connection():
    """Return MT4 connection status with staleness check."""
    status = dict(_mt4_status)
    if status["last_heartbeat"]:
        last = datetime.fromisoformat(status["last_heartbeat"])
        age = (datetime.now(timezone.utc) - last).total_seconds()
        status["connected"] = age < 600  # 10 min timeout
        status["seconds_ago"] = int(age)
    else:
        status["connected"] = False
        status["seconds_ago"] = None
    return jsonify(status)


@app.route("/mt4/open-trades", methods=["GET"])
def mt4_open_trades():
    """Return all currently open MT4 trades from Gist."""
    trades_list = get_trades()
    open_trades = [t for t in trades_list if t.get("status") == "open" and t.get("source") == "mt4"]
    return jsonify(open_trades)


# ═══════════════════════════════════════════════════════
# EXCHANGE INTEGRATION — Kraken & Binance Private APIs
# ═══════════════════════════════════════════════════════

# In-memory state for exchange sync
_exchange_status = {
    "kraken": {"connected": False, "last_sync": None, "error": None, "disabled": False,
               "balance_usdt": 0, "balance_btc": 0, "open_positions": 0},
    "binance": {"connected": False, "last_sync": None, "error": None, "disabled": False,
                "balance_usdt": 0, "balance_btc": 0, "open_positions": 0},
}
# Track already-logged trade IDs to avoid duplicates (loaded from Gist)
_logged_trade_ids = set()
# Track positions already alerted for 1:5 R:R (reset on restart)
_be_alerted_positions = set()


# ── Kraken Private API Signing ──────────────────────────

def _kraken_sign(urlpath, data):
    """Sign a Kraken private API request using HMAC-SHA512."""
    postdata = urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(KRAKEN_API_SECRET), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _kraken_private(endpoint, extra_data=None):
    """Make a signed Kraken private API call."""
    if not KRAKEN_API_KEY or not KRAKEN_API_SECRET:
        raise ValueError("Kraken API credentials not configured")
    urlpath = f"/0/private/{endpoint}"
    data = {"nonce": str(int(time.time() * 1000))}
    if extra_data:
        data.update(extra_data)
    headers = {
        "API-Key": KRAKEN_API_KEY,
        "API-Sign": _kraken_sign(urlpath, data),
    }
    r = requests.post(f"https://api.kraken.com{urlpath}",
                      headers=headers, data=data, timeout=15)
    r.raise_for_status()
    resp = r.json()
    if resp.get("error") and len(resp["error"]):
        raise ValueError(resp["error"][0])
    return resp["result"]


# ── Binance Private API Signing ─────────────────────────

def _binance_sign(params):
    """Sign a Binance API request using HMAC-SHA256."""
    query = urlencode(params)
    signature = hmac.new(BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + signature


def _binance_private(endpoint, params=None, method="GET"):
    """Make a signed Binance API call."""
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise ValueError("Binance API credentials not configured")
    if params is None:
        params = {}
    params["timestamp"] = str(int(time.time() * 1000))
    signed_qs = _binance_sign(params)
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    url = f"https://api.binance.com{endpoint}?{signed_qs}"
    r = requests.request(method, url, headers=headers, timeout=15)
    if r.status_code == 451 or r.status_code == 403:
        raise ConnectionError("Binance geo-blocked or forbidden")
    r.raise_for_status()
    return r.json()


# ── Kraken Account ──────────────────────────────────────

def kraken_get_balance():
    """Fetch Kraken account balance."""
    result = _kraken_private("Balance")
    usdt = float(result.get("USDT", result.get("ZUSD", 0)))
    btc = float(result.get("XXBT", result.get("XBT", 0)))
    return {"usdt": usdt, "btc": btc}


def kraken_get_open_orders():
    """Fetch open orders from Kraken."""
    result = _kraken_private("OpenOrders")
    return result.get("open", {})


def kraken_get_trade_history(start=None):
    """Fetch closed trades from Kraken."""
    extra = {}
    if start:
        extra["start"] = str(start)
    result = _kraken_private("TradesHistory", extra)
    return result.get("trades", {})


def kraken_get_open_positions():
    """Fetch open positions from Kraken."""
    try:
        result = _kraken_private("OpenPositions")
        return result
    except ValueError as e:
        if "permission" in str(e).lower():
            return {}
        raise


# ── Binance Account ─────────────────────────────────────

def binance_get_balance():
    """Fetch Binance account balance."""
    result = _binance_private("/api/v3/account")
    balances = {b["asset"]: float(b["free"]) + float(b["locked"]) for b in result["balances"]
                if float(b["free"]) + float(b["locked"]) > 0}
    return {"usdt": balances.get("USDT", 0), "btc": balances.get("BTC", 0)}


def binance_get_trade_history(symbol="BTCUSDT", limit=50):
    """Fetch recent trades from Binance."""
    return _binance_private("/api/v3/myTrades", {"symbol": symbol, "limit": str(limit)})


def binance_get_open_orders(symbol="BTCUSDT"):
    """Fetch open orders from Binance."""
    return _binance_private("/api/v3/openOrders", {"symbol": symbol})


# ── Symbol Normalization ────────────────────────────────

def _normalize_kraken_symbol(pair):
    """Convert Kraken pair name to standard format (e.g., XXBTZUSD → BTCUSDT)."""
    pair = pair.upper()
    pair = pair.replace("XXBT", "BTC").replace("XBT", "BTC")
    pair = pair.replace("ZUSD", "USDT").replace("USD", "USDT")
    # Avoid double USDT
    if pair.endswith("USDTUSDT"):
        pair = pair.replace("USDTUSDT", "USDT")
    if pair.endswith("USDTT"):
        pair = pair[:-1]
    return pair


# ── Exchange Trade to Journal Entry ─────────────────────

def exchange_trade_to_journal(trade_data, source="kraken"):
    """Convert an exchange trade to journal format."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"{source}_{trade_data['trade_id']}",
        "market": "BTC/USDT",
        "pair": trade_data.get("symbol", "BTCUSDT"),
        "direction": trade_data.get("direction", "long").lower(),
        "timeframe": "",
        "setup": "",
        "dateOpen": trade_data.get("open_time", now),
        "dateClose": trade_data.get("close_time", now),
        "entry": trade_data.get("entry_price", 0),
        "exitPrice": trade_data.get("exit_price", 0),
        "sl": 0, "tp": 0,
        "size": str(trade_data.get("volume", "")),
        "risk": 0,
        "plannedRR": 0,
        "actualPnL": trade_data.get("pnl", 0),
        "actualRR": 0,
        "confidence": 0,
        "conditions": [],
        "rationale": "",
        "preChart": "",
        # System analysis fields — to be filled by user
        "htfBias": "", "poiType": "", "bosTF": "", "liqTaken": "",
        "mbmsConfirmed": "", "scVisible": "", "entryConfirmation": "",
        "distMomentum": "", "poiLevel": "",
        # Status
        "status": "closed",
        "outcome": "win" if trade_data.get("pnl", 0) > 0 else ("loss" if trade_data.get("pnl", 0) < 0 else "be"),
        "review": "", "postChart": "", "rating": 0,
        # Post-trade review
        "scRespected": None, "mbmsPlayedOut": None, "htfAligned": None,
        "liqProperlyTaken": None, "expectedVsActual": "",
        "whatDifferently": "", "lessonLearned": "", "executionRating": 0,
        # Exchange metadata
        "source": source,
        "exchangeTradeId": trade_data.get("trade_id"),
        # Meta
        "createdAt": now,
        "updatedAt": now,
    }


# ── Process Kraken Trade History ────────────────────────

def _process_kraken_trades():
    """Check Kraken for new closed trades and log them."""
    if _exchange_status["kraken"]["disabled"]:
        return

    try:
        trades = kraken_get_trade_history()
    except ValueError as e:
        if "invalid" in str(e).lower() or "permission" in str(e).lower():
            _exchange_status["kraken"]["disabled"] = True
            _exchange_status["kraken"]["error"] = f"Auth error: {e}"
            logging.error("Kraken auth error — disabling sync: %s", e)
            return
        raise

    new_count = 0
    for tid, t in trades.items():
        if tid in _logged_trade_ids:
            continue

        # Parse Kraken trade data
        symbol = _normalize_kraken_symbol(t.get("pair", ""))
        direction = "long" if t.get("type") == "buy" else "short"
        price = float(t.get("price", 0))
        cost = float(t.get("cost", 0))
        fee = float(t.get("fee", 0))
        vol = float(t.get("vol", 0))
        open_time = datetime.fromtimestamp(float(t.get("time", 0)), tz=timezone.utc).isoformat()

        # For spot trades, P&L needs to be calculated differently
        # We'll use cost - fee as a rough estimate; actual P&L comes from position close
        pnl = float(t.get("net", 0)) if "net" in t else -(fee)

        trade_data = {
            "trade_id": tid,
            "symbol": symbol,
            "direction": direction,
            "entry_price": price,
            "exit_price": price,
            "volume": vol,
            "pnl": pnl,
            "open_time": open_time,
            "close_time": open_time,
        }

        journal_entry = exchange_trade_to_journal(trade_data, source="kraken")
        trades_list = get_trades()
        # Double-check no duplicate
        if any(tr.get("id") == journal_entry["id"] for tr in trades_list):
            _logged_trade_ids.add(tid)
            continue

        trades_list.append(journal_entry)
        save_trades(trades_list)
        _logged_trade_ids.add(tid)
        new_count += 1

        # Telegram notification
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        msg = (
            f"\U0001f4ca <b>New Kraken trade logged!</b>\n\n"
            f"<b>{symbol}</b> — {direction.upper()}\n"
            f"\U0001f4cd Entry: <b>${price:.2f}</b>\n"
            f"\U0001f4b0 P&L: <b>{pnl_str}</b>\n"
            f"\U0001f4e6 Volume: {vol}\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal to add your analysis!</a>"
        )
        send_telegram(msg)
        logging.info("Kraken trade auto-logged: %s %s %s @ $%.2f", tid, symbol, direction, price)

    if new_count > 0:
        logging.info("Auto-logged %d new Kraken trade(s)", new_count)


# ── Process Binance Trade History ───────────────────────

def _process_binance_trades():
    """Check Binance for new closed trades and log them."""
    if _exchange_status["binance"]["disabled"]:
        return

    try:
        trades = binance_get_trade_history("BTCUSDT", 50)
    except ConnectionError:
        _exchange_status["binance"]["error"] = "Geo-blocked — falling back to Kraken only"
        _exchange_status["binance"]["disabled"] = True
        logging.warning("Binance geo-blocked — disabling Binance sync")
        return
    except Exception as e:
        if "invalid" in str(e).lower() or "unauthorized" in str(e).lower():
            _exchange_status["binance"]["disabled"] = True
            _exchange_status["binance"]["error"] = f"Auth error: {e}"
            logging.error("Binance auth error — disabling sync: %s", e)
            return
        raise

    new_count = 0
    for t in trades:
        tid = str(t.get("id", ""))
        if f"binance_{tid}" in _logged_trade_ids:
            continue

        direction = "long" if t.get("isBuyer") else "short"
        price = float(t.get("price", 0))
        qty = float(t.get("qty", 0))
        quote_qty = float(t.get("quoteQty", 0))
        commission = float(t.get("commission", 0))
        trade_time = datetime.fromtimestamp(t.get("time", 0) / 1000, tz=timezone.utc).isoformat()

        trade_data = {
            "trade_id": tid,
            "symbol": "BTCUSDT",
            "direction": direction,
            "entry_price": price,
            "exit_price": price,
            "volume": qty,
            "pnl": -commission,
            "open_time": trade_time,
            "close_time": trade_time,
        }

        journal_entry = exchange_trade_to_journal(trade_data, source="binance")
        trades_list = get_trades()
        if any(tr.get("id") == journal_entry["id"] for tr in trades_list):
            _logged_trade_ids.add(f"binance_{tid}")
            continue

        trades_list.append(journal_entry)
        save_trades(trades_list)
        _logged_trade_ids.add(f"binance_{tid}")
        new_count += 1

        pnl_str = f"+${-commission:.2f}" if commission <= 0 else f"-${commission:.2f}"
        msg = (
            f"\U0001f4ca <b>New Binance trade logged!</b>\n\n"
            f"<b>BTCUSDT</b> — {direction.upper()}\n"
            f"\U0001f4cd Entry: <b>${price:.2f}</b>\n"
            f"\U0001f4e6 Qty: {qty} BTC (~${quote_qty:.2f})\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal to add your analysis!</a>"
        )
        send_telegram(msg)
        logging.info("Binance trade auto-logged: %s BTCUSDT %s @ $%.2f", tid, direction, price)

    if new_count > 0:
        logging.info("Auto-logged %d new Binance trade(s)", new_count)


# ── Open Position Monitoring (1:5 R:R alerts) ──────────

def _monitor_positions():
    """Check open positions for 1:5 R:R break-even alert."""
    # Kraken positions
    if KRAKEN_API_KEY and not _exchange_status["kraken"]["disabled"]:
        try:
            positions = kraken_get_open_positions()
            _exchange_status["kraken"]["open_positions"] = len(positions)
            for pid, pos in positions.items():
                if pid in _be_alerted_positions:
                    continue
                # Check against journal entry for SL/TP
                trades_list = get_trades()
                entry_price = float(pos.get("cost", 0)) / max(float(pos.get("vol", 1)), 0.0001)
                current_pnl = float(pos.get("net", 0))
                direction = "long" if pos.get("type") == "buy" else "short"
                symbol = _normalize_kraken_symbol(pos.get("pair", ""))

                # Find matching journal entry with SL
                matching = [t for t in trades_list if t.get("source") == "kraken"
                           and t.get("status") == "open" and t.get("sl")]
                sl_dist = 0
                for m in matching:
                    sl_dist = abs(m.get("entry", 0) - m.get("sl", 0))
                    break

                if sl_dist <= 0:
                    continue

                # Get current price for R:R calc
                try:
                    current_price = get_price("BTCUSDT")
                except Exception:
                    continue

                if direction == "long":
                    current_rr = (current_price - entry_price) / sl_dist if sl_dist > 0 else 0
                else:
                    current_rr = (entry_price - current_price) / sl_dist if sl_dist > 0 else 0

                if current_rr >= 5:
                    _be_alerted_positions.add(pid)
                    msg = (
                        f"\U0001f512 <b>KRAKEN POSITION AT 1:5 R:R!</b>\n\n"
                        f"<b>{symbol}</b> — {direction.upper()}\n"
                        f"Consider moving stop to break even!\n"
                        f"\U0001f4b0 Current profit: <b>${current_pnl:.2f}</b>\n"
                        f"\U0001f4ca R:R: 1:{current_rr:.1f}\n\n"
                        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">View in journal</a>"
                    )
                    send_telegram(msg)
                    logging.info("1:5 R:R alert sent for Kraken position %s", pid)

        except Exception as e:
            logging.warning("Kraken position monitor error: %s", e)

    # Binance open orders (spot doesn't have margin positions by default)
    if BINANCE_API_KEY and not _exchange_status["binance"]["disabled"]:
        try:
            orders = binance_get_open_orders("BTCUSDT")
            _exchange_status["binance"]["open_positions"] = len(orders)
        except Exception as e:
            logging.warning("Binance position monitor error: %s", e)


# ── Exchange Sync Loop ──────────────────────────────────

def _load_logged_trade_ids():
    """Load already-logged exchange trade IDs from Gist to avoid duplicates."""
    try:
        trades_list = get_trades()
        for t in trades_list:
            src = t.get("source", "")
            eid = t.get("exchangeTradeId") or t.get("id", "")
            if src in ("kraken", "binance"):
                _logged_trade_ids.add(eid)
                if src == "kraken":
                    _logged_trade_ids.add(eid)
                else:
                    _logged_trade_ids.add(f"binance_{eid}")
        logging.info("Loaded %d already-logged exchange trade IDs", len(_logged_trade_ids))
    except Exception as e:
        logging.warning("Failed to load logged trade IDs: %s", e)


def exchange_sync_loop():
    """Background loop: sync exchange trades and monitor positions every 60s."""
    _load_logged_trade_ids()
    while True:
        time.sleep(60)
        try:
            # Kraken sync
            if KRAKEN_API_KEY and not _exchange_status["kraken"]["disabled"]:
                try:
                    bal = kraken_get_balance()
                    _exchange_status["kraken"]["connected"] = True
                    _exchange_status["kraken"]["balance_usdt"] = bal["usdt"]
                    _exchange_status["kraken"]["balance_btc"] = bal["btc"]
                    _exchange_status["kraken"]["last_sync"] = datetime.now(timezone.utc).isoformat()
                    _exchange_status["kraken"]["error"] = None
                    _process_kraken_trades()
                except ValueError as e:
                    if "invalid" in str(e).lower() or "permission" in str(e).lower():
                        _exchange_status["kraken"]["disabled"] = True
                        _exchange_status["kraken"]["connected"] = False
                        _exchange_status["kraken"]["error"] = str(e)
                        logging.error("Kraken disabled due to auth error: %s", e)
                    else:
                        _exchange_status["kraken"]["error"] = str(e)
                        logging.warning("Kraken sync error: %s", e)
                except Exception as e:
                    _exchange_status["kraken"]["error"] = str(e)
                    logging.warning("Kraken sync error: %s", e)

            # Binance sync
            if BINANCE_API_KEY and not _exchange_status["binance"]["disabled"]:
                try:
                    bal = binance_get_balance()
                    _exchange_status["binance"]["connected"] = True
                    _exchange_status["binance"]["balance_usdt"] = bal["usdt"]
                    _exchange_status["binance"]["balance_btc"] = bal["btc"]
                    _exchange_status["binance"]["last_sync"] = datetime.now(timezone.utc).isoformat()
                    _exchange_status["binance"]["error"] = None
                    _process_binance_trades()
                except ConnectionError:
                    _exchange_status["binance"]["disabled"] = True
                    _exchange_status["binance"]["connected"] = False
                    _exchange_status["binance"]["error"] = "Geo-blocked"
                    logging.warning("Binance geo-blocked — disabled")
                except Exception as e:
                    if "unauthorized" in str(e).lower():
                        _exchange_status["binance"]["disabled"] = True
                        _exchange_status["binance"]["connected"] = False
                    _exchange_status["binance"]["error"] = str(e)
                    logging.warning("Binance sync error: %s", e)

            # Monitor open positions for 1:5 R:R
            _monitor_positions()

        except Exception as e:
            logging.error("Exchange sync loop error: %s", e)


# ── Exchange API Routes ─────────────────────────────────

@app.route("/kraken/account", methods=["GET"])
def kraken_account():
    """GET /kraken/account — account balance, open positions, recent trades."""
    if not KRAKEN_API_KEY:
        return jsonify({"error": "Kraken API not configured"}), 400
    if _exchange_status["kraken"]["disabled"]:
        return jsonify({"error": _exchange_status["kraken"]["error"], "disabled": True}), 403

    try:
        balance = kraken_get_balance()
        open_orders = kraken_get_open_orders()
        trades = kraken_get_trade_history()

        # Format recent trades (last 50)
        recent = []
        for tid, t in list(trades.items())[:50]:
            recent.append({
                "id": tid,
                "symbol": _normalize_kraken_symbol(t.get("pair", "")),
                "direction": "Long" if t.get("type") == "buy" else "Short",
                "price": float(t.get("price", 0)),
                "volume": float(t.get("vol", 0)),
                "cost": float(t.get("cost", 0)),
                "fee": float(t.get("fee", 0)),
                "time": datetime.fromtimestamp(float(t.get("time", 0)), tz=timezone.utc).isoformat(),
            })

        return jsonify({
            "connected": True,
            "balance_usdt": balance["usdt"],
            "balance_btc": balance["btc"],
            "open_orders": len(open_orders),
            "recent_trades": recent,
            "last_sync": datetime.now(timezone.utc).isoformat(),
        })
    except ValueError as e:
        if "invalid" in str(e).lower() or "permission" in str(e).lower():
            _exchange_status["kraken"]["disabled"] = True
            _exchange_status["kraken"]["error"] = str(e)
        return jsonify({"error": str(e)}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kraken/positions", methods=["GET"])
def kraken_positions():
    """GET /kraken/positions — open positions with current P&L and R:R."""
    if not KRAKEN_API_KEY:
        return jsonify({"error": "Kraken API not configured"}), 400
    if _exchange_status["kraken"]["disabled"]:
        return jsonify({"error": _exchange_status["kraken"]["error"], "disabled": True}), 403

    try:
        positions = kraken_get_open_positions()
        current_price = get_price("BTCUSDT")
        result = []

        for pid, pos in positions.items():
            vol = max(float(pos.get("vol", 0)), 0.0001)
            entry_price = float(pos.get("cost", 0)) / vol
            direction = "Long" if pos.get("type") == "buy" else "Short"
            symbol = _normalize_kraken_symbol(pos.get("pair", ""))
            current_pnl = float(pos.get("net", 0))
            open_time = datetime.fromtimestamp(float(pos.get("time", 0)), tz=timezone.utc).isoformat()

            # Calculate R:R from journal entry if SL/TP set
            trades_list = get_trades()
            sl = 0
            tp = 0
            current_rr = 0
            for t in trades_list:
                if t.get("source") == "kraken" and t.get("status") == "open":
                    sl = t.get("sl", 0)
                    tp = t.get("tp", 0)
                    break

            sl_dist = abs(entry_price - sl) if sl else 0
            if sl_dist > 0:
                if direction == "Long":
                    current_rr = (current_price - entry_price) / sl_dist
                else:
                    current_rr = (entry_price - current_price) / sl_dist

            elapsed = time.time() - float(pos.get("time", time.time()))
            result.append({
                "id": pid,
                "symbol": symbol,
                "direction": direction,
                "entry_price": round(entry_price, 2),
                "current_price": round(current_price, 2),
                "current_pnl": round(current_pnl, 2),
                "current_rr": round(max(current_rr, 0), 2),
                "volume": float(pos.get("vol", 0)),
                "open_time": open_time,
                "time_open_minutes": int(elapsed / 60),
                "sl": sl, "tp": tp,
            })

        return jsonify({"positions": result, "count": len(result)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/exchange/status", methods=["GET"])
def exchange_status():
    """GET /exchange/status — connection status for all exchanges."""
    return jsonify(_exchange_status)


@app.route("/binance/account", methods=["GET"])
def binance_account():
    """GET /binance/account — account balance and open orders."""
    if not BINANCE_API_KEY:
        return jsonify({"error": "Binance API not configured"}), 400
    if _exchange_status["binance"]["disabled"]:
        return jsonify({"error": _exchange_status["binance"]["error"], "disabled": True}), 403

    try:
        balance = binance_get_balance()
        open_orders = binance_get_open_orders("BTCUSDT")

        return jsonify({
            "connected": True,
            "balance_usdt": balance["usdt"],
            "balance_btc": balance["btc"],
            "open_orders": len(open_orders),
            "last_sync": datetime.now(timezone.utc).isoformat(),
        })
    except ConnectionError:
        _exchange_status["binance"]["disabled"] = True
        return jsonify({"error": "Binance geo-blocked"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Start ───────────────────────────────────────────────

def _start_background_threads():
    """Start all background threads."""
    threading.Thread(target=price_monitor_loop, daemon=True).start()
    if KRAKEN_API_KEY or BINANCE_API_KEY:
        threading.Thread(target=exchange_sync_loop, daemon=True).start()
        logging.info("Exchange sync started — Kraken: %s, Binance: %s",
                     "enabled" if KRAKEN_API_KEY else "disabled",
                     "enabled" if BINANCE_API_KEY else "disabled")


if __name__ == "__main__":
    _start_background_threads()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
else:
    # When run via gunicorn, also start background threads
    _start_background_threads()
