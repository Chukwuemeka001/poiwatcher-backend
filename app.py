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
from datetime import datetime, timezone, timedelta
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
EXECUTION_API_KEY = os.environ.get("EXECUTION_API_KEY", "")
PAPER_TRADING_MODE = os.environ.get("PAPER_TRADING_MODE", "true").lower() != "false"
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


# ── MT4/MT5 Integration ─────────────────────────────────
# Backend accepts both /mt4/... and /mt5/... paths as aliases so legacy MQL4
# EAs and the current MQL5 EA (POIWatcher.mq5) can both poll the same handlers.

# In-memory MT4/MT5 connection state
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
    """Convert MT4/MT5 trade-open payload to journal trade format.

    The payload shape is identical for both MQL4 and MQL5 EAs. The ``source``
    field on the resulting journal row records whichever platform sent it so
    the frontend can badge the trade correctly.
    """
    now = datetime.now(timezone.utc).isoformat()
    entry = float(body.get("entry_price", 0))
    sl = float(body.get("stop_loss", 0))
    tp = float(body.get("take_profit", 0))
    sl_dist = abs(entry - sl) if sl else 0
    tp_dist = abs(tp - entry) if tp else 0
    planned_rr = (tp_dist / sl_dist) if sl_dist > 0 else 0

    # EA sends an optional "platform" field ("mt4" or "mt5"). Default to "mt5"
    # since the active EA is POIWatcher.mq5; fall back to "mt4" only if the EA
    # explicitly identifies as MQL4.
    platform = (body.get("platform") or "mt5").lower()
    if platform not in ("mt4", "mt5"):
        platform = "mt5"

    return {
        # Ticket id prefix stays "mt4_" for backward-compat with historical
        # rows already in the Gist — source field distinguishes the platform.
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
        # MT4/MT5 metadata. Field names stay "mt4Xxx" for backward compat with
        # the frontend — the "source" and "platform" fields drive badge rendering.
        "source": platform,
        "platform": platform,
        "mt4Ticket": body.get("ticket"),
        "mt4Balance": body.get("account_balance"),
        "mt4Equity": body.get("account_equity"),
        # Meta
        "createdAt": now,
        "updatedAt": now,
    }


@app.route("/mt4/trade-open", methods=["POST"])
@app.route("/mt5/trade-open", methods=["POST"])
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

    platform_label = trade.get("platform", "mt5").upper()
    msg = (
        f"\U0001f4ca <b>Trade opened on {platform_label}!</b>\n\n"
        f"<b>{symbol}</b> — {direction}\n"
        f"\U0001f4cd Entry: <b>${entry}</b>\n"
        f"\U0001f6d1 SL: ${sl} | \U0001f3af TP: ${tp}\n"
        f"\U0001f4e6 Lot size: {lot}\n\n"
        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open your journal to add your analysis!</a>"
    )
    send_telegram(msg)

    logging.info("%s trade opened: #%s %s %s @ %s", platform_label, body.get("ticket"), symbol, direction, entry)
    return jsonify({"ok": True, "trade_id": trade["id"]}), 201


@app.route("/mt4/trade-close", methods=["POST"])
@app.route("/mt5/trade-close", methods=["POST"])
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

    platform_label = (found.get("platform") or found.get("source") or "mt5").upper()
    logging.info("%s trade closed: #%s %s P&L=%s", platform_label, body.get("ticket"), symbol, pnl_str)
    return jsonify({"ok": True})


@app.route("/mt4/trade-modify", methods=["POST"])
@app.route("/mt5/trade-modify", methods=["POST"])
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

    platform_label = (found.get("platform") or found.get("source") or "mt5").upper()
    logging.info("%s trade modified: #%s %s — %s", platform_label, body.get("ticket"), symbol, modification)
    return jsonify({"ok": True})


@app.route("/mt4/status", methods=["POST", "GET"])
@app.route("/mt5/status", methods=["POST", "GET"])
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
@app.route("/mt5/connection", methods=["GET"])
def mt4_connection():
    """Return MT4/MT5 EA connection status with staleness check."""
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
@app.route("/mt5/open-trades", methods=["GET"])
def mt4_open_trades():
    """Return all currently open MT4/MT5 trades from Gist.

    Accepts both legacy ``source == "mt4"`` rows and new ``"mt5"`` rows so the
    live panel never goes blank after the platform migration.
    """
    trades_list = get_trades()
    open_trades = [
        t for t in trades_list
        if t.get("status") == "open" and t.get("source") in ("mt4", "mt5")
    ]
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


# ═══════════════════════════════════════════════════════
# TRADE EXECUTION PIPELINE
# ═══════════════════════════════════════════════════════

# In-memory execution queue (persists across requests, lost on restart)
# Each entry: { id, symbol, direction, entry, sl, tp, risk_percent, lot_size,
#               be_trigger_rr, timestamp, source, journal_trade_id, status,
#               warnings, actual_entry, executed_at }
_execution_queue = []

# Execution audit log (last N events). Each entry:
# { ts, trade_id, symbol, direction, planned_entry, actual_entry, slippage,
#   status, reason, mt4_ticket, paper, test }
_execution_log = []
_EXECUTION_LOG_MAX = 500

# Emergency stop flag — set by /api/execution/emergency_stop (kill-switch), polled by EA
_emergency_stop = {"active": False, "at": None, "by": None}

# Simple remote-pause flag — set via POST /api/mt4/emergency-stop, polled by EA via GET.
# When True the EA stops opening new trades but does NOT close existing positions.
_mt4_emergency_stop = False


def _log_execution_event(**kwargs):
    """Append an event to the execution log (most-recent first cap at MAX)."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "trade_id": kwargs.get("trade_id", ""),
        "symbol": kwargs.get("symbol", ""),
        "direction": kwargs.get("direction", ""),
        "planned_entry": kwargs.get("planned_entry"),
        "actual_entry": kwargs.get("actual_entry"),
        "slippage": kwargs.get("slippage"),
        "status": kwargs.get("status", ""),
        "reason": kwargs.get("reason", ""),
        "mt4_ticket": kwargs.get("mt4_ticket"),
        "paper": bool(kwargs.get("paper", False)),
        "test": bool(kwargs.get("test", False)),
    }
    _execution_log.append(entry)
    if len(_execution_log) > _EXECUTION_LOG_MAX:
        del _execution_log[: len(_execution_log) - _EXECUTION_LOG_MAX]
    return entry


def _require_execution_key():
    """Validate X-Execution-Key header. Returns error response or None."""
    if not EXECUTION_API_KEY:
        return jsonify({"error": "EXECUTION_API_KEY not configured on server"}), 500
    key = request.headers.get("X-Execution-Key", "")
    if not hmac.compare_digest(key, EXECUTION_API_KEY):
        return jsonify({"error": "Invalid or missing X-Execution-Key"}), 401
    return None


def _get_account_state_from_gist():
    """Read closed trades from Gist to compute daily/weekly/monthly P&L."""
    trades_list = get_trades()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Week starts Monday
    week_start = today_start - timedelta(days=now.weekday())
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    daily_pnl = 0.0
    weekly_pnl = 0.0
    monthly_pnl = 0.0
    capital = 0.0

    for t in trades_list:
        if t.get("status") != "closed" or t.get("actualPnL") is None:
            continue
        pnl = float(t.get("actualPnL", 0))
        close_date = t.get("dateClose")
        if not close_date:
            continue
        try:
            cd = datetime.fromisoformat(close_date.replace("Z", "+00:00"))
            if cd.tzinfo is None:
                cd = cd.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue

        if cd >= today_start:
            daily_pnl += pnl
        if cd >= week_start:
            weekly_pnl += pnl
        if cd >= month_start:
            monthly_pnl += pnl

    # Try to get capital from Gist settings or MT4 status
    gist_data = gist_read()
    if gist_data and isinstance(gist_data, dict):
        settings = gist_data.get("settings", {})
        capital = float(settings.get("profile", {}).get("capital", 0))
        if not capital:
            capital = float(_mt4_status.get("account_balance", 0))

    return {
        "capital": capital,
        "daily_pnl": daily_pnl,
        "weekly_pnl": weekly_pnl,
        "monthly_pnl": monthly_pnl,
    }


def validate_trade(trade, account_state=None):
    """Risk engine: validate a trade before approval.

    Returns: { approved: bool, warnings: [], reason: str, adjusted_trade: trade }
    """
    if account_state is None:
        account_state = _get_account_state_from_gist()

    warnings = []
    capital = account_state.get("capital", 0)
    risk_pct = float(trade.get("risk_percent", 1.0))

    # --- Configurable limits (passed from journal settings or use defaults) ---
    limits = trade.get("risk_limits", {})
    max_risk_per_trade = float(limits.get("riskPerTrade", 2))
    max_daily_loss = float(limits.get("dailyLoss", 2))
    max_weekly_loss = float(limits.get("weeklyLoss", 10))
    max_monthly_loss = float(limits.get("monthlyLoss", 25))

    entry = float(trade.get("entry", 0))
    sl = float(trade.get("sl", 0))
    tp = float(trade.get("tp", 0))
    direction = trade.get("direction", "").upper()

    # ── HARD BLOCKS ──
    # Missing SL or TP
    if not sl or not tp:
        return {"approved": False, "warnings": [], "reason": "Missing SL or TP", "adjusted_trade": trade}

    # SL on wrong side
    if direction == "BUY" and sl >= entry:
        return {"approved": False, "warnings": [], "reason": "SL must be below entry for BUY", "adjusted_trade": trade}
    if direction == "SELL" and sl <= entry:
        return {"approved": False, "warnings": [], "reason": "SL must be above entry for SELL", "adjusted_trade": trade}

    # TP on wrong side
    if direction == "BUY" and tp <= entry:
        return {"approved": False, "warnings": [], "reason": "TP must be above entry for BUY", "adjusted_trade": trade}
    if direction == "SELL" and tp >= entry:
        return {"approved": False, "warnings": [], "reason": "TP must be below entry for SELL", "adjusted_trade": trade}

    # Risk % too high
    if risk_pct > max_risk_per_trade:
        return {"approved": False, "warnings": [],
                "reason": f"Risk {risk_pct}% exceeds max {max_risk_per_trade}% per trade", "adjusted_trade": trade}

    # Drawdown limits (only check if capital is known)
    if capital > 0:
        daily_loss_pct = abs(min(account_state.get("daily_pnl", 0), 0)) / capital * 100
        weekly_loss_pct = abs(min(account_state.get("weekly_pnl", 0), 0)) / capital * 100
        monthly_loss_pct = abs(min(account_state.get("monthly_pnl", 0), 0)) / capital * 100

        if daily_loss_pct >= max_daily_loss:
            return {"approved": False, "warnings": [],
                    "reason": f"Daily loss {daily_loss_pct:.1f}% already at limit ({max_daily_loss}%)", "adjusted_trade": trade}
        if weekly_loss_pct >= max_weekly_loss:
            return {"approved": False, "warnings": [],
                    "reason": f"Weekly loss {weekly_loss_pct:.1f}% already at limit ({max_weekly_loss}%)", "adjusted_trade": trade}
        if monthly_loss_pct >= max_monthly_loss:
            return {"approved": False, "warnings": [],
                    "reason": f"Monthly loss {monthly_loss_pct:.1f}% already at limit ({max_monthly_loss}%)", "adjusted_trade": trade}

        # ── SOFT WARNINGS ──
        if risk_pct > 1.5:
            warnings.append(f"Risk {risk_pct}% is approaching the {max_risk_per_trade}% limit")
        if daily_loss_pct > max_daily_loss * 0.75:
            warnings.append(f"Daily loss {daily_loss_pct:.1f}% approaching {max_daily_loss}% limit")

    # Confidence warning
    confidence = int(trade.get("confidence", 0))
    if confidence > 0 and confidence < 6:
        warnings.append(f"Low confidence ({confidence}/10)")

    # DXY conflict warning
    dxy_confirms = trade.get("dxy_confirms", "")
    if dxy_confirms and dxy_confirms.lower() in ("no", "conflicts"):
        warnings.append("DXY conflicts with trade direction")

    # No entry confirmation
    entry_conf = trade.get("entry_confirmation", "")
    if not entry_conf:
        warnings.append("No entry confirmation recorded")

    return {"approved": True, "warnings": warnings, "reason": "", "adjusted_trade": trade}


# ── Execution Endpoints ────────────────────────────────

@app.route("/api/trade", methods=["GET"])
def get_pending_trade():
    """GET /api/trade — Return latest approved trade waiting for MT4 execution."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    for trade in _execution_queue:
        if trade.get("status") == "approved":
            # Mark as fetched so it doesn't execute twice
            trade["status"] = "fetched"
            trade["fetched_at"] = datetime.now(timezone.utc).isoformat()
            _log_execution_event(
                trade_id=trade["id"], symbol=trade["symbol"], direction=trade["direction"],
                planned_entry=trade["entry"], status="fetched_by_ea",
                paper=trade.get("paper", False), test=trade.get("test_only", False),
                reason="EA polled and received trade",
            )
            return jsonify({
                "status": "trade_ready",
                "trade": {
                    "id": trade["id"],
                    "symbol": trade["symbol"],
                    "direction": trade["direction"],
                    "entry": trade["entry"],
                    "sl": trade["sl"],
                    "tp": trade["tp"],
                    "risk_percent": trade["risk_percent"],
                    "lot_size": trade["lot_size"],
                    "be_trigger_rr": trade.get("be_trigger_rr", 1.5),
                    "timestamp": trade["timestamp"],
                    "source": "journal",
                    "journal_trade_id": trade.get("journal_trade_id", ""),
                    "paper_trading": trade.get("paper", PAPER_TRADING_MODE),
                    "test_only": trade.get("test_only", False),
                }
            })

    return jsonify({"status": "no_trade", "paper_trading": PAPER_TRADING_MODE})


@app.route("/api/trade/approve", methods=["POST"])
def approve_trade():
    """POST /api/trade/approve — Validate and queue a trade for MT5 execution."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body = request.json
    if not body:
        return jsonify({"error": "Request body required"}), 400

    required = ["symbol", "direction", "entry", "sl", "tp"]
    for field in required:
        if field not in body:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    # Build trade object
    trade = {
        "id": str(uuid.uuid4())[:12],
        "symbol": body["symbol"].upper(),
        "direction": body["direction"].upper(),
        "entry": float(body["entry"]),
        "sl": float(body["sl"]),
        "tp": float(body["tp"]),
        "risk_percent": float(body.get("risk_percent", 1.0)),
        "lot_size": float(body.get("lot_size", 0.01)),
        "be_trigger_rr": float(body.get("be_trigger_rr", 1.5)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "journal",
        "journal_trade_id": body.get("journal_trade_id", ""),
        "status": "pending",
        "confidence": body.get("confidence", 0),
        "dxy_confirms": body.get("dxy_confirms", ""),
        "entry_confirmation": body.get("entry_confirmation", ""),
        "risk_limits": body.get("risk_limits", {}),
        "paper": PAPER_TRADING_MODE,
        "test_only": bool(body.get("test_only", False)),
    }

    # Get account state (from body or Gist)
    account_state = body.get("account_state") or _get_account_state_from_gist()

    # Run risk engine
    result = validate_trade(trade, account_state)

    if not result["approved"]:
        # Rejected
        trade["status"] = "rejected"
        trade["reject_reason"] = result["reason"]
        _execution_queue.append(trade)

        _log_execution_event(
            trade_id=trade["id"], symbol=trade["symbol"], direction=trade["direction"],
            planned_entry=trade["entry"], status="rejected",
            paper=trade.get("paper", False), test=trade.get("test_only", False),
            reason=result["reason"],
        )

        msg = (
            f"\u274c <b>Trade REJECTED by risk engine</b>\n\n"
            f"<b>{trade['symbol']}</b> {trade['direction']}\n"
            f"Entry: {trade['entry']} | SL: {trade['sl']} | TP: {trade['tp']}\n"
            f"Risk: {trade['risk_percent']}%\n\n"
            f"\U0001f6ab Reason: <b>{result['reason']}</b>\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
        )
        send_telegram(msg)

        return jsonify({
            "approved": False,
            "reason": result["reason"],
            "warnings": result["warnings"],
            "trade_id": trade["id"],
        }), 200

    # Approved
    trade["status"] = "approved"
    trade["warnings"] = result["warnings"]
    _execution_queue.append(trade)

    _log_execution_event(
        trade_id=trade["id"], symbol=trade["symbol"], direction=trade["direction"],
        planned_entry=trade["entry"], status="approved",
        paper=trade.get("paper", False), test=trade.get("test_only", False),
        reason="Risk engine approved" + (" (with warnings)" if result["warnings"] else ""),
    )

    warning_text = ""
    if result["warnings"]:
        warning_text = "\n\u26a0\ufe0f Warnings:\n" + "\n".join(f"  \u2022 {w}" for w in result["warnings"]) + "\n"

    msg = (
        f"\u2705 <b>Trade approved and queued for MT5!</b>\n\n"
        f"<b>{trade['symbol']}</b> {trade['direction']}\n"
        f"\U0001f4cd Entry: {trade['entry']} | SL: {trade['sl']} | TP: {trade['tp']}\n"
        f"\U0001f4b0 Risk: {trade['risk_percent']}% | Lot: {trade['lot_size']}\n"
        f"{warning_text}\n"
        f"Waiting for MT5 EA to fetch...\n\n"
        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
    )
    send_telegram(msg)

    logging.info("Trade approved: %s %s %s @ %s", trade["id"], trade["symbol"], trade["direction"], trade["entry"])
    return jsonify({
        "approved": True,
        "warnings": result["warnings"],
        "trade_id": trade["id"],
        "trade": trade,
    }), 201


@app.route("/api/trade/executed", methods=["POST"])
def trade_executed():
    """POST /api/trade/executed — Called by the MT5 EA when a trade is placed."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body = request.json
    if not body or not body.get("id"):
        return jsonify({"error": "Trade id required"}), 400

    trade_id = body["id"]
    found = None
    for t in _execution_queue:
        if t["id"] == trade_id:
            found = t
            break

    if not found:
        return jsonify({"error": "Trade not found in execution queue"}), 404

    actual_entry = float(body.get("actual_entry", found["entry"]))
    is_paper = bool(body.get("paper", found.get("paper", False)))
    is_test = bool(body.get("test", found.get("test_only", False)))
    err_text = body.get("error", "")

    if is_test:
        new_status = "test_passed" if not err_text else "test_failed"
    elif err_text:
        new_status = "execution_failed"
    elif is_paper:
        new_status = "paper_executed"
    else:
        new_status = "executed"

    found["status"] = new_status
    found["actual_entry"] = actual_entry
    found["executed_at"] = datetime.now(timezone.utc).isoformat()
    found["mt4_ticket"] = body.get("ticket")
    found["paper"] = is_paper
    found["test_only"] = is_test
    if err_text:
        found["error"] = err_text

    # Slippage in raw price units
    slippage = round(actual_entry - found["entry"], 6) if actual_entry and found.get("entry") else None

    _log_execution_event(
        trade_id=trade_id, symbol=found["symbol"], direction=found["direction"],
        planned_entry=found["entry"], actual_entry=actual_entry, slippage=slippage,
        status=new_status, mt4_ticket=body.get("ticket"),
        paper=is_paper, test=is_test, reason=err_text or "OK",
    )

    # Update journal entry via Gist (skip for test trades and execution failures)
    journal_id = found.get("journal_trade_id")
    if journal_id and not is_test and not err_text:
        try:
            trades_list = get_trades()
            for t in trades_list:
                if t.get("id") == journal_id:
                    t["status"] = "open"
                    # Newly executed trades tagged as mt5; legacy mt4 rows stay tagged mt4.
                    t["source"] = (body.get("platform") or "mt5").lower()
                    t["platform"] = t["source"]
                    t["mt4Ticket"] = body.get("ticket")
                    t["entry"] = actual_entry
                    t["execStatus"] = new_status  # paper_executed or executed
                    t["execTicket"] = body.get("ticket")
                    t["execActualEntry"] = actual_entry
                    t["execExecutedAt"] = found["executed_at"]
                    t["execPaper"] = is_paper
                    t["updatedAt"] = datetime.now(timezone.utc).isoformat()
                    break
            save_trades(trades_list)
        except Exception as e:
            logging.error("Failed to update journal via Gist: %s", e)

    if is_test:
        msg = (
            f"\U0001f9ea <b>TEST trade pipeline OK</b>\n\n"
            f"Trade ID: <code>{trade_id}</code>\n"
            f"Symbol: {found['symbol']} {found['direction']}\n"
            f"Status: <b>{new_status}</b>\n"
            f"{('Error: ' + err_text) if err_text else 'All steps passed \u2705'}"
        )
    elif err_text:
        msg = (
            f"\u26a0\ufe0f <b>Trade execution FAILED</b>\n\n"
            f"<b>{found['symbol']}</b> {found['direction']}\n"
            f"Planned entry: {found['entry']} | Lot: {found['lot_size']}\n"
            f"Error: <b>{err_text}</b>\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
        )
    else:
        prefix = "\U0001f4c4 <b>PAPER TRADE executed (demo mode)</b>" if is_paper else "\U0001f680 <b>Trade EXECUTED on MT5!</b>"
        msg = (
            f"{prefix}\n\n"
            f"<b>{found['symbol']}</b> {found['direction']}\n"
            f"\U0001f4cd Planned entry: {found['entry']}\n"
            f"\U0001f4cd Actual entry: {actual_entry}\n"
            f"\U0001f4e6 Lot: {found['lot_size']}\n"
            f"\U0001f6d1 SL: {found['sl']} | \U0001f3af TP: {found['tp']}\n"
            f"{'Ticket: #' + str(body.get('ticket', '')) if body.get('ticket') else ''}\n"
            f"Journal updated automatically \u2705\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
        )
    send_telegram(msg)

    logging.info("Trade executed: %s %s actual_entry=%s", trade_id, found["symbol"], actual_entry)
    return jsonify({"ok": True, "trade": found})


@app.route("/api/trade/cancelled", methods=["POST"])
def trade_cancelled():
    """POST /api/trade/cancelled — Cancel a pending trade."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body = request.json
    if not body or not body.get("id"):
        return jsonify({"error": "Trade id required"}), 400

    trade_id = body["id"]
    found = None
    for t in _execution_queue:
        if t["id"] == trade_id:
            found = t
            break

    if not found:
        return jsonify({"error": "Trade not found in execution queue"}), 404

    found["status"] = "cancelled"
    found["cancelled_at"] = datetime.now(timezone.utc).isoformat()

    _log_execution_event(
        trade_id=trade_id, symbol=found["symbol"], direction=found["direction"],
        planned_entry=found["entry"], status="cancelled",
        paper=found.get("paper", False), test=found.get("test_only", False),
        reason=body.get("reason") or "Manual cancel",
    )

    msg = (
        f"\u274c <b>Trade cancelled</b>\n\n"
        f"<b>{found['symbol']}</b> {found['direction']}\n"
        f"Entry: {found['entry']} | SL: {found['sl']} | TP: {found['tp']}\n\n"
        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
    )
    send_telegram(msg)

    logging.info("Trade cancelled: %s %s", trade_id, found["symbol"])
    return jsonify({"ok": True})


@app.route("/api/trade/status/<trade_id>", methods=["GET"])
def trade_status(trade_id):
    """GET /api/trade/status/:id — Return current status of a trade."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    for t in _execution_queue:
        if t["id"] == trade_id:
            return jsonify({
                "id": t["id"],
                "status": t["status"],
                "symbol": t["symbol"],
                "direction": t["direction"],
                "warnings": t.get("warnings", []),
                "reject_reason": t.get("reject_reason"),
                "executed_at": t.get("executed_at"),
                "mt4_ticket": t.get("mt4_ticket"),
            })

    return jsonify({"error": "Trade not found"}), 404


@app.route("/api/execution/queue", methods=["GET"])
def execution_queue():
    """GET /api/execution/queue — Return all trades in the execution queue."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    pending = [t for t in _execution_queue if t.get("status") in ("approved", "pending", "fetched")]
    return jsonify({
        "queue": [{
            "id": t["id"],
            "symbol": t["symbol"],
            "direction": t["direction"],
            "entry": t["entry"],
            "sl": t["sl"],
            "tp": t["tp"],
            "lot_size": t["lot_size"],
            "risk_percent": t["risk_percent"],
            "status": t["status"],
            "timestamp": t["timestamp"],
            "warnings": t.get("warnings", []),
            "journal_trade_id": t.get("journal_trade_id", ""),
        } for t in pending],
        "total": len(pending),
    })


@app.route("/api/execution/log", methods=["GET"])
def execution_log():
    """GET /api/execution/log?limit=50&status=executed — Filtered execution audit log (newest first)."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, _EXECUTION_LOG_MAX))

    status_filter = (request.args.get("status") or "").strip().lower()

    entries = list(reversed(_execution_log))
    if status_filter and status_filter != "all":
        if status_filter == "success":
            entries = [e for e in entries if e["status"] in ("executed", "paper_executed", "test_passed")]
        elif status_filter == "failed":
            entries = [e for e in entries if e["status"] in ("execution_failed", "test_failed", "rejected")]
        elif status_filter == "paper":
            entries = [e for e in entries if e.get("paper")]
        else:
            entries = [e for e in entries if e["status"] == status_filter]

    return jsonify({
        "log": entries[:limit],
        "total": len(_execution_log),
        "returned": min(limit, len(entries)),
    })


@app.route("/api/execution/test", methods=["POST"])
def execution_test():
    """POST /api/execution/test — Inject a synthetic test trade into the pipeline.

    Test trades flow through the full pipeline (queue → EA fetch → executed callback)
    but skip OrderSend() in the EA and never touch the journal Gist.
    """
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body = request.json or {}

    test_trade = {
        "id": "test-" + str(uuid.uuid4())[:8],
        "symbol": (body.get("symbol") or "EURUSD").upper(),
        "direction": (body.get("direction") or "BUY").upper(),
        "entry": float(body.get("entry", 1.10000)),
        "sl": float(body.get("sl", 1.09500)),
        "tp": float(body.get("tp", 1.11500)),
        "risk_percent": 0.1,
        "lot_size": 0.01,
        "be_trigger_rr": 1.5,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "execution_test",
        "journal_trade_id": "",
        "status": "approved",
        "warnings": ["TEST TRADE — will not be executed on broker"],
        "paper": True,
        "test_only": True,
    }
    _execution_queue.append(test_trade)

    _log_execution_event(
        trade_id=test_trade["id"], symbol=test_trade["symbol"], direction=test_trade["direction"],
        planned_entry=test_trade["entry"], status="approved",
        paper=True, test=True, reason="Synthetic test trade injected",
    )

    return jsonify({
        "ok": True,
        "trade_id": test_trade["id"],
        "message": "Test trade queued. EA will fetch within 5s. Poll /api/trade/status/<id> to track.",
        "trade": test_trade,
    }), 201


@app.route("/api/execution/health", methods=["GET"])
def execution_health():
    """GET /api/execution/health — Aggregated status of all execution pipeline components."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    now = datetime.now(timezone.utc)

    # Backend — we are responding, so green
    backend_ok = True

    # MT4/MT5 EA — connected if heartbeat within last 2 minutes.
    # Dict key stays "mt4" so existing frontend consumers keep working.
    mt4_ok = False
    mt4_age_seconds = None
    if _mt4_status.get("last_heartbeat"):
        try:
            last = datetime.fromisoformat(_mt4_status["last_heartbeat"])
            mt4_age_seconds = (now - last).total_seconds()
            mt4_ok = mt4_age_seconds < 120
        except Exception:
            mt4_ok = False

    # Queue
    pending = [t for t in _execution_queue if t.get("status") in ("approved", "pending", "fetched")]

    # Risk engine — green if EXECUTION_API_KEY is set (means risk pipeline is actually wired)
    risk_engine_ok = bool(EXECUTION_API_KEY)

    # Telegram
    telegram_ok = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

    # Gist
    gist_ok = bool(GITHUB_GIST_TOKEN)

    return jsonify({
        "backend": {"ok": backend_ok, "label": "Backend reachable"},
        "mt4": {
            "ok": mt4_ok,
            "label": "MT5 EA connected" if mt4_ok else "MT5 EA offline",
            "last_heartbeat": _mt4_status.get("last_heartbeat"),
            "age_seconds": mt4_age_seconds,
            "open_trades": _mt4_status.get("open_trades", 0),
            "account_equity": _mt4_status.get("account_equity", 0),
        },
        "queue": {
            "ok": True,
            "label": f"{len(pending)} pending",
            "pending_count": len(pending),
            "total_logged": len(_execution_log),
        },
        "risk_engine": {
            "ok": risk_engine_ok,
            "label": "Risk engine armed" if risk_engine_ok else "EXECUTION_API_KEY missing",
        },
        "paper_mode": {
            "ok": True,
            "active": PAPER_TRADING_MODE,
            "label": "PAPER MODE — demo only" if PAPER_TRADING_MODE else "LIVE mode",
        },
        "telegram": {"ok": telegram_ok, "label": "Telegram configured" if telegram_ok else "Telegram missing"},
        "gist": {"ok": gist_ok, "label": "Gist token present" if gist_ok else "Gist token missing"},
        "emergency_stop": {
            "active": _emergency_stop["active"],
            "at": _emergency_stop["at"],
            "by": _emergency_stop["by"],
        },
        "checked_at": now.isoformat(),
    })


@app.route("/api/execution/emergency_stop", methods=["POST"])
def execution_emergency_stop():
    """POST /api/execution/emergency_stop — KILL SWITCH.

    Cancels every pending/approved trade in the queue, sets the emergency_stop flag
    so the EA picks it up and closes all POIWatcher_-prefixed positions, and fires
    a high-priority Telegram alert.
    """
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body = request.json or {}
    by = body.get("by") or "journal"

    cancelled = 0
    for t in _execution_queue:
        if t.get("status") in ("approved", "pending", "fetched"):
            t["status"] = "cancelled"
            t["cancelled_at"] = datetime.now(timezone.utc).isoformat()
            t["cancel_reason"] = "Emergency stop"
            cancelled += 1
            _log_execution_event(
                trade_id=t["id"], symbol=t["symbol"], direction=t["direction"],
                planned_entry=t["entry"], status="cancelled",
                paper=t.get("paper", False), test=t.get("test_only", False),
                reason="EMERGENCY STOP",
            )

    _emergency_stop["active"] = True
    _emergency_stop["at"] = datetime.now(timezone.utc).isoformat()
    _emergency_stop["by"] = by

    msg = (
        f"\U0001f6d1 <b>EMERGENCY STOP ACTIVATED</b>\n\n"
        f"\u2022 Cancelled <b>{cancelled}</b> pending trade(s)\n"
        f"\u2022 EA instructed to close all POIWatcher positions\n"
        f"\u2022 Triggered by: {by}\n\n"
        f"\u26a0\ufe0f New approvals will still queue. Reset the kill switch in the journal when ready."
    )
    send_telegram(msg)

    logging.warning("EMERGENCY STOP activated by %s — %d trades cancelled", by, cancelled)
    return jsonify({
        "ok": True,
        "cancelled": cancelled,
        "emergency_stop": _emergency_stop,
    })


@app.route("/api/debug/key-echo", methods=["GET"])
def debug_key_echo():
    """Diagnostic endpoint for debugging 401s on X-Execution-Key.

    Returns a byte-level comparison of what the caller transmitted in the
    X-Execution-Key header vs what EXECUTION_API_KEY is set to on the server.
    Never returns the server key — only its first 4 chars and length, so no
    secret is leaked. The hex of the *received* value is safe to return
    because the caller already knows what they sent (helps them spot hidden
    whitespace / smart-quote / encoding issues on their side).

    No auth required (this is precisely the tool for diagnosing when auth
    is failing). Intentionally not linked anywhere; leave it in place only
    while debugging.
    """
    received = request.headers.get("X-Execution-Key", "")
    server   = EXECUTION_API_KEY or ""

    def preview(s):
        return s[:4] if len(s) >= 4 else s

    received_hex = received.encode("utf-8").hex()

    return jsonify({
        "received": {
            "first4":    preview(received),
            "len_chars": len(received),
            "len_bytes": len(received.encode("utf-8")),
            "hex":       received_hex,
        },
        "server": {
            "first4":    preview(server),
            "len_chars": len(server),
            "len_bytes": len(server.encode("utf-8")),
            "configured": bool(server),
        },
        "match": bool(server) and hmac.compare_digest(received, server),
    })


@app.route("/api/mt4/emergency-stop", methods=["GET"])
@app.route("/api/mt5/emergency-stop", methods=["GET"])
def mt4_emergency_stop_get():
    """GET /api/mt[4|5]/emergency-stop — EA polls every 10s to check for remote pause.

    Requires X-Execution-Key.  Returns the simple remote-pause flag (_mt4_emergency_stop)
    so the EA can stop opening new trades without closing existing ones.
    Both /mt4/ and /mt5/ paths resolve here so legacy MQL4 and current MQL5 EAs
    both work. The response exposes the legacy 'active' field for MQL4 compat.
    """
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    return jsonify({
        "emergency": _mt4_emergency_stop,
        "active":    _mt4_emergency_stop,          # backward compat with MQL4 EA
        "message":   (
            "EMERGENCY STOP — EA trading paused remotely. "
            "Deactivate in journal to resume."
        ) if _mt4_emergency_stop else "All clear — continue trading",
        "kill_switch": _emergency_stop,            # separate kill-switch state for reference
    })


@app.route("/api/mt4/emergency-stop", methods=["POST"])
@app.route("/api/mt5/emergency-stop", methods=["POST"])
def mt4_emergency_stop_post():
    """POST /api/mt[4|5]/emergency-stop — Activate or deactivate the EA remote pause flag.

    Body: {"emergency": true | false}
    When activated the EA will stop opening new trades on its next 10s poll.
    Existing open positions are NOT closed — use /api/execution/emergency_stop for that.
    """
    global _mt4_emergency_stop

    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body    = request.json or {}
    activate = bool(body.get("emergency", False))
    _mt4_emergency_stop = activate

    if activate:
        msg = (
            "\U0001f6a8 <b>EMERGENCY STOP ACTIVATED!</b>\n\n"
            "All EA trading halted remotely.\n"
            "To resume: deactivate emergency stop in your journal app."
        )
        logging.warning("MT5 emergency stop ACTIVATED via API")
    else:
        msg = (
            "\u2705 <b>Emergency stop DEACTIVATED.</b>\n\n"
            "EA trading resumed."
        )
        logging.info("MT5 emergency stop deactivated via API")

    send_telegram(msg)

    return jsonify({
        "ok":      True,
        "emergency": _mt4_emergency_stop,
        "message": (
            "EMERGENCY STOP — EA trading paused remotely."
        ) if _mt4_emergency_stop else "All clear — continue trading",
    })


@app.route("/api/mt4/emergency-stop", methods=["DELETE"])
@app.route("/api/mt5/emergency-stop", methods=["DELETE"])
def mt4_emergency_stop_clear():
    """DELETE /api/mt[4|5]/emergency-stop — EA ack after closing POIWatcher trades, or journal reset.

    Clears BOTH the simple remote-pause flag and the kill-switch state. Both
    /mt4/ and /mt5/ paths resolve here for MQL4/MQL5 EA compatibility.
    """
    global _mt4_emergency_stop

    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body         = request.json or {}
    closed_count = body.get("closed_count")

    # Clear both flags
    _mt4_emergency_stop       = False
    _emergency_stop["active"] = False
    _emergency_stop["at"]     = None
    _emergency_stop["by"]     = None

    if closed_count is not None:
        msg = (
            f"\u2705 <b>Emergency stop cleared</b>\n\n"
            f"EA closed {closed_count} POIWatcher position(s). Pipeline is armed again."
        )
        send_telegram(msg)

    logging.info("Emergency stop cleared (closed_count=%s)", closed_count)
    return jsonify({"ok": True, "emergency": False, "emergency_stop": _emergency_stop})


# ── Daily Summary (5pm ET) ──────────────────────────────

# ET is UTC-5 (EST) or UTC-4 (EDT). For simplicity treat 5pm ET as a fixed UTC
# offset using the current US daylight rule via timezone-aware datetime.
# We don't depend on pytz/zoneinfo to keep deployment lightweight; assume EDT
# (UTC-4) Mar–Nov and EST (UTC-5) Nov–Mar. Good enough for a daily ping.
def _is_us_dst(now_utc):
    # US DST: 2nd Sunday of March → 1st Sunday of November
    y = now_utc.year
    march = datetime(y, 3, 8, tzinfo=timezone.utc)
    dst_start = march + timedelta(days=(6 - march.weekday()) % 7)
    nov = datetime(y, 11, 1, tzinfo=timezone.utc)
    dst_end = nov + timedelta(days=(6 - nov.weekday()) % 7)
    return dst_start <= now_utc < dst_end


def _et_now():
    now = datetime.now(timezone.utc)
    offset = -4 if _is_us_dst(now) else -5
    return now + timedelta(hours=offset), offset


_last_summary_date = None


def _build_daily_summary():
    """Build the daily summary message from journal trades closed today (ET)."""
    et_now, _ = _et_now()
    today_et = et_now.date()
    today_str = today_et.strftime("%a %b %d, %Y")

    try:
        all_trades = get_trades() or []
    except Exception as e:
        logging.error("Daily summary: get_trades failed: %s", e)
        all_trades = []

    closed_today = []
    for t in all_trades:
        if t.get("status") != "closed":
            continue
        d = t.get("dateClose") or t.get("dateOpen") or ""
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            offset = -4 if _is_us_dst(dt.astimezone(timezone.utc)) else -5
            dt_et = dt.astimezone(timezone.utc) + timedelta(hours=offset)
            if dt_et.date() == today_et:
                closed_today.append(t)
        except Exception:
            continue

    n = len(closed_today)
    wins = [t for t in closed_today if t.get("outcome") == "win"]
    losses = [t for t in closed_today if t.get("outcome") == "loss"]
    win_rate = (len(wins) / n * 100) if n else 0
    total_pnl = sum(float(t.get("actualPnL") or 0) for t in closed_today)

    best = max(closed_today, key=lambda t: float(t.get("actualPnL") or 0), default=None)
    worst = min(closed_today, key=lambda t: float(t.get("actualPnL") or 0), default=None)

    # Drawdown vs limits — read latest settings from gist if available
    settings = {}
    try:
        gist_data = _get_gist_data()
        if gist_data and isinstance(gist_data, dict):
            settings = gist_data.get("settings", {}) or {}
    except Exception:
        pass

    profile = (settings.get("profile") or {})
    capital = float(profile.get("capital") or 0)
    daily_limit = float(profile.get("ddDaily") or 2)
    weekly_limit = float(profile.get("ddWeekly") or 10)

    # Daily DD %
    daily_pnl = total_pnl
    daily_dd_pct = (-daily_pnl / capital * 100) if capital and daily_pnl < 0 else 0

    # Weekly DD = sum P&L of trades closed in last 7 days
    week_start = today_et - timedelta(days=6)
    weekly_pnl = 0.0
    for t in all_trades:
        if t.get("status") != "closed":
            continue
        d = t.get("dateClose") or t.get("dateOpen") or ""
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            offset = -4 if _is_us_dst(dt.astimezone(timezone.utc)) else -5
            dt_et = dt.astimezone(timezone.utc) + timedelta(hours=offset)
            if week_start <= dt_et.date() <= today_et:
                weekly_pnl += float(t.get("actualPnL") or 0)
        except Exception:
            continue
    weekly_dd_pct = (-weekly_pnl / capital * 100) if capital and weekly_pnl < 0 else 0

    def dd_emoji(used_pct, limit_pct):
        if limit_pct <= 0:
            return "\u2705"
        ratio = used_pct / limit_pct
        if ratio >= 1:
            return "\U0001f6a8"
        if ratio >= 0.7:
            return "\u26a0\ufe0f"
        return "\u2705"

    # Quality metrics
    exec_ratings = [int(t.get("executionRating") or 0) for t in closed_today if t.get("executionRating")]
    avg_exec = (sum(exec_ratings) / len(exec_ratings)) if exec_ratings else 0
    confidences = [int(t.get("confidence") or 0) for t in closed_today if t.get("confidence")]
    avg_align = (sum(confidences) / len(confidences)) if confidences else 0

    pnl_sign = "+" if total_pnl >= 0 else ""
    msg = f"\U0001f4ca <b>DAILY TRADING SUMMARY \u2014 {today_str}</b>\n\n"

    if n == 0:
        msg += "No trades closed today.\n\n"
    else:
        msg += f"Trades taken: <b>{n}</b>\n"
        msg += f"Wins: <b>{len(wins)}</b> | Losses: <b>{len(losses)}</b> | Win Rate: <b>{win_rate:.0f}%</b>\n"
        msg += f"Total P&amp;L: <b>{pnl_sign}${total_pnl:.2f}</b>\n\n"

        if best and float(best.get("actualPnL") or 0) > 0:
            br = best.get("actualRR") or 0
            msg += f"Best trade: {best.get('pair', '?')} +${float(best.get('actualPnL') or 0):.2f} (+{float(br):.1f}R)\n"
        if worst and float(worst.get("actualPnL") or 0) < 0:
            wr = worst.get("actualRR") or 0
            msg += f"Worst trade: {worst.get('pair', '?')} ${float(worst.get('actualPnL') or 0):.2f} ({float(wr):.1f}R)\n"
        msg += "\n"

    msg += "<b>Drawdown status:</b>\n"
    msg += f"Daily: {daily_dd_pct:.1f}% / {daily_limit:.0f}% limit {dd_emoji(daily_dd_pct, daily_limit)}\n"
    msg += f"Weekly: {weekly_dd_pct:.1f}% / {weekly_limit:.0f}% limit {dd_emoji(weekly_dd_pct, weekly_limit)}\n\n"

    if avg_exec or avg_align:
        msg += f"Execution quality: <b>{avg_exec:.1f}/10</b> avg\n"
        msg += f"System alignment: <b>{avg_align:.1f}/10</b> avg\n\n"

    msg += "Keep following your system! \U0001f4aa\n\n"
    msg += f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open your journal</a>"
    return msg


def daily_summary_loop():
    """Background loop — sends daily summary at 5:00 PM ET each day."""
    global _last_summary_date
    logging.info("Daily summary loop started (sends 5:00 PM ET)")
    while True:
        try:
            et_now, _ = _et_now()
            target_hour = 17  # 5 PM
            if et_now.hour == target_hour and _last_summary_date != et_now.date():
                msg = _build_daily_summary()
                send_telegram(msg)
                _last_summary_date = et_now.date()
                logging.info("Daily summary sent for %s", et_now.date())
        except Exception as e:
            logging.error("Daily summary loop error: %s", e)
        # Sleep ~60s; coarse enough for a once-a-day check
        time.sleep(60)


def _get_gist_data():
    """Fetch the parsed gist JSON. Wrapper that returns dict (or None)."""
    data = gist_read()
    if isinstance(data, dict):
        return data
    return None


# ── Start ───────────────────────────────────────────────

def _start_background_threads():
    """Start all background threads."""
    threading.Thread(target=price_monitor_loop, daemon=True).start()
    if KRAKEN_API_KEY or BINANCE_API_KEY:
        threading.Thread(target=exchange_sync_loop, daemon=True).start()
        logging.info("Exchange sync started — Kraken: %s, Binance: %s",
                     "enabled" if KRAKEN_API_KEY else "disabled",
                     "enabled" if BINANCE_API_KEY else "disabled")
    threading.Thread(target=daily_summary_loop, daemon=True).start()


if __name__ == "__main__":
    _start_background_threads()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
else:
    # When run via gunicorn, also start background threads
    _start_background_threads()
