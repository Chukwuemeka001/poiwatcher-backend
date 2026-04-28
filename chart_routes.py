from flask import Blueprint, request, jsonify
from chart_data import get_candles, get_price, get_multi_tf
import logging, datetime

logger = logging.getLogger(__name__)
chart_bp = Blueprint("chart", __name__, url_prefix="/api/chart")

@chart_bp.route("/candles/<symbol>/<interval>")
def candles(symbol, interval):
    limit = min(int(request.args.get("limit", 200)), 500)
    try:
        data = get_candles(symbol.upper(), interval.lower(), limit)
        return jsonify({"ok":True,"symbol":symbol.upper(),"interval":interval,"count":len(data),"candles":data})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}), 500

@chart_bp.route("/price/<symbol>")
def price(symbol):
    try:
        p = get_price(symbol.upper())
        return jsonify({"ok":True,"symbol":symbol.upper(),"price":p})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}), 500

@chart_bp.route("/multitf/<symbol>")
def multitf(symbol):
    tf_param   = request.args.get("tf", "1d,4h,1h,15m")
    timeframes = [t.strip() for t in tf_param.split(",") if t.strip()]
    try:
        data    = get_multi_tf(symbol.upper(), timeframes)
        summary = {tf:len(c) for tf,c in data.items()}
        return jsonify({"ok":True,"symbol":symbol.upper(),"timeframes":summary,"data":data})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}), 500

@chart_bp.route("/analyze", methods=["POST"])
def analyze():
    body       = request.get_json(force=True)
    symbol     = body.get("symbol","").upper()
    timeframes = body.get("timeframes",["1d","4h","1h","15m"])
    question   = body.get("question","Perform a full top-down analysis.")
    if not symbol:
        return jsonify({"ok":False,"error":"symbol required"}), 400
    try:
        chart_data = get_multi_tf(symbol, timeframes)
    except Exception as e:
        return jsonify({"ok":False,"error":f"Data fetch failed: {e}"}), 500
    candle_summary = {tf:c[-50:] for tf,c in chart_data.items()}
    lines = []
    for tf,candles in candle_summary.items():
        lines.append(f"\n[{tf.upper()} — {len(candles)} candles]")
        for c in candles[-10:]:
            t = datetime.datetime.utcfromtimestamp(c["time"]).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  {t} | O:{c['open']:.5f} H:{c['high']:.5f} L:{c['low']:.5f} C:{c['close']:.5f}")
    prompt = f"""You are analyzing {symbol} using the Liquidity & Inducement Pure Price Action system.
Multi-timeframe OHLCV data (oldest to newest):\n{''.join(lines)}\nQuestion: {question}
Respond using: HTF Bias / Working TF Structure / Liquidity Status / Mitigation Sequence /
SEC POI / Confluence / LTF Entry Conditions / Opposite Structure / Assessment"""
    try:
        import anthropic
        client  = anthropic.Anthropic()
        message = client.messages.create(model="claude-opus-4-5", max_tokens=1500,
                                         messages=[{"role":"user","content":prompt}])
        return jsonify({"ok":True,"symbol":symbol,"analysis":message.content[0].text})
    except Exception as e:
        return jsonify({"ok":False,"error":f"Analysis failed: {e}"}), 500
