"""
chart_data.py — Unified OHLCV data layer for POIWatcher Flask backend
Sources: Crypto → Kraken (CCXT) → CoinGecko fallback
         Forex  → yfinance (Yahoo Finance)
"""

import os, time, logging, requests, ccxt

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

CRYPTO_SYMBOLS = {"BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","ADAUSDT","DOGEUSDT"}

CCXT_INTERVALS = {
    "1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
    "1h":"1h","2h":"2h","4h":"4h","1d":"1d","1w":"1w",
}

def get_candles(symbol:str, interval:str="1h", limit:int=200) -> list:
    symbol = symbol.upper().replace("/","").replace("-","")
    limit  = min(limit, 500)
    if _is_crypto(symbol):
        return _crypto_candles(symbol, interval, limit)
    return _forex_candles(symbol, interval, limit)

def get_price(symbol:str) -> float:
    candles = get_candles(symbol, "1m", limit=2)
    if not candles:
        raise ValueError(f"No price data for {symbol}")
    return candles[-1]["close"]

def get_multi_tf(symbol:str, timeframes:list) -> dict:
    result = {}
    for tf in timeframes:
        try:
            result[tf] = get_candles(symbol, tf, limit=200)
        except Exception as e:
            logger.warning(f"[get_multi_tf] {symbol} {tf} failed: {e}")
            result[tf] = []
    return result

# ── Crypto: Kraken (CCXT) primary → CoinGecko fallback ─────────────
_kraken = None
def _get_kraken():
    global _kraken
    if _kraken is None:
        _kraken = ccxt.kraken({"enableRateLimit": True})
    return _kraken

def _crypto_candles(symbol, interval, limit):
    ccxt_interval = CCXT_INTERVALS.get(interval)
    if not ccxt_interval:
        raise ValueError(f"Unsupported interval: {interval}")
    # Kraken uses XBT, not BTC
    pair = symbol.replace("BTC","XBT")
    pair = pair[:-4]+"/"+pair[-4:] if pair.endswith("USDT") else pair[:3]+"/"+pair[3:]
    try:
        raw = _get_kraken().fetch_ohlcv(pair, ccxt_interval, limit=limit)
        return [_normalize_ccxt(b) for b in raw]
    except Exception as e:
        logger.warning(f"[crypto] Kraken failed: {e} — trying CoinGecko")
        time.sleep(1)
        return _coingecko_candles(symbol, interval, limit)

def _coingecko_candles(symbol, interval, limit):
    coin_map = {"BTCUSDT":"bitcoin","ETHUSDT":"ethereum","SOLUSDT":"solana","XRPUSDT":"ripple"}
    coin_id  = coin_map.get(symbol)
    if not coin_id:
        raise ValueError(f"CoinGecko: unknown symbol {symbol}")
    days = _limit_to_days(interval, limit)
    resp = requests.get(f"{COINGECKO_BASE}/coins/{coin_id}/ohlc",
                        params={"vs_currency":"usd","days":days}, timeout=10)
    resp.raise_for_status()
    candles = [{"time":r[0]//1000,"open":r[1],"high":r[2],"low":r[3],"close":r[4],"volume":0.0}
               for r in resp.json()]
    return sorted(candles, key=lambda c:c["time"])[-limit:]

# ── Forex: yfinance only (Finnhub free tier doesn't serve OHLCV) ───
def _forex_candles(symbol, interval, limit):
    """Fetch forex candles via yfinance.

    yfinance is the only free source that reliably serves forex OHLCV
    without an API key. Pairs use the Yahoo format ``EURUSD=X``.
    """
    import yfinance as yf

    yf_symbol = symbol[:3] + symbol[3:] + "=X"
    yf_interval_map = {
        "1m":"1m",  "5m":"5m",  "15m":"15m", "30m":"30m",
        "1h":"1h",  "4h":"1h",  "1d":"1d",   "1w":"1wk",
    }
    yf_interval = yf_interval_map.get(interval, "1h")
    period_map = {
        "1m":"7d",  "5m":"60d",  "15m":"60d", "30m":"60d",
        "1h":"730d","4h":"730d", "1d":"5y",   "1w":"10y",
    }
    period = period_map.get(interval, "60d")

    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval=yf_interval)
        if df.empty:
            raise ValueError(f"yfinance returned empty data for {yf_symbol}")
        candles = []
        for ts, row in df.iterrows():
            candles.append({
                "time":   int(ts.timestamp()),
                "open":   float(row["Open"]),
                "high":   float(row["High"]),
                "low":    float(row["Low"]),
                "close":  float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
            })
        return sorted(candles, key=lambda c: c["time"])[-limit:]
    except Exception as e:
        logger.error(f"[forex] yfinance failed for {yf_symbol}: {e}")
        raise

# ── Helpers ────────────────────────────────────────────────────────
def _is_crypto(symbol):
    return symbol in CRYPTO_SYMBOLS or symbol.endswith("USDT") or symbol.endswith("USDC")

def _normalize_ccxt(b):
    return {"time":b[0]//1000,"open":b[1],"high":b[2],"low":b[3],"close":b[4],"volume":b[5] or 0.0}

def _interval_to_seconds(interval):
    units={"m":60,"h":3600,"d":86400,"w":604800}
    try: return int(interval[:-1])*units[interval[-1]]
    except: return 3600

def _limit_to_days(interval, limit):
    days = max(1,(_interval_to_seconds(interval)*limit)//86400)
    for d in [1,7,14,30,90,180,365]:
        if days<=d: return d
    return 365
