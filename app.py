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
from collections import deque
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
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# ── Bitunix Futures (primary crypto futures venue) ──
BITUNIX_API_KEY = os.environ.get("BITUNIX_API_KEY", "")
BITUNIX_API_SECRET = os.environ.get("BITUNIX_API_SECRET", "")
BITUNIX_DEFAULT_LEVERAGE = int(os.environ.get("BITUNIX_DEFAULT_LEVERAGE", "10") or "10")
BITUNIX_MARGIN_MODE = (os.environ.get("BITUNIX_MARGIN_MODE", "CROSS") or "CROSS").upper()
BITUNIX_BASE_URL = "https://fapi.bitunix.com"

# ── Symbol mapping for multi-source APIs ──
SYMBOL_MAP = {
    "BTCUSDT": {"coingecko": "bitcoin", "coincap": "bitcoin"},
    "ETHUSDT": {"coingecko": "ethereum", "coincap": "ethereum"},
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


def _price_coincap(symbol):
    """PRIMARY — CoinCap (free, no geo restrictions)."""
    ids = _get_symbol_ids(symbol)
    r = requests.get(f"https://api.coincap.io/v2/assets/{ids['coincap']}", timeout=10)
    if r.status_code == 429:
        _set_cooldown("CoinCap")
        r.raise_for_status()
    r.raise_for_status()
    return float(r.json()["data"]["priceUsd"])


def _price_coingecko(symbol):
    """BACKUP — CoinGecko (strict rate limits on free tier)."""
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
    """Get price: check cache first, then Bitunix → CoinGecko → CoinCap with cooldowns.

    Bitunix is the PRIMARY source because we trade against its order book; using
    its own ticker minimises any cross-venue spread when the journal app shows
    a live price. Falls back through CoinGecko, then CoinCap as last resort.
    """
    now = time.time()

    # 1. Return cached price if still fresh
    cached = _price_cache.get(symbol)
    if cached and (now - cached["time"]) < CACHE_TTL:
        return cached["price"]

    # 2. Try sources in order, skipping any on cooldown
    sources = [
        ("Bitunix",   _price_bitunix),
        ("CoinGecko", _price_coingecko),
        ("CoinCap",   _price_coincap),
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


def get_btc_price():
    """Convenience wrapper for BTCUSDT price."""
    return get_price("BTCUSDT")


def get_eth_price():
    """Convenience wrapper for ETHUSDT price (same fallback chain)."""
    return get_price("ETHUSDT")


def _get_forex_price(symbol):
    """Fetch current FX rate for a 6-letter pair like 'EURUSD'.

    Uses frankfurter.app (ECB-backed, no auth, no rate limit for our
    volumes). Returns a mid-market rate as a float. Raises on failure;
    callers are expected to have a fallback.
    """
    if not (len(symbol) == 6 and symbol.isalpha()):
        raise ValueError(f"Not a standard 6-letter forex pair: {symbol}")
    base  = symbol[:3].upper()
    quote = symbol[3:].upper()
    r = requests.get(
        f"https://api.frankfurter.app/latest?from={base}&to={quote}",
        timeout=5,
    )
    r.raise_for_status()
    data = r.json()
    rate = (data.get("rates") or {}).get(quote)
    if not rate:
        raise RuntimeError(f"No rate returned for {symbol}: {data}")
    return float(rate)


def _test_trade_levels(symbol, direction="BUY"):
    """Generate realistic entry/SL/TP/lot for a synthetic pipeline test trade.

    Stops are placed relative to the *current market price* so MT5 won't
    reject with retcode 10016 (invalid stops). Falls back to sensible
    ball-park levels if the live-price source is unreachable so the
    pipeline test still runs when the network is flaky.

    Returns (entry, sl, tp, lot).
    """
    sym = symbol.upper()
    direction = direction.upper()

    # ── Crypto: reuse existing multi-source get_price() ──
    if sym in ("BTCUSDT", "ETHUSDT"):
        try:
            entry = get_price(sym)
        except Exception as e:
            logging.warning("Test-trade price fetch failed for %s: %s — using fallback", sym, e)
            entry = 65000.0 if sym == "BTCUSDT" else 3500.0
        if sym == "BTCUSDT":
            stop_dist, tgt_dist = 500.0, 1500.0
        else:  # ETHUSDT
            stop_dist, tgt_dist = 30.0, 90.0
        lot = 0.001
        decimals = 2

    # ── Forex: 6-letter pair via frankfurter.app ──
    elif len(sym) == 6 and sym.isalpha():
        try:
            entry = _get_forex_price(sym)
        except Exception as e:
            logging.warning("FX test-trade price fetch failed for %s: %s — using fallback", sym, e)
            fallbacks = {
                "EURUSD": 1.0870, "GBPUSD": 1.2650, "AUDUSD": 0.6600,
                "NZDUSD": 0.6000, "USDCAD": 1.3600, "USDCHF": 0.8800,
                "USDJPY": 149.50, "EURJPY": 162.50, "GBPJPY": 189.50,
            }
            entry = fallbacks.get(sym, 1.0000)
        # JPY pairs quote to 2-3 decimals (pip = 0.01); others 4-5 (pip = 0.0001)
        pip = 0.01 if sym.endswith("JPY") else 0.0001
        stop_dist = 50 * pip
        tgt_dist  = 150 * pip
        lot = 0.01
        decimals = 3 if sym.endswith("JPY") else 5

    # ── Anything else: last-ditch safe defaults ──
    else:
        return (1.0, 0.995, 1.015, 0.01)

    # Direction-aware placement
    if direction == "BUY":
        sl = entry - stop_dist
        tp = entry + tgt_dist
    else:  # SELL — flip stops/targets
        sl = entry + stop_dist
        tp = entry - tgt_dist

    return (
        round(entry, decimals),
        round(sl,    decimals),
        round(tp,    decimals),
        lot,
    )


def get_klines(symbol="BTCUSDT", interval="1d", limit=200):
    """Get OHLCV candle data via CoinGecko (only kline source post-Kraken removal)."""
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
        # Journal-link metadata: when the EA fills a queued trade it forwards
        # the journal entry id that spawned the execution. Stored on this
        # auto-logged row so the close-side matcher has another path to link
        # opens that originated from the journal but were materialised by the
        # EA as fresh "mt4_<ticket>" rows.
        "journalTradeId": body.get("journal_trade_id"),
        "executionQueueId": body.get("execution_queue_id"),
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

    # Telegram notification — differentiate limit fills from regular opens
    direction = body.get("direction", "Long")
    symbol = body.get("symbol", "")
    entry = body.get("entry_price", 0)
    sl = body.get("stop_loss", 0)
    tp = body.get("take_profit", 0)
    lot = body.get("lot_size", 0)
    order_type = body.get("order_type", "market").lower()
    planned_entry = body.get("planned_entry")
    actual_entry = body.get("actual_entry")
    slippage_pips = body.get("slippage")
    queue_id = body.get("execution_queue_id", "")

    platform_label = trade.get("platform", "mt5").upper()

    if order_type == "limit":
        # Mark matching pending limit order as filled
        for lo in _pending_limit_orders:
            if lo["id"] == queue_id or lo.get("order_ticket") == body.get("ticket"):
                lo["status"] = "limit_order_filled"
                lo["filled_at"] = datetime.now(timezone.utc).isoformat()
                lo["actual_entry"] = actual_entry
                break

        slip_str = f"{slippage_pips:.1f}" if slippage_pips is not None else "0"
        msg = (
            f"\u2705 <b>Limit order FILLED!</b>\n\n"
            f"<b>{symbol}</b> — {direction}\n"
            f"\U0001f4cd Ordered at: <b>{planned_entry}</b>\n"
            f"\U0001f4cd Filled at: <b>{actual_entry}</b>\n"
            f"\U0001f4e6 Lot size: {lot}\n"
            f"\U0001f6d1 SL: {sl} | \U0001f3af TP: {tp}\n"
            f"Slippage: {slip_str} pips\n"
            f"Trade is now LIVE \U0001f3af\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open your journal to add your analysis!</a>"
        )
        _log_execution_event(
            trade_id=queue_id, symbol=symbol, direction=direction.upper(),
            planned_entry=planned_entry, actual_entry=actual_entry,
            slippage=slippage_pips, status="limit_order_filled",
            mt4_ticket=body.get("ticket"),
            paper=trade.get("paper", False),
            reason="Limit order filled on MT5",
        )
    else:
        msg = (
            f"\U0001f4ca <b>Trade opened on {platform_label}!</b>\n\n"
            f"<b>{symbol}</b> — {direction}\n"
            f"\U0001f4cd Entry: <b>{entry}</b>\n"
            f"\U0001f6d1 SL: {sl} | \U0001f3af TP: {tp}\n"
            f"\U0001f4e6 Lot size: {lot}\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open your journal to add your analysis!</a>"
        )
    send_telegram(msg)

    logging.info("%s trade opened: #%s %s %s @ %s (order_type=%s)",
                 platform_label, body.get("ticket"), symbol, direction, entry, order_type)
    return jsonify({"ok": True, "trade_id": trade["id"]}), 201


@app.route("/mt4/trade-close", methods=["POST"])
@app.route("/mt5/trade-close", methods=["POST"])
def mt4_trade_close():
    """MT4/MT5 close webhook.

    Three-tier matching strategy — we want the journal Gist row that this
    closed position originated from, even when the row id and the MT5 ticket
    don't share a prefix:

      Tier 1 — exact match on ``journalTradeId`` / ``id`` against the
               ``journal_trade_id`` the EA stored when fetching from
               /api/trade. This is the strongest link.
      Tier 2 — match on the MT5 ticket. Catches rows that were auto-logged
               by /mt5/trade-open (id = "mt4_<ticket>"). Also catches rows
               where the user manually pasted the ticket.
      Tier 3 — fuzzy match by symbol + approximate entry + open date.
               Last-resort heuristic for legacy rows that have neither.

    On a hit we patch the row with the EA's full close payload and notify
    Telegram. On a miss we *still* persist the close as a fresh auto-logged
    row marked ``mt5AutoClose=True, reviewNeeded=True`` so the user can
    review and link it manually from the journal.
    """
    body = request.json
    if not body or not body.get("ticket"):
        return jsonify({"error": "ticket required"}), 400

    ticket             = body.get("ticket")
    journal_trade_id   = (body.get("journal_trade_id") or "").strip()
    symbol             = body.get("symbol", "")
    direction_in       = (body.get("direction") or "").strip()
    exit_price         = float(body.get("exit_price", 0) or 0)
    pnl                = float(body.get("profit_loss", 0) or 0)
    pips               = float(body.get("pips", 0) or 0)
    duration_min       = int(body.get("duration_minutes", 0) or 0)
    close_reason       = body.get("close_reason", "Manual Close") or "Manual Close"
    actual_rr_payload  = body.get("actual_rr")
    planned_entry      = float(body.get("planned_entry", 0) or 0)
    planned_sl         = float(body.get("planned_sl", 0) or 0)
    planned_tp         = float(body.get("planned_tp", 0) or 0)

    trades_list = get_trades()

    # ─────────────────────────────────────────────────────────────────
    # TIER 1 — match by journal_trade_id (strongest link)
    # ─────────────────────────────────────────────────────────────────
    found = None
    match_tier = None
    if journal_trade_id:
        for t in trades_list:
            tid    = t.get("id")
            jourId = t.get("journalTradeId")
            if tid == journal_trade_id or jourId == journal_trade_id:
                found = t
                match_tier = "journal_trade_id"
                break

    # ─────────────────────────────────────────────────────────────────
    # TIER 2 — match by MT5 ticket
    # ─────────────────────────────────────────────────────────────────
    if not found:
        ticket_str = str(ticket)
        legacy_id  = "mt4_" + ticket_str
        for t in trades_list:
            if (
                t.get("id") == legacy_id
                or str(t.get("mt4Ticket") or "") == ticket_str
                or str(t.get("mt5Ticket") or "") == ticket_str
            ):
                found = t
                match_tier = "ticket"
                break

    # ─────────────────────────────────────────────────────────────────
    # TIER 3 — fuzzy match by symbol + approximate entry + open date
    # ─────────────────────────────────────────────────────────────────
    if not found and symbol and planned_entry > 0:
        # 0.5% tolerance on entry price; same UTC calendar day on dateOpen.
        from datetime import datetime as _dt
        tol = max(planned_entry * 0.005, 0.0001)
        today = _dt.utcnow().strftime("%Y-%m-%d")
        for t in trades_list:
            if t.get("status") == "closed":
                continue
            t_pair  = (t.get("pair") or "").upper()
            t_entry = float(t.get("entry") or 0)
            t_open  = (t.get("dateOpen") or "")[:10]
            sym_match = (t_pair == symbol.upper())
            entry_match = (t_entry > 0 and abs(t_entry - planned_entry) <= tol)
            day_match = (t_open == today or t_open == "")
            if sym_match and entry_match and day_match:
                found = t
                match_tier = "fuzzy"
                break

    now_iso = datetime.now(timezone.utc).isoformat()

    # ─────────────────────────────────────────────────────────────────
    # Compute signed actual_rr — prefer EA-supplied (already signed,
    # uses planned levels) and fall back to local re-derivation if the
    # payload didn't include it (older EA build).
    # ─────────────────────────────────────────────────────────────────
    if pnl > 0:
        outcome = "win"
    elif pnl < 0:
        outcome = "loss"
    else:
        outcome = "be"

    if actual_rr_payload is not None:
        try:
            actual_rr = float(actual_rr_payload)
        except (TypeError, ValueError):
            actual_rr = 0.0
    else:
        # Legacy fallback — derive from journal entry/sl + payload exit
        ref_entry = planned_entry or (found.get("entry", 0) if found else 0)
        ref_sl    = planned_sl    or (found.get("sl",    0) if found else 0)
        ref_dir   = direction_in or (found.get("direction", "") if found else "")
        sl_dist   = abs(ref_entry - ref_sl) if ref_sl else 0
        if ref_dir.lower() in ("long", "buy"):
            signed_profit = exit_price - ref_entry
        elif ref_dir.lower() in ("short", "sell"):
            signed_profit = ref_entry - exit_price
        else:
            signed_profit = abs(exit_price - ref_entry) * (1 if pnl > 0 else -1 if pnl < 0 else 0)
        actual_rr = 0.0 if outcome == "be" else (
            (signed_profit / sl_dist) if sl_dist > 0 else 0.0
        )

    # ─────────────────────────────────────────────────────────────────
    # Compute MT5 entry slippage in pips: actual fill - planned entry,
    # signed in trade direction (positive = better than planned).
    # ─────────────────────────────────────────────────────────────────
    entry_price_actual = float(body.get("entry_price", 0) or 0)
    direction_lower = (direction_in or (found.get("direction", "") if found else "")).lower()
    pip_size = 0.0001  # forex default
    sym_upper = (symbol or (found.get("pair", "") if found else "")).upper()
    if "JPY" in sym_upper:
        pip_size = 0.01
    if "BTC" in sym_upper or "ETH" in sym_upper or "XAU" in sym_upper:
        pip_size = 1.0
    mt5_slippage_pips = 0.0
    if planned_entry > 0 and entry_price_actual > 0:
        if direction_lower in ("long", "buy"):
            # paying *more* than planned = negative slippage
            mt5_slippage_pips = (planned_entry - entry_price_actual) / pip_size
        elif direction_lower in ("short", "sell"):
            # selling *lower* than planned = negative slippage
            mt5_slippage_pips = (entry_price_actual - planned_entry) / pip_size

    if found:
        # ─────────── HIT — update the existing journal row ────────────
        found["status"]            = "closed"
        found["exitPrice"]         = exit_price
        found["actualPnL"]         = pnl
        found["dateClose"]         = body.get("timestamp", now_iso)
        found["actualRR"]          = round(actual_rr, 2)
        found["outcome"]           = outcome
        found["updatedAt"]         = now_iso
        # MT5-supplied fields. Keep both legacy (mt4*) and new (mt5*) keys
        # populated so the frontend can rely on either.
        found["mt4CloseReason"]    = close_reason
        found["mt5CloseReason"]    = close_reason
        found["mt4Pips"]           = pips
        found["mt5Pips"]           = pips
        found["mt4Duration"]       = duration_min
        found["mt5Duration"]       = duration_min
        found["mt5Slippage"]       = round(mt5_slippage_pips, 1)
        found["mt5Ticket"]         = ticket
        found["mt5AutoClose"]      = True
        found["mt5ClosedAt"]       = now_iso
        found["mt5MatchTier"]      = match_tier
        found["reviewNeeded"]      = True
        found["source"]            = "mt5_auto_close"
        # Also persist the journal id link if we discovered it via tier 1
        if journal_trade_id and not found.get("journalTradeId"):
            found["journalTradeId"] = journal_trade_id

        save_trades(trades_list)
        outcome_emoji = "\u2705" if pnl > 0 else ("\U0001f534" if pnl < 0 else "\u2796")
        outcome_text  = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAK EVEN")
        pnl_str       = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        ref_entry_disp = found.get("entry", planned_entry)
        msg = (
            f"{outcome_emoji} <b>MT5 closed — {outcome_text}</b>\n\n"
            f"<b>{sym_upper or symbol}</b> \u2014 {direction_in or found.get('direction', '')}\n"
            f"\U0001f4cd Entry: {ref_entry_disp} \u2192 Exit: {exit_price}\n"
            f"\U0001f4b0 P&L: <b>{pnl_str}</b>\n"
            f"\U0001f4ca Actual RR: <b>{actual_rr:+.2f}R</b>\n"
            f"\u23f1 Duration: {duration_min} min\n"
            f"\U0001f4a1 Reason: {close_reason}\n"
            f"\U0001f517 Matched via: {match_tier}\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Complete your post-trade review</a>"
        )
        send_telegram(msg)
        platform_label = (found.get("platform") or found.get("source") or "mt5").upper()
        logging.info(
            "%s trade closed (tier=%s): #%s %s P&L=%s journal=%s",
            platform_label, match_tier, ticket, sym_upper, pnl_str,
            found.get("id"),
        )
        return jsonify({"ok": True, "match_tier": match_tier, "trade_id": found.get("id")})

    # ─────────────────────────────────────────────────────────────────
    # MISS — orphan auto-log. Persist the close as a fresh row so the
    # user can manually link it from the journal UI.
    # ─────────────────────────────────────────────────────────────────
    orphan_id = "mt5_orphan_" + str(ticket)
    market_guess = "BTC/USDT" if "BTC" in (sym_upper or "") else "Forex"
    orphan_dir = direction_in.lower() if direction_in else ""
    orphan = {
        "id":              orphan_id,
        "market":          market_guess,
        "pair":            sym_upper or symbol,
        "direction":       orphan_dir,
        "timeframe":       "",
        "setup":           "",
        "dateOpen":        body.get("opened_at", now_iso),
        "dateClose":       body.get("timestamp", now_iso),
        "entry":           planned_entry or entry_price_actual,
        "sl":              planned_sl,
        "tp":              planned_tp,
        "exitPrice":       exit_price,
        "actualPnL":       pnl,
        "actualRR":        round(actual_rr, 2),
        "outcome":         outcome,
        "size":            "",
        "risk":            0,
        "plannedRR":       0,
        "confidence":      0,
        "conditions":      [],
        "rationale":       "MT5 Auto-close \u2014 no matching journal entry found. Please review and link manually.",
        "preChart":        "",
        "review":          "",
        "postChart":       "",
        "rating":          0,
        "status":          "closed",
        "scRespected":     None,
        "mbmsPlayedOut":   None,
        "htfAligned":      None,
        "liqProperlyTaken": None,
        "expectedVsActual": "",
        "whatDifferently":  "",
        "lessonLearned":    "",
        "executionRating":  0,
        "source":           "mt5_auto_close",
        "platform":         "mt5",
        "mt4Ticket":        ticket,
        "mt5Ticket":        ticket,
        "mt5AutoClose":     True,
        "mt5Orphan":        True,
        "mt5ClosedAt":      now_iso,
        "mt5CloseReason":   close_reason,
        "mt4CloseReason":   close_reason,
        "mt5Pips":          pips,
        "mt4Pips":          pips,
        "mt5Duration":      duration_min,
        "mt4Duration":      duration_min,
        "mt5Slippage":      round(mt5_slippage_pips, 1),
        "journalTradeId":   journal_trade_id or None,
        "reviewNeeded":     True,
        "createdAt":        now_iso,
        "updatedAt":        now_iso,
    }
    trades_list.append(orphan)
    save_trades(trades_list)

    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    msg = (
        f"\u26a0\ufe0f <b>MT5 closed — orphan trade</b>\n\n"
        f"<b>{sym_upper or symbol}</b> \u2014 {direction_in}\n"
        f"\U0001f4cd Exit: {exit_price}\n"
        f"\U0001f4b0 P&L: <b>{pnl_str}</b>\n"
        f"\U0001f4a1 Reason: {close_reason}\n"
        f"Ticket: #{ticket}\n\n"
        f"No matching journal entry was found. The close has been auto-logged "
        f"and flagged for review.\n\n"
        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Review and link manually</a>"
    )
    send_telegram(msg)

    logging.info(
        "MT5 trade closed (orphan): #%s %s P&L=%s — auto-logged as %s",
        ticket, sym_upper or symbol, pnl_str, orphan_id,
    )
    return jsonify({"ok": True, "match_tier": "orphan", "trade_id": orphan_id, "auto_logged": True}), 201


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
# EXCHANGE INTEGRATION — Binance Private API
# ═══════════════════════════════════════════════════════

# In-memory state for exchange sync
_exchange_status = {
    "binance": {"connected": False, "last_sync": None, "error": None, "disabled": False,
                "balance_usdt": 0, "balance_btc": 0, "open_positions": 0},
    "bitunix": {"connected": False, "last_sync": None, "error": None, "disabled": False,
                "balance_usdt": 0, "available_usdt": 0, "equity_usdt": 0, "open_positions": 0,
                "open_orders": 0},
}
# Per-symbol cache so we only call set_leverage / set_margin_mode the first time
# a venue/symbol pair is used in a session
_bitunix_symbol_setup = set()
# Positions where SL has already been moved to entry (1:5 R:R)
_bitunix_be_alerted = set()
# Track already-logged trade IDs to avoid duplicates (loaded from Gist)
_logged_trade_ids = set()
# Track positions already alerted for 1:5 R:R (reset on restart)
_be_alerted_positions = set()


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


# ── Exchange Trade to Journal Entry ─────────────────────

def exchange_trade_to_journal(trade_data, source="binance"):
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


# ── Process Binance Trade History ───────────────────────

def _process_binance_trades():
    """Check Binance for new closed trades and log them."""
    if _exchange_status["binance"]["disabled"]:
        return

    try:
        trades = binance_get_trade_history("BTCUSDT", 50)
    except ConnectionError:
        _exchange_status["binance"]["error"] = "Geo-blocked"
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
            src = (t.get("source") or "").lower()
            eid = t.get("exchangeTradeId") or t.get("id", "")
            if src == "binance":
                _logged_trade_ids.add(eid)
                _logged_trade_ids.add(f"binance_{eid}")
            elif src in ("bitunix", "bitunix_auto_close"):
                _logged_trade_ids.add(eid)
                _logged_trade_ids.add(f"bitunix_{eid}")
                bo = t.get("bitunixOrderId")
                if bo:
                    _logged_trade_ids.add(f"bitunix_{bo}")
        logging.info("Loaded %d already-logged exchange trade IDs", len(_logged_trade_ids))
    except Exception as e:
        logging.warning("Failed to load logged trade IDs: %s", e)


def exchange_sync_loop():
    """Background loop: sync exchange trades and monitor positions every 60s."""
    _load_logged_trade_ids()
    while True:
        time.sleep(60)
        try:
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

            # Bitunix sync (primary crypto futures venue)
            if BITUNIX_API_KEY and not _exchange_status["bitunix"]["disabled"]:
                try:
                    bal = bitunix_get_balance()
                    _exchange_status["bitunix"]["connected"]      = True
                    _exchange_status["bitunix"]["balance_usdt"]   = bal["balance"]
                    _exchange_status["bitunix"]["available_usdt"] = bal["available"]
                    _exchange_status["bitunix"]["equity_usdt"]    = bal["equity"]
                    _exchange_status["bitunix"]["last_sync"]      = datetime.now(timezone.utc).isoformat()
                    _exchange_status["bitunix"]["error"]          = None
                    bitunix_trade_close_monitor()
                    bitunix_position_monitor()
                except ConnectionError:
                    _exchange_status["bitunix"]["disabled"]  = True
                    _exchange_status["bitunix"]["connected"] = False
                    _exchange_status["bitunix"]["error"]     = "Geo-blocked"
                    logging.warning("Bitunix geo-blocked — disabled")
                except Exception as e:
                    if "auth" in str(e).lower() or "unauthorized" in str(e).lower() or "invalid api" in str(e).lower():
                        _exchange_status["bitunix"]["disabled"]  = True
                        _exchange_status["bitunix"]["connected"] = False
                    _exchange_status["bitunix"]["error"] = str(e)
                    logging.warning("Bitunix sync error: %s", e)

            # Monitor open positions for 1:5 R:R
            _monitor_positions()

        except Exception as e:
            logging.error("Exchange sync loop error: %s", e)


# ── Exchange API Routes ─────────────────────────────────

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
# BITUNIX FUTURES — Private API (primary crypto venue)
# ═══════════════════════════════════════════════════════

# Per-venue kill switch — separate from _mt4_emergency_stop
_bitunix_emergency_stop = False

# ── Rate limiter: max 10 requests/second ────────────────
_bitunix_call_times = deque(maxlen=20)
_bitunix_lock = threading.Lock()


def _bitunix_rate_limit():
    """Block until we're under 10 requests/second to Bitunix."""
    with _bitunix_lock:
        now = time.time()
        # Drop entries older than 1s
        while _bitunix_call_times and now - _bitunix_call_times[0] > 1.0:
            _bitunix_call_times.popleft()
        if len(_bitunix_call_times) >= 10:
            sleep_for = 1.0 - (now - _bitunix_call_times[0]) + 0.01
            if sleep_for > 0:
                time.sleep(sleep_for)
        _bitunix_call_times.append(time.time())


def _bitunix_query_string(params):
    """Build the Bitunix-canonical queryParams string for signing.

    Per Bitunix docs: keys sorted ASCII, concatenated as key1value1key2value2
    with NO '=' or '&' separators. Empty params = empty string.
    """
    if not params:
        return ""
    parts = []
    for k in sorted(params.keys()):
        v = params[k]
        if v is None:
            continue
        parts.append(f"{k}{v}")
    return "".join(parts)


def _bitunix_sign(nonce, timestamp, query_string, body_string):
    """Bitunix double-SHA256 signing.

    digestInput = nonce + timestamp + apiKey + queryParams + body
    digest      = sha256_hex(digestInput)
    signInput   = digest + secretKey
    sign        = sha256_hex(signInput)
    """
    digest_input = f"{nonce}{timestamp}{BITUNIX_API_KEY}{query_string}{body_string}"
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    sign_input = f"{digest}{BITUNIX_API_SECRET}"
    return hashlib.sha256(sign_input.encode("utf-8")).hexdigest()


def _bitunix_request(method, path, params=None, body=None, signed=True):
    """Make a (signed) request to Bitunix futures API.

    Returns parsed JSON response (the full envelope: {code, msg, data}).
    Raises ConnectionError on HTTP 451/403, RuntimeError on auth failure,
    ValueError if credentials are missing.
    """
    if signed and (not BITUNIX_API_KEY or not BITUNIX_API_SECRET):
        raise ValueError("Bitunix API credentials not configured")

    _bitunix_rate_limit()

    method = method.upper()
    params = params or {}
    # Body must be JSON with all spaces removed; identical bytes signed and sent
    if body is None:
        body_string = ""
    else:
        body_string = json.dumps(body, separators=(",", ":"), sort_keys=False)

    query_string = _bitunix_query_string(params)

    headers = {"Content-Type": "application/json", "language": "en-US"}
    if signed:
        nonce = uuid.uuid4().hex
        timestamp = str(int(time.time() * 1000))
        sign = _bitunix_sign(nonce, timestamp, query_string, body_string)
        headers.update({
            "api-key":   BITUNIX_API_KEY,
            "sign":      sign,
            "nonce":     nonce,
            "timestamp": timestamp,
        })

    # Build URL — use standard urlencoded query for the wire request
    url = BITUNIX_BASE_URL + path
    if params:
        url = url + "?" + urlencode({k: v for k, v in params.items() if v is not None})

    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=15)
        else:
            r = requests.request(method, url, headers=headers, data=body_string.encode("utf-8"), timeout=15)
    except requests.RequestException as e:
        raise RuntimeError(f"Bitunix request failed: {e}") from e

    if r.status_code in (451, 403):
        raise ConnectionError("Bitunix geo-blocked or forbidden")
    r.raise_for_status()

    try:
        data = r.json()
    except ValueError as e:
        raise RuntimeError(f"Bitunix returned non-JSON: {r.text[:200]}") from e

    code = data.get("code")
    if code != 0:
        msg = data.get("msg") or data.get("message") or "Unknown error"
        # Auth-style errors → propagate so caller can disable integration
        if code in (10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008,
                    10009, 10010, 10011, 10012):
            raise RuntimeError(f"Bitunix auth error (code {code}): {msg}")
        raise RuntimeError(f"Bitunix API error (code {code}): {msg}")

    return data


# ── Bitunix Read APIs ───────────────────────────────────

def bitunix_get_balance(margin_coin="USDT"):
    """Fetch Bitunix futures account balance for the given margin coin."""
    resp = _bitunix_request("GET", "/api/v1/futures/account", params={"marginCoin": margin_coin})
    d = resp.get("data") or {}
    return {
        "margin_coin": d.get("marginCoin", margin_coin),
        "balance":     float(d.get("margin", 0) or 0) + float(d.get("available", 0) or 0),
        "available":   float(d.get("available", 0) or 0),
        "margin":      float(d.get("margin", 0) or 0),
        "equity":      float(d.get("equity", 0) or 0),
        "unrealized":  float(d.get("unrealizedPNL", d.get("unrealizedPnl", 0)) or 0),
        "raw":         d,
    }


def bitunix_get_ticker(symbol="BTCUSDT"):
    """Fetch latest ticker for a symbol — public endpoint, no signing."""
    resp = _bitunix_request("GET", "/api/v1/futures/market/tickers",
                             params={"symbols": symbol}, signed=False)
    items = resp.get("data") or []
    if not items:
        raise RuntimeError(f"Bitunix ticker: no data for {symbol}")
    t = items[0] if isinstance(items, list) else items
    return {
        "symbol":    t.get("symbol", symbol),
        "last":      float(t.get("lastPrice", t.get("last", 0)) or 0),
        "bid":       float(t.get("bidPrice", t.get("bid", 0)) or 0),
        "ask":       float(t.get("askPrice", t.get("ask", 0)) or 0),
        "high":      float(t.get("high24h", t.get("high", 0)) or 0),
        "low":       float(t.get("low24h", t.get("low", 0)) or 0),
        "volume":    float(t.get("baseVol", t.get("volume", 0)) or 0),
        "raw":       t,
    }


def bitunix_get_positions(symbol=None):
    """Fetch all currently-open Bitunix positions."""
    params = {"symbol": symbol} if symbol else None
    resp = _bitunix_request("GET", "/api/v1/futures/position/get_pending_positions", params=params)
    return resp.get("data") or []


def bitunix_get_open_orders(symbol=None):
    """Fetch all currently-pending Bitunix limit/stop orders."""
    params = {"symbol": symbol} if symbol else None
    resp = _bitunix_request("GET", "/api/v1/futures/trade/get_pending_orders", params=params)
    d = resp.get("data") or {}
    if isinstance(d, dict):
        return d.get("orderList") or d.get("list") or []
    return d or []


def bitunix_get_trade_history(symbol=None, start_time=None, end_time=None, limit=50):
    """Fetch executed trade history."""
    params = {"limit": limit}
    if symbol:
        params["symbol"] = symbol
    if start_time:
        params["startTime"] = int(start_time)
    if end_time:
        params["endTime"] = int(end_time)
    resp = _bitunix_request("GET", "/api/v1/futures/trade/get_history_trades", params=params)
    d = resp.get("data") or {}
    if isinstance(d, dict):
        return d.get("tradeList") or d.get("list") or []
    return d or []


# ── Bitunix Write APIs (orders + position management) ──

def bitunix_set_leverage(symbol, leverage, margin_coin="USDT"):
    """Set leverage for a symbol. Idempotent — safe to call repeatedly."""
    body = {"symbol": symbol, "marginCoin": margin_coin, "leverage": str(int(leverage))}
    return _bitunix_request("POST", "/api/v1/futures/account/change_leverage", body=body)


def bitunix_set_margin_mode(symbol, mode="CROSS", margin_coin="USDT"):
    """Set margin mode (CROSS or ISOLATION)."""
    mode = (mode or "CROSS").upper()
    if mode == "ISOLATED":
        mode = "ISOLATION"
    body = {"symbol": symbol, "marginCoin": margin_coin, "marginMode": mode}
    return _bitunix_request("POST", "/api/v1/futures/account/change_margin_mode", body=body)


def bitunix_ensure_symbol_setup(symbol, leverage=None, margin_mode=None):
    """First-time-per-session leverage + margin-mode setup for a symbol."""
    cache_key = f"{symbol}:{leverage}:{margin_mode}"
    if cache_key in _bitunix_symbol_setup:
        return
    lev = int(leverage or BITUNIX_DEFAULT_LEVERAGE)
    mode = (margin_mode or BITUNIX_MARGIN_MODE).upper()
    try:
        bitunix_set_margin_mode(symbol, mode)
    except Exception as e:
        logging.warning("Bitunix set_margin_mode(%s, %s) failed: %s", symbol, mode, e)
    try:
        bitunix_set_leverage(symbol, lev)
    except Exception as e:
        logging.warning("Bitunix set_leverage(%s, %d) failed: %s", symbol, lev, e)
    _bitunix_symbol_setup.add(cache_key)


def bitunix_place_order(symbol, side, qty, order_type="MARKET", price=None,
                        client_id=None, tp_price=None, sl_price=None,
                        trade_side="OPEN", reduce_only=False, effect="GTC",
                        margin_coin="USDT"):
    """Place a futures order on Bitunix.

    side       — BUY / SELL
    order_type — MARKET / LIMIT
    trade_side — OPEN / CLOSE (one-way mode uses OPEN for new + CLOSE to close)
    client_id  — passed as clientId; we use the journal_trade_id so we can
                 match closes back to the journal row later.
    tp_price/sl_price — optional take-profit / stop-loss; both use LAST_PRICE
                       trigger by default.
    """
    body = {
        "symbol":     symbol,
        "side":       side.upper(),
        "orderType":  order_type.upper(),
        "qty":        str(qty),
        "tradeSide":  trade_side.upper(),
        "reduceOnly": bool(reduce_only),
        "effect":     effect.upper(),
        "marginCoin": margin_coin,
    }
    if order_type.upper() == "LIMIT" and price is not None:
        body["price"] = str(price)
    if client_id:
        body["clientId"] = str(client_id)
    if tp_price is not None:
        body["tpPrice"] = str(tp_price)
        body["tpStopType"] = "LAST_PRICE"
    if sl_price is not None:
        body["slPrice"] = str(sl_price)
        body["slStopType"] = "LAST_PRICE"

    return _bitunix_request("POST", "/api/v1/futures/trade/place_order", body=body)


def bitunix_cancel_order(symbol, order_id=None, client_id=None):
    """Cancel a pending order by orderId or clientId."""
    if not order_id and not client_id:
        raise ValueError("Must provide order_id or client_id")
    order_entry = {}
    if order_id:
        order_entry["orderId"] = str(order_id)
    if client_id:
        order_entry["clientId"] = str(client_id)
    body = {"symbol": symbol, "orderList": [order_entry]}
    return _bitunix_request("POST", "/api/v1/futures/trade/cancel_orders", body=body)


def bitunix_modify_position_sl(symbol, position_id, new_sl, new_tp=None):
    """Modify a position's stop-loss (and optionally take-profit)."""
    body = {
        "symbol":     symbol,
        "positionId": str(position_id),
        "slPrice":    str(new_sl),
        "slStopType": "LAST_PRICE",
    }
    if new_tp is not None:
        body["tpPrice"] = str(new_tp)
        body["tpStopType"] = "LAST_PRICE"
    return _bitunix_request("POST", "/api/v1/futures/tpsl/modify_position_tp_sl", body=body)


# ── Bitunix Price Source (for get_price chain) ─────────

def _price_bitunix(symbol):
    """PRIMARY price source — Bitunix public ticker."""
    t = bitunix_get_ticker(symbol)
    px = t.get("last") or 0
    if not px or px <= 0:
        raise RuntimeError(f"Bitunix returned invalid price for {symbol}: {px}")
    return float(px)


# ── Bitunix Position Monitor (1:5 R:R Break Even) ──────

def bitunix_position_monitor():
    """Auto-move SL to entry once a Bitunix position reaches 1:5 R:R."""
    if _exchange_status["bitunix"]["disabled"] or not BITUNIX_API_KEY:
        return
    try:
        positions = bitunix_get_positions()
    except ConnectionError:
        return
    except Exception as e:
        logging.warning("Bitunix position monitor — fetch failed: %s", e)
        return

    _exchange_status["bitunix"]["open_positions"] = len(positions)

    for p in positions:
        try:
            pos_id  = str(p.get("positionId", ""))
            symbol  = p.get("symbol", "")
            side    = (p.get("side") or "").upper()  # BUY (long) or SELL (short)
            entry   = float(p.get("avgOpenPrice", p.get("entryValue", 0)) or 0)
            sl_price = float(p.get("slPrice", 0) or 0) if p.get("slPrice") else 0
            mark     = float(p.get("markPrice", p.get("lastPrice", 0)) or 0)
            client_id = p.get("clientId") or ""

            if not pos_id or not entry or not mark or not sl_price:
                continue
            if pos_id in _bitunix_be_alerted:
                continue

            # R-distance = entry - SL (long) or SL - entry (short)
            if side == "BUY":
                r_dist = entry - sl_price
                progress = (mark - entry)
            else:
                r_dist = sl_price - entry
                progress = (entry - mark)
            if r_dist <= 0:
                continue

            rr = progress / r_dist
            if rr < 5.0:
                continue

            # Already at 1:5 R:R — move SL to entry
            try:
                bitunix_modify_position_sl(symbol, pos_id, entry)
                _bitunix_be_alerted.add(pos_id)
            except Exception as e:
                logging.warning("Bitunix BE modify failed for %s: %s", pos_id, e)
                continue

            # Patch the journal row if we can match by clientId/journal_trade_id
            try:
                if client_id:
                    trades_list = get_trades()
                    for t in trades_list:
                        if t.get("id") == client_id or t.get("journalTradeId") == client_id:
                            t["breakEvenSet"]   = True
                            t["bitunixBEAt"]    = datetime.now(timezone.utc).isoformat()
                            t["updatedAt"]      = t["bitunixBEAt"]
                            break
                    save_trades(trades_list)
            except Exception as e:
                logging.warning("Bitunix BE journal patch failed: %s", e)

            msg = (
                f"\U0001f512 <b>Break even set on Bitunix!</b>\n\n"
                f"<b>{symbol}</b> {side} reached 1:5 R:R\n"
                f"\U0001f4cd Entry: {entry}\n"
                f"\U0001f4ca Mark: {mark} (R = {rr:.2f})\n"
                f"SL moved to entry — risk eliminated \u2705\n\n"
                f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
            )
            send_telegram(msg)
            logging.info("Bitunix BE set on position %s %s @ entry=%s mark=%s", pos_id, symbol, entry, mark)
        except Exception as e:
            logging.warning("Bitunix position monitor — per-position error: %s", e)


# ── Bitunix Trade Close Monitor (3-tier match) ─────────

def _bitunix_match_journal_row(trades_list, trade):
    """Return (row, tier) for a Bitunix close, mirroring the MT5 3-tier match.

    Tier 1: by clientId / journal_trade_id
    Tier 2: by exchange orderId / id
    Tier 3: fuzzy — same symbol, same UTC date, entry within 0.5%
    """
    client_id = str(trade.get("clientId") or "")
    order_id  = str(trade.get("orderId") or trade.get("id") or "")
    symbol    = trade.get("symbol", "")
    entry     = float(trade.get("avgPrice", trade.get("price", 0)) or 0)

    # TIER 1 — clientId / journal_trade_id
    if client_id:
        for t in trades_list:
            if t.get("id") == client_id or t.get("journalTradeId") == client_id:
                return t, "client_id"

    # TIER 2 — orderId
    if order_id:
        legacy_id = f"bitunix_{order_id}"
        for t in trades_list:
            if (t.get("id") == legacy_id
                or str(t.get("bitunixOrderId") or "") == order_id
                or str(t.get("exchangeTradeId") or "") == order_id):
                return t, "order_id"

    # TIER 3 — fuzzy
    if symbol and entry:
        ctime_ms = trade.get("ctime") or trade.get("createTime") or trade.get("time")
        try:
            close_dt = datetime.fromtimestamp(int(ctime_ms) / 1000, tz=timezone.utc) if ctime_ms else None
        except (ValueError, TypeError):
            close_dt = None
        for t in trades_list:
            if t.get("status") != "open":
                continue
            if (t.get("pair") or t.get("symbol") or "").upper() != symbol.upper():
                continue
            t_entry = float(t.get("entry") or 0)
            if not t_entry:
                continue
            if abs(t_entry - entry) / entry > 0.005:
                continue
            if close_dt:
                t_open = t.get("dateOpen", "")
                try:
                    o_dt = datetime.fromisoformat(t_open.replace("Z", "+00:00"))
                    if o_dt.tzinfo is None:
                        o_dt = o_dt.replace(tzinfo=timezone.utc)
                    if o_dt.date() != close_dt.date():
                        continue
                except (ValueError, AttributeError):
                    continue
            return t, "fuzzy"
    return None, None


def bitunix_trade_close_monitor():
    """Pick up newly-closed Bitunix trades and reconcile them with journal rows."""
    if _exchange_status["bitunix"]["disabled"] or not BITUNIX_API_KEY:
        return

    try:
        # Look back ~1h to catch anything missed during a brief outage
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - 60 * 60 * 1000
        history = bitunix_get_trade_history(start_time=start_ms, end_time=end_ms, limit=50)
    except ConnectionError:
        _exchange_status["bitunix"]["disabled"] = True
        _exchange_status["bitunix"]["error"] = "Geo-blocked"
        return
    except Exception as e:
        if "auth" in str(e).lower() or "unauthorized" in str(e).lower() or "invalid api" in str(e).lower():
            _exchange_status["bitunix"]["disabled"] = True
            _exchange_status["bitunix"]["error"] = f"Auth error: {e}"
            logging.error("Bitunix auth error — disabling: %s", e)
            return
        logging.warning("Bitunix history fetch failed: %s", e)
        return

    if not history:
        return

    trades_list = get_trades()
    new_count = 0

    for t in history:
        # Only consider closing fills (reduceOnly / tradeSide=CLOSE / position closed)
        trade_side = (t.get("tradeSide") or t.get("positionSide") or "").upper()
        reduce_only = bool(t.get("reduceOnly") or False)
        is_close = reduce_only or trade_side in ("CLOSE", "CLOSE_LONG", "CLOSE_SHORT")
        if not is_close:
            continue

        order_id = str(t.get("orderId") or t.get("tradeId") or t.get("id") or "")
        if not order_id:
            continue
        dedupe_key = f"bitunix_{order_id}"
        if dedupe_key in _logged_trade_ids:
            continue

        client_id = str(t.get("clientId") or "")
        symbol    = t.get("symbol", "")
        side_raw  = (t.get("side") or t.get("positionSide") or "").upper()
        # On Bitunix the closing side is opposite of the position direction
        # — convert back to the original direction
        if "LONG" in trade_side or side_raw == "SELL":
            direction = "long"
        elif "SHORT" in trade_side or side_raw == "BUY":
            direction = "short"
        else:
            direction = (t.get("originalSide") or "").lower() or ""

        exit_price = float(t.get("avgPrice", t.get("price", 0)) or 0)
        pnl        = float(t.get("realizedPNL", t.get("realizedPnl", 0)) or 0)
        ctime_ms   = t.get("ctime") or t.get("createTime") or t.get("time") or int(time.time() * 1000)
        try:
            close_iso = datetime.fromtimestamp(int(ctime_ms) / 1000, tz=timezone.utc).isoformat()
        except (ValueError, TypeError):
            close_iso = datetime.now(timezone.utc).isoformat()

        # 3-tier match
        normalised = {
            "clientId": client_id, "orderId": order_id, "symbol": symbol,
            "avgPrice": exit_price, "ctime": ctime_ms,
        }
        found, tier = _bitunix_match_journal_row(trades_list, normalised)

        if found:
            entry_price = float(found.get("entry") or 0)
            risk = float(found.get("risk") or 0)
            sl_price = float(found.get("sl") or 0)
            r_dist = abs(entry_price - sl_price) if sl_price else 0
            actual_rr = (abs(exit_price - entry_price) / r_dist) if r_dist else 0
            if direction == "short":
                actual_rr = -actual_rr if exit_price > entry_price else actual_rr
            else:
                actual_rr = -actual_rr if exit_price < entry_price else actual_rr

            outcome = "win" if pnl > 0 else ("loss" if pnl < 0 else "be")

            found["status"]          = "closed"
            found["exitPrice"]       = exit_price
            found["actualPnL"]       = pnl
            found["dateClose"]       = close_iso
            found["actualRR"]        = actual_rr
            found["outcome"]         = outcome
            found["bitunixOrderId"]  = order_id
            found["bitunixAutoClose"]= True
            found["bitunixMatchTier"]= tier
            found["reviewNeeded"]    = True
            found["source"]          = "bitunix_auto_close"
            found["updatedAt"]       = datetime.now(timezone.utc).isoformat()
        else:
            # Persist as a fresh auto-logged row
            trade_data = {
                "trade_id":    order_id,
                "symbol":      symbol,
                "direction":   direction or "long",
                "entry_price": exit_price,
                "exit_price":  exit_price,
                "volume":      float(t.get("qty", 0) or 0),
                "pnl":         pnl,
                "open_time":   close_iso,
                "close_time":  close_iso,
            }
            row = exchange_trade_to_journal(trade_data, source="bitunix")
            row["bitunixOrderId"]   = order_id
            row["bitunixAutoClose"] = True
            row["bitunixMatchTier"] = "no_match"
            row["reviewNeeded"]     = True
            trades_list.append(row)

        _logged_trade_ids.add(dedupe_key)
        new_count += 1

        outcome_str = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BE")
        msg = (
            f"\U0001f4ca <b>Trade closed on Bitunix!</b>  [{outcome_str}]\n\n"
            f"<b>{symbol}</b> {direction.upper() if direction else ''}\n"
            f"\U0001f4cd Exit: <b>{exit_price}</b>\n"
            f"\U0001f4b0 P&amp;L: <b>${pnl:.2f}</b>\n"
            f"Match: <code>{tier or 'no_match'}</code>\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Review in journal</a>"
        )
        send_telegram(msg)
        logging.info("Bitunix close logged: %s %s exit=%s pnl=%s match=%s",
                     order_id, symbol, exit_price, pnl, tier or "no_match")

    if new_count > 0:
        try:
            save_trades(trades_list)
        except Exception as e:
            logging.error("Bitunix close monitor — Gist save failed: %s", e)
        logging.info("Auto-logged %d new Bitunix close(s)", new_count)


# ── Bitunix Flask Routes ───────────────────────────────

@app.route("/bitunix/exchange/status", methods=["GET"])
def bitunix_exchange_status():
    """GET /bitunix/exchange/status — connection state for Bitunix only."""
    return jsonify(_exchange_status.get("bitunix", {}))


@app.route("/bitunix/account", methods=["GET"])
def bitunix_account():
    """GET /bitunix/account — balance + open position/order counts."""
    if not BITUNIX_API_KEY:
        return jsonify({"error": "Bitunix API not configured"}), 400
    if _exchange_status["bitunix"]["disabled"]:
        return jsonify({"error": _exchange_status["bitunix"]["error"], "disabled": True}), 403
    try:
        balance = bitunix_get_balance()
        positions = bitunix_get_positions()
        orders = bitunix_get_open_orders()
        return jsonify({
            "connected":      True,
            "balance_usdt":   balance["balance"],
            "available_usdt": balance["available"],
            "equity_usdt":    balance["equity"],
            "open_positions": len(positions),
            "open_orders":    len(orders),
            "leverage":       BITUNIX_DEFAULT_LEVERAGE,
            "margin_mode":    BITUNIX_MARGIN_MODE,
            "last_sync":      datetime.now(timezone.utc).isoformat(),
        })
    except ConnectionError:
        _exchange_status["bitunix"]["disabled"] = True
        return jsonify({"error": "Bitunix geo-blocked"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bitunix/ticker/<symbol>", methods=["GET"])
def bitunix_ticker_route(symbol):
    """GET /bitunix/ticker/<symbol> — public market ticker."""
    try:
        t = bitunix_get_ticker(symbol.upper())
        # Strip the raw payload for cleaner responses
        t.pop("raw", None)
        return jsonify(t)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bitunix/positions", methods=["GET"])
def bitunix_positions_route():
    """GET /bitunix/positions — currently open Bitunix futures positions."""
    if not BITUNIX_API_KEY:
        return jsonify({"error": "Bitunix API not configured"}), 400
    if _exchange_status["bitunix"]["disabled"]:
        return jsonify({"error": _exchange_status["bitunix"]["error"], "disabled": True}), 403
    try:
        return jsonify(bitunix_get_positions())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bitunix/orders/pending", methods=["GET"])
def bitunix_orders_pending_route():
    """GET /bitunix/orders/pending — open limit/stop orders on Bitunix."""
    if not BITUNIX_API_KEY:
        return jsonify({"error": "Bitunix API not configured"}), 400
    if _exchange_status["bitunix"]["disabled"]:
        return jsonify({"error": _exchange_status["bitunix"]["error"], "disabled": True}), 403
    try:
        return jsonify(bitunix_get_open_orders())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bitunix/trade/execute", methods=["POST"])
def bitunix_trade_execute():
    """POST /bitunix/trade/execute — place a futures order on Bitunix.

    Same risk engine as /api/trade/approve. Differs in that it also
    sizes the position (qty = risk_amount / |entry-sl|) and calls Bitunix
    directly. Returns trade_id + order_id.
    """
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    if _bitunix_emergency_stop:
        return jsonify({"error": "Bitunix emergency stop active"}), 403
    if not BITUNIX_API_KEY:
        return jsonify({"error": "Bitunix API not configured"}), 400
    if _exchange_status["bitunix"]["disabled"]:
        return jsonify({"error": _exchange_status["bitunix"]["error"], "disabled": True}), 403

    body = request.json or {}
    required = ["symbol", "direction", "entry", "sl", "tp"]
    for f in required:
        if f not in body:
            return jsonify({"error": f"Missing required field: {f}"}), 400

    symbol     = body["symbol"].upper()
    direction  = body["direction"].upper()
    entry      = float(body["entry"])
    sl         = float(body["sl"])
    tp         = float(body["tp"])
    risk_pct   = float(body.get("risk_percent", 1.0))
    leverage   = int(body.get("leverage", BITUNIX_DEFAULT_LEVERAGE))
    margin_mode = (body.get("margin_mode") or BITUNIX_MARGIN_MODE).upper()
    order_type  = (body.get("order_type") or "MARKET").upper()
    journal_id  = body.get("journal_trade_id", "")

    # Build trade dict + run risk engine
    trade = {
        "id":               str(uuid.uuid4())[:12],
        "symbol":           symbol,
        "direction":        direction,
        "entry":            entry,
        "sl":               sl,
        "tp":               tp,
        "risk_percent":     risk_pct,
        "be_trigger_rr":    float(body.get("be_trigger_rr", 1.5)),
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "source":           "journal",
        "journal_trade_id": journal_id,
        "venue":            "bitunix",
        "leverage":         leverage,
        "margin_mode":      margin_mode,
        "confidence":       body.get("confidence", 0),
        "dxy_confirms":     body.get("dxy_confirms", ""),
        "entry_confirmation": body.get("entry_confirmation", ""),
        "risk_limits":      body.get("risk_limits", {}),
        "status":           "pending",
        "paper":            PAPER_TRADING_MODE,
    }
    account_state = body.get("account_state") or _get_account_state_from_gist()
    result = validate_trade(trade, account_state)

    if not result["approved"]:
        trade["status"] = "rejected"
        trade["reject_reason"] = result["reason"]
        _execution_queue.append(trade)
        _log_execution_event(
            trade_id=trade["id"], symbol=symbol, direction=direction,
            planned_entry=entry, status="rejected",
            paper=trade.get("paper", False), reason=result["reason"],
        )
        return jsonify({
            "approved": False, "reason": result["reason"],
            "warnings": result["warnings"], "trade_id": trade["id"],
        }), 200

    # Futures position sizing — qty in BASE units (BTC, ETH, …)
    capital = float(account_state.get("capital", 0) or 0)
    risk_amount = capital * (risk_pct / 100.0) if capital else 0
    price_dist = abs(entry - sl)
    if price_dist <= 0:
        return jsonify({"error": "Invalid SL — zero distance from entry"}), 400
    if risk_amount <= 0:
        return jsonify({"error": "Cannot size position — capital not available in account state"}), 400

    qty = round(risk_amount / price_dist, 4)
    notional = qty * entry
    required_margin = notional / max(leverage, 1)

    trade["lot_size"]        = qty
    trade["notional"]        = notional
    trade["required_margin"] = required_margin
    trade["warnings"]        = result["warnings"]
    trade["status"]          = "approved"
    _execution_queue.append(trade)

    if PAPER_TRADING_MODE:
        # Paper-trading: skip the live order, mark queue as paper_executed
        trade["status"]      = "paper_executed"
        trade["executed_at"] = datetime.now(timezone.utc).isoformat()
        _log_execution_event(
            trade_id=trade["id"], symbol=symbol, direction=direction,
            planned_entry=entry, actual_entry=entry, status="paper_executed",
            paper=True, reason="Bitunix paper mode",
        )
        msg = (
            f"\U0001f4c4 <b>PAPER TRADE on Bitunix (demo)</b>\n\n"
            f"<b>{symbol}</b> {direction}\n"
            f"\U0001f4cd Entry: {entry} | SL: {sl} | TP: {tp}\n"
            f"\U0001f4e6 Qty: {qty} (notional ${notional:.2f}, margin ${required_margin:.2f})\n"
            f"Lev {leverage}x \u00b7 {margin_mode}\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
        )
        send_telegram(msg)
        return jsonify({
            "approved": True, "paper": True,
            "trade_id": trade["id"], "order_id": None,
            "qty": qty, "required_margin": required_margin,
            "warnings": result["warnings"],
        }), 200

    # Live execution: ensure leverage + margin mode, then place order
    side = "BUY" if direction == "BUY" else "SELL"
    try:
        bitunix_ensure_symbol_setup(symbol, leverage=leverage, margin_mode=margin_mode)
    except Exception as e:
        logging.warning("Bitunix setup pre-order failed: %s", e)

    try:
        place_resp = bitunix_place_order(
            symbol=symbol, side=side, qty=qty,
            order_type=order_type,
            price=(entry if order_type == "LIMIT" else None),
            client_id=(journal_id or trade["id"]),
            tp_price=tp, sl_price=sl,
        )
    except ConnectionError:
        _exchange_status["bitunix"]["disabled"] = True
        return jsonify({"error": "Bitunix geo-blocked"}), 403
    except Exception as e:
        trade["status"] = "execution_failed"
        trade["error"] = str(e)
        _log_execution_event(
            trade_id=trade["id"], symbol=symbol, direction=direction,
            planned_entry=entry, status="execution_failed",
            reason=str(e),
        )
        return jsonify({"approved": True, "error": str(e), "trade_id": trade["id"]}), 502

    order_data = (place_resp or {}).get("data") or {}
    order_id = str(order_data.get("orderId") or order_data.get("id") or "")
    trade["status"]      = "executed"
    trade["actual_entry"] = entry
    trade["executed_at"] = datetime.now(timezone.utc).isoformat()
    trade["bitunixOrderId"] = order_id

    _log_execution_event(
        trade_id=trade["id"], symbol=symbol, direction=direction,
        planned_entry=entry, actual_entry=entry, status="executed",
        reason="Bitunix order placed", mt4_ticket=order_id,
    )

    # Mirror executed status onto the journal row, if linked
    if journal_id:
        try:
            trades_list = get_trades()
            for t in trades_list:
                if t.get("id") == journal_id:
                    t["status"]          = "open"
                    t["source"]          = "bitunix"
                    t["platform"]        = "bitunix"
                    t["bitunixOrderId"]  = order_id
                    t["bitunixLeverage"] = leverage
                    t["bitunixMargin"]   = margin_mode
                    t["execStatus"]      = "executed"
                    t["execActualEntry"] = entry
                    t["execExecutedAt"]  = trade["executed_at"]
                    t["updatedAt"]       = trade["executed_at"]
                    break
            save_trades(trades_list)
        except Exception as e:
            logging.error("Bitunix execute — journal patch failed: %s", e)

    msg = (
        f"\U0001f680 <b>Bitunix order placed!</b>\n\n"
        f"<b>{symbol}</b> {direction} \u00b7 Lev {leverage}x \u00b7 {margin_mode}\n"
        f"\U0001f4cd Entry: {entry} | SL: {sl} | TP: {tp}\n"
        f"\U0001f4e6 Qty: {qty} (notional ${notional:.2f}, margin ${required_margin:.2f})\n"
        f"Order: <code>{order_id}</code>\n\n"
        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
    )
    send_telegram(msg)
    logging.info("Bitunix order placed: %s %s qty=%s order_id=%s", symbol, direction, qty, order_id)

    return jsonify({
        "approved": True, "paper": False,
        "trade_id": trade["id"], "order_id": order_id,
        "qty": qty, "notional": notional, "required_margin": required_margin,
        "warnings": result["warnings"],
    }), 201


@app.route("/bitunix/trade/cancel", methods=["POST"])
def bitunix_trade_cancel():
    """POST /bitunix/trade/cancel — cancel a pending Bitunix order."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err
    if not BITUNIX_API_KEY:
        return jsonify({"error": "Bitunix API not configured"}), 400

    body = request.json or {}
    symbol = (body.get("symbol") or "").upper()
    order_id = body.get("order_id")
    client_id = body.get("client_id") or body.get("journal_trade_id")
    if not symbol or (not order_id and not client_id):
        return jsonify({"error": "symbol and (order_id or client_id) required"}), 400
    try:
        resp = bitunix_cancel_order(symbol, order_id=order_id, client_id=client_id)
        return jsonify({"ok": True, "result": resp.get("data")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bitunix/emergency-stop", methods=["GET"])
def bitunix_emergency_stop_get():
    """GET /api/bitunix/emergency-stop — current Bitunix kill-switch state."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err
    return jsonify({
        "venue":      "bitunix",
        "emergency":  _bitunix_emergency_stop,
        "active":     _bitunix_emergency_stop,
        "message":    ("Bitunix execution paused — kill switch active"
                        if _bitunix_emergency_stop else "All clear — Bitunix executions enabled"),
    })


@app.route("/api/bitunix/emergency-stop", methods=["POST"])
def bitunix_emergency_stop_post():
    """POST /api/bitunix/emergency-stop — set Bitunix kill switch."""
    global _bitunix_emergency_stop
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err
    body = request.json or {}
    activate = bool(body.get("emergency", False))
    _bitunix_emergency_stop = activate
    if activate:
        send_telegram(
            "\U0001f6a8 <b>Bitunix EMERGENCY STOP active!</b>\n\n"
            "All new Bitunix executions blocked. "
            "MT5 routing remains independent — flip its own kill switch separately if needed."
        )
        logging.warning("Bitunix kill switch ACTIVATED via API")
    else:
        send_telegram("\u2705 <b>Bitunix kill switch cleared</b> — executions resumed.")
        logging.info("Bitunix kill switch deactivated via API")
    return jsonify({"ok": True, "venue": "bitunix", "emergency": _bitunix_emergency_stop})


@app.route("/api/bitunix/emergency-stop", methods=["DELETE"])
def bitunix_emergency_stop_clear():
    """DELETE /api/bitunix/emergency-stop — clear the Bitunix kill switch."""
    global _bitunix_emergency_stop
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err
    _bitunix_emergency_stop = False
    return jsonify({"ok": True, "venue": "bitunix", "emergency": False})


# ═══════════════════════════════════════════════════════
# TRADE EXECUTION PIPELINE
# ═══════════════════════════════════════════════════════

# In-memory execution queue (persists across requests, lost on restart)
# Each entry: { id, symbol, direction, entry, sl, tp, risk_percent, lot_size,
#               be_trigger_rr, timestamp, source, journal_trade_id, status,
#               warnings, actual_entry, executed_at }
_execution_queue = []

# Pending limit orders — populated by /api/trade/limit-placed, cleared on fill/expiry
# Each entry: { id, symbol, direction, entry, sl, tp, order_ticket,
#               placed_at, expires_at, status, paper }
_pending_limit_orders = []

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
    """POST /api/trade/cancelled — Cancel a pending trade or log a limit order expiry."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body = request.json
    if not body or not body.get("id"):
        return jsonify({"error": "Trade id required"}), 400

    trade_id = body["id"]
    raw_reason = body.get("reason", "Manual cancel")
    is_limit_expired   = raw_reason == "limit_order_expired"
    is_limit_cancelled = raw_reason == "limit_order_cancelled"
    is_limit_event     = is_limit_expired or is_limit_cancelled

    # --- Update pending limit orders list ---
    if is_limit_event:
        new_status = "limit_order_expired" if is_limit_expired else "limit_order_cancelled"
        for lo in _pending_limit_orders:
            if lo["id"] == trade_id:
                lo["status"] = new_status
                lo["ended_at"] = datetime.now(timezone.utc).isoformat()
                break

    # --- Update execution queue if entry exists ---
    found = None
    for t in _execution_queue:
        if t["id"] == trade_id:
            found = t
            break

    if found:
        found["status"] = new_status if is_limit_event else "cancelled"
        found["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    # Limit events may arrive without a queue entry when the order was placed
    # before a backend restart — that's fine, we still log and notify.

    log_status = new_status if is_limit_event else "cancelled"
    symbol    = (found["symbol"]    if found else body.get("symbol",    ""))
    direction = (found["direction"] if found else body.get("direction", ""))
    entry     = (found["entry"]     if found else body.get("entry",     0))
    sl        = (found.get("sl")    if found else 0)
    tp        = (found.get("tp")    if found else 0)

    _log_execution_event(
        trade_id=trade_id, symbol=symbol, direction=direction,
        planned_entry=entry, status=log_status,
        paper=(found.get("paper", False) if found else False),
        test=(found.get("test_only", False) if found else False),
        reason=raw_reason,
    )

    # --- Telegram ---
    if is_limit_expired:
        expires_at = body.get("expires_at", "")
        msg = (
            f"\u23f0 <b>Limit order EXPIRED</b>\n\n"
            f"<b>{symbol}</b> {direction}\n"
            f"Price never reached <b>{entry}</b>\n"
            f"Order cancelled after {body.get('expiry_hours', 24)}h\n"
            f"(Expires: {expires_at})\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
        )
        logging.info("Limit order expired: %s %s @ %s", trade_id, symbol, entry)
    elif is_limit_cancelled:
        msg = (
            f"\u274c <b>Limit order cancelled</b>\n\n"
            f"<b>{symbol}</b> {direction}\n"
            f"Limit at: {entry} was cancelled manually\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
        )
        logging.info("Limit order cancelled: %s %s @ %s", trade_id, symbol, entry)
    else:
        msg = (
            f"\u274c <b>Trade cancelled</b>\n\n"
            f"<b>{symbol}</b> {direction}\n"
            f"Entry: {entry} | SL: {sl} | TP: {tp}\n\n"
            f"\U0001f4dd <a href=\"{JOURNAL_URL}\">Open journal</a>"
        )
        logging.info("Trade cancelled: %s %s", trade_id, symbol)

    send_telegram(msg)
    return jsonify({"ok": True})


@app.route("/api/trade/limit-placed", methods=["POST"])
def trade_limit_placed():
    """POST /api/trade/limit-placed — Called by EA when BuyLimit/SellLimit is placed."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    body = request.json
    if not body or not body.get("id"):
        return jsonify({"error": "id required"}), 400

    trade_id = body["id"]

    # Find in execution queue to get full trade context
    found = None
    for t in _execution_queue:
        if t["id"] == trade_id:
            found = t
            break

    symbol    = body.get("symbol",    found["symbol"]    if found else "")
    direction = body.get("direction", found["direction"] if found else "")
    entry     = float(body.get("entry",   found["entry"] if found else 0))
    sl        = float(body.get("sl",      found.get("sl", 0) if found else 0))
    tp        = float(body.get("tp",      found.get("tp", 0) if found else 0))
    expires_at = body.get("expires_at", "")
    order_ticket = body.get("order_ticket")

    if found:
        found["status"] = "limit_placed"
        found["limit_order_ticket"] = order_ticket
        found["limit_placed_at"] = datetime.now(timezone.utc).isoformat()
        found["limit_expires_at"] = expires_at

    # Register in pending limit orders list (avoid duplicates)
    if not any(lo["id"] == trade_id for lo in _pending_limit_orders):
        _pending_limit_orders.append({
            "id":           trade_id,
            "symbol":       symbol,
            "direction":    direction,
            "entry":        entry,
            "sl":           sl,
            "tp":           tp,
            "order_ticket": order_ticket,
            "placed_at":    datetime.now(timezone.utc).isoformat(),
            "expires_at":   expires_at,
            "status":       "limit_placed",
            "paper":        found.get("paper", PAPER_TRADING_MODE) if found else PAPER_TRADING_MODE,
        })

    _log_execution_event(
        trade_id=trade_id, symbol=symbol, direction=direction,
        planned_entry=entry, status="limit_order_placed",
        paper=(found.get("paper", False) if found else False),
        reason="Limit order placed on MT5 at " + str(entry),
    )

    msg = (
        f"\u23f3 <b>Limit order placed!</b>\n\n"
        f"<b>{symbol}</b> {direction}\n"
        f"Waiting for price: <b>{entry}</b>\n"
        f"\U0001f6d1 SL: {sl} | \U0001f3af TP: {tp}\n"
        f"Expires in 24h\n"
        f"(Ticket #{order_ticket})\n\n"
        f"\U0001f4dd <a href=\"{JOURNAL_URL}\">View in journal</a>"
    )
    send_telegram(msg)

    logging.info("Limit order placed: %s %s %s @ %s", trade_id, symbol, direction, entry)
    return jsonify({"ok": True})


@app.route("/api/pending-orders", methods=["GET"])
def pending_orders():
    """GET /api/pending-orders — Return all active (unfilled) limit orders."""
    auth_err = _require_execution_key()
    if auth_err:
        return auth_err

    active = [o for o in _pending_limit_orders if o.get("status") == "limit_placed"]
    now = datetime.now(timezone.utc)

    result = []
    for o in active:
        placed_str  = o.get("placed_at", "")
        expires_str = o.get("expires_at", "")

        hours_placed  = 0
        hours_expires = 24
        try:
            placed_dt = datetime.fromisoformat(placed_str.replace("Z", "+00:00"))
            hours_placed = round((now - placed_dt).total_seconds() / 3600, 1)
        except Exception:
            pass
        try:
            exp_dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            secs_left = (exp_dt - now).total_seconds()
            hours_expires = max(0, round(secs_left / 3600, 1))
        except Exception:
            pass

        result.append({
            "id":            o["id"],
            "symbol":        o["symbol"],
            "direction":     o["direction"],
            "entry":         o["entry"],
            "sl":            o.get("sl"),
            "tp":            o.get("tp"),
            "order_ticket":  o.get("order_ticket"),
            "placed_at":     placed_str,
            "expires_at":    expires_str,
            "hours_placed":  hours_placed,
            "hours_left":    hours_expires,
            "status":        o["status"],
            "paper":         o.get("paper", False),
        })

    return jsonify({"orders": result, "total": len(result)})


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
            entries = [e for e in entries if e["status"] in (
                "executed", "paper_executed", "test_passed", "limit_order_filled")]
        elif status_filter == "failed":
            entries = [e for e in entries if e["status"] in (
                "execution_failed", "test_failed", "rejected")]
        elif status_filter == "paper":
            entries = [e for e in entries if e.get("paper")]
        elif status_filter == "limit":
            entries = [e for e in entries if e["status"] in (
                "limit_order_placed", "limit_order_filled",
                "limit_order_expired", "limit_order_cancelled")]
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
    symbol    = (body.get("symbol") or "EURUSD").upper()
    direction = (body.get("direction") or "BUY").upper()

    # Generate realistic levels relative to the current market price so MT5
    # doesn't reject the order with retcode 10016 (invalid stops). Falls back
    # to sane defaults if the live-price source is unreachable.
    entry_live, sl_live, tp_live, lot_live = _test_trade_levels(symbol, direction)

    # Explicit overrides from the request body still win (useful for targeted
    # regression tests where the caller wants specific numbers).
    entry = float(body.get("entry", entry_live))
    sl    = float(body.get("sl",    sl_live))
    tp    = float(body.get("tp",    tp_live))
    lot   = float(body.get("lot_size", body.get("lot", lot_live)))

    test_trade = {
        "id":               "test-" + str(uuid.uuid4())[:8],
        "symbol":           symbol,
        "direction":        direction,
        "entry":            entry,
        "sl":               sl,
        "tp":               tp,
        "risk_percent":     0.1,
        "lot_size":         lot,
        "be_trigger_rr":    1.5,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "source":           "execution_test",
        "journal_trade_id": "pipeline-test",
        "status":           "approved",
        "warnings":         ["TEST TRADE — will not be executed on broker"],
        "paper":            True,
        "test":             True,   # new explicit flag
        "test_only":        True,   # legacy flag — EA reads this one
    }
    _execution_queue.append(test_trade)

    _log_execution_event(
        trade_id=test_trade["id"], symbol=test_trade["symbol"], direction=test_trade["direction"],
        planned_entry=test_trade["entry"], status="approved",
        paper=True, test=True,
        reason=f"Synthetic test trade — live levels (entry={entry}, sl={sl}, tp={tp})",
    )

    return jsonify({
        "ok":       True,
        "trade_id": test_trade["id"],
        "message":  "Test trade queued with live market levels. EA will fetch within 5s.",
        "trade":    test_trade,
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
    if BINANCE_API_KEY:
        threading.Thread(target=exchange_sync_loop, daemon=True).start()
        logging.info("Exchange sync started — Binance: enabled")
    threading.Thread(target=daily_summary_loop, daemon=True).start()


if __name__ == "__main__":
    _start_background_threads()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
else:
    # When run via gunicorn, also start background threads
    _start_background_threads()
