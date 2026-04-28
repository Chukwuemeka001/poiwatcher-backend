"""
chart_data.py — Unified OHLCV data layer for POIWatcher Flask backend
Sources: Crypto → Binance (CCXT) → CoinGecko fallback
         Forex  → Finnhub → Alpha Vantage fallback
"""

import os, time, logging, requests, ccxt

logger = logging.getLogger(__name__)

FINNHUB_KEY   = os.getenv("FINNHUB_API_KEY", "")
AV_KEY        = os.getenv("ALPHA_VANTAGE_KEY", "")
FINNHUB_BASE  = "https://finnhub.io/api/v1"
AV_BASE       = "https://www.alphavantage.co/query"
COINGECKO_BASE= "https://api.coingecko.com/api/v3"

CRYPTO_SYMBOLS = {"BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","ADAUSDT","DOGEUSDT"}

CCXT_INTERVALS = {
    "1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
    "1h":"1h","2h":"2h","4h":"4h","1d":"1d","1w":"1w",
}
FINNHUB_INTERVALS = {
    "1m":"1","5m":"5","15m":"15","30m":"30",
    "1h":"60","4h":"D","1d":"D","1w":"W",
}
AV_INTERVALS = {
    "1m":"1min","5m":"5min","15m":"15min","30m":"30min","1h":"60min",
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

_binance = None
def _get_binance():
    global _binance
    if _binance is None:
        _binance = ccxt.binance({"enableRateLimit": True})
    return _binance

def _crypto_candles(symbol, interval, limit):
    ccxt_interval = CCXT_INTERVALS.get(interval)
    if not ccxt_interval:
        raise ValueError(f"Unsupported interval: {interval}")
    pair = symbol[:-4]+"/"+symbol[-4:] if symbol.endswith("USDT") else symbol[:3]+"/"+symbol[3:]
    try:
        raw = _get_binance().fetch_ohlcv(pair, ccxt_interval, limit=limit)
        return [_normalize_ccxt(b) for b in raw]
    except Exception as e:
        logger.warning(f"[crypto] Binance failed: {e} — trying CoinGecko")
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

def _forex_candles(symbol, interval, limit):
    try:
        return _finnhub_candles(symbol, interval, limit)
    except Exception as e:
        logger.warning(f"[forex] Finnhub failed: {e}")
        if AV_KEY:
            return _av_candles(symbol, interval, limit)
        raise

def _finnhub_candles(symbol, interval, limit):
    if not FINNHUB_KEY:
        raise ValueError("FINNHUB_API_KEY not set")
    resolution = FINNHUB_INTERVALS.get(interval)
    if not resolution:
        raise ValueError(f"Unsupported interval: {interval}")
    fh_symbol = f"OANDA:{symbol[:3]}_{symbol[3:]}"
    now = int(time.time())
    frm = now - _interval_to_seconds(interval) * limit
    resp = requests.get(f"{FINNHUB_BASE}/forex/candle",
                        params={"symbol":fh_symbol,"resolution":resolution,
                                "from":frm,"to":now,"token":FINNHUB_KEY}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("s") != "ok":
        raise ValueError(f"Finnhub status: {data.get('s')} for {fh_symbol}")
    return sorted([{"time":data["t"][i],"open":data["o"][i],"high":data["h"][i],
                    "low":data["l"][i],"close":data["c"][i],"volume":data.get("v",[0]*len(data["t"]))[i]}
                   for i in range(len(data["t"]))], key=lambda c:c["time"])

def _av_candles(symbol, interval, limit):
    av_interval = AV_INTERVALS.get(interval)
    av_from, av_to = symbol[:3], symbol[3:]
    if not av_interval:
        params = {"function":"FX_DAILY","from_symbol":av_from,"to_symbol":av_to,
                  "outputsize":"compact","apikey":AV_KEY}
        key = "Time Series FX (Daily)"
    else:
        params = {"function":"FX_INTRADAY","from_symbol":av_from,"to_symbol":av_to,
                  "interval":av_interval,"outputsize":"compact","apikey":AV_KEY}
        key = f"Time Series FX ({av_interval})"
    resp = requests.get(AV_BASE, params=params, timeout=10)
    resp.raise_for_status()
    series = resp.json().get(key, {})
    candles = []
    for ts_str, vals in series.items():
        fmt = "%Y-%m-%d %H:%M:%S" if ":" in ts_str else "%Y-%m-%d"
        ts  = int(time.mktime(time.strptime(ts_str[:19], fmt)))
        candles.append({"time":ts,"open":float(vals["1. open"]),"high":float(vals["2. high"]),
                        "low":float(vals["3. low"]),"close":float(vals["4. close"]),"volume":0.0})
    return sorted(candles, key=lambda c:c["time"])[-limit:]

def _is_crypto(symbol): return symbol in CRYPTO_SYMBOLS or symbol.endswith("USDT") or symbol.endswith("USDC")
def _normalize_ccxt(b): return {"time":b[0]//1000,"open":b[1],"high":b[2],"low":b[3],"close":b[4],"volume":b[5] or 0.0}
def _interval_to_seconds(interval):
    units={"m":60,"h":3600,"d":86400,"w":604800}
    try: return int(interval[:-1])*units[interval[-1]]
    except: return 3600
def _limit_to_days(interval, limit):
    days = max(1,(_interval_to_seconds(interval)*limit)//86400)
    for d in [1,7,14,30,90,180,365]:
        if days<=d: return d
    return 365
