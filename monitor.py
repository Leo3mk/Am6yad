import json
import os
from pathlib import Path
from datetime import datetime, timezone

import requests

BINANCE_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
STATE_FILE = Path("state.json")
MULTIPLIER = 1.02  # 2% more severe than the current reference drop
MIN_DROP = 5.0     # ignore ordinary small moves
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def get_tickers():
    r = requests.get(BINANCE_URL, timeout=20)
    r.raise_for_status()
    return r.json()

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_alerted": {}, "last_run_max_drop": None}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=20)
    r.raise_for_status()

def main():
    state = load_state()
    tickers = get_tickers()

    # USDⓈ-M perpetual USDT pairs only.
    rows = []
    for x in tickers:
        symbol = x.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        if x.get("contractType") not in (None, "PERPETUAL"):
            continue
        try:
            pct = float(x["priceChangePercent"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((symbol, pct))

    drops = [(s, abs(p)) for s, p in rows if p < 0]
    if not drops:
        return

    # Reference = the strongest drop from the previous scan.
    previous_max = state.get("last_run_max_drop")
    current_max = max(d for _, d in drops)
    reference = float(previous_max) if previous_max else current_max

    threshold = max(MIN_DROP, reference * MULTIPLIER)

    # Check the strongest current movers first.
    candidates = sorted(
        [(s, d) for s, d in drops if d >= threshold],
        key=lambda z: z[1],
        reverse=True,
    )

    alerts = []
    last_alerted = state.setdefault("last_alerted", {})

    for symbol, drop in candidates:
        old = last_alerted.get(symbol)
        # Alert on first crossing, or again if the reference threshold has
        # moved materially higher and the coin beats that new threshold.
        if old is None or drop > float(old) * 1.02:
            alerts.append((symbol, drop, reference, threshold))
            last_alerted[symbol] = drop

    # Reset symbols once they are no longer beyond the current threshold,
    # allowing a fresh alert if they cross it again later.
    active = {s for s, d in drops if d >= threshold}
    for symbol in list(last_alerted):
        if symbol not in active:
            del last_alerted[symbol]

    for symbol, drop, ref, th in alerts:
        msg = (
            "🚨 هبوط استثنائي\n\n"
            f"🪙 {symbol}\n"
            f"📉 الهبوط: -{drop:.2f}%\n\n"
            f"🔥 أعلى هبوط بالقراءة السابقة: -{ref:.2f}%\n"
            f"🎯 حد التنبيه (+2%): -{th:.2f}%\n\n"
            "Binance USDⓈ-M Futures • 24H"
        )
        send_telegram(msg)

    state["last_run_max_drop"] = current_max
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

if __name__ == "__main__":
    main()
