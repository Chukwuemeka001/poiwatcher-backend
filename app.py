"""
Trading Alert Backend — Flask server for price monitoring, Telegram alerts,
and AI level suggestions using Emeka's BTCUSDT Trading System framework.

Deployed on Render free tier. All secrets via environment variables.
"""

import os
import json
import time
import uuid
import threading
import logging
from datetime import datetime, timezone

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


# ── Start ───────────────────────────────────────────────

if __name__ == "__main__":
    # Start background price monitor
    monitor = threading.Thread(target=price_monitor_loop, daemon=True)
    monitor.start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
else:
    # When run via gunicorn, also start the monitor
    monitor = threading.Thread(target=price_monitor_loop, daemon=True)
    monitor.start()
