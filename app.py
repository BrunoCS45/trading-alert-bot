from flask import Flask
import os
import requests
import yfinance as yf
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from threading import Thread
import pandas as pd

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1504082995479314502/zDYRdyJ5nkmMdZhu3oixMuRLwBZZLcFQwjUHMy1Jdl5BCzNypjYA3pQi5e04AAUNH_U7"

WATCHLIST = ["BAC", "F", "SOFI", "HOOD"]

# ---- Tunable settings (GUESSES until swing_backtest.py proves them) ----
SCAN_INTERVAL_SECONDS = 600     # check every hour (daily strategy; avoid rate limits)
TICKER_DELAY_SECONDS = 4         # pause between tickers so Yahoo doesn't throttle
FETCH_RETRIES = 3                # retry a ticker if rate-limited
RSI_BLOCK_HIGH = 72              # don't buy already-overbought
RSI_BLOCK_LOW = 28              # don't short already-oversold
PULLBACK_LOOKBACK = 5           # bars to look back for the dip toward EMA20
PULLBACK_TOUCH = 0.01           # "near EMA20" = within 1%
STOP_PCT = 0.04                 # 4% stop (room for a swing to breathe)
TARGET_PCT = 0.08               # 8% target
OPTION_WEEKS_OUT = 3            # suggest expiration ~3 weeks out (slow theta)

sent_alerts = set()
_alerts_date = None


def _reset_alerts_if_new_day():
    global _alerts_date, sent_alerts
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if _alerts_date != today:
        sent_alerts = set()
        _alerts_date = today


def market_is_open():
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    from datetime import time as dt_time
    return dt_time(9, 30) <= now.time() <= dt_time(16, 0)


def send_discord_alert(message):
    if not DISCORD_WEBHOOK or "PASTE_YOUR" in DISCORD_WEBHOOK:
        print("Discord webhook not set; skipping send.")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"Discord error: {e}")


def get_expiration(weeks_out=OPTION_WEEKS_OUT):
    today = datetime.now(ZoneInfo("America/New_York"))
    target = today + timedelta(weeks=weeks_out)
    # roll forward to that week's Friday
    days_to_fri = (4 - target.weekday()) % 7
    exp = target + timedelta(days=days_to_fri)
    return exp.strftime("%B %d, %Y")


def wilder_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    al = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = ag / al
    return (100 - 100/(1+rs)).iloc[-1]


def fetch_history(ticker):
    """Fetch daily history with retry + backoff so a rate-limit doesn't skip the ticker."""
    for attempt in range(FETCH_RETRIES):
        try:
            hist = yf.Ticker(ticker).history(period="2y", interval="1d")
            if not hist.empty:
                return hist
        except Exception as e:
            msg = str(e)
            wait = 5 * (attempt + 1)
            print(f"{ticker}: fetch error ({msg[:40]}); retrying in {wait}s")
            time.sleep(wait)
    return None


def scan_stock(ticker):
    try:
        hist = fetch_history(ticker)
        if hist is None or hist.empty or len(hist) < 210:
            print(f"{ticker}: not enough daily data")
            return

        close = hist["Close"]
        price = close.iloc[-1]
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema200 = close.ewm(span=200, adjust=False).mean()
        rsi = wilder_rsi(close)
        vol = hist["Volume"].iloc[-1]
        avg_vol = hist["Volume"].rolling(20).mean().iloc[-1]

        uptrend = ema50.iloc[-1] > ema200.iloc[-1] and price > ema50.iloc[-1]
        downtrend = ema50.iloc[-1] < ema200.iloc[-1] and price < ema50.iloc[-1]
        if not (uptrend or downtrend):
            print(f"{ticker}: no clear trend")
            return

        # pullback toward EMA20 in the last few bars
        recent_low = hist["Low"].iloc[-PULLBACK_LOOKBACK:]
        recent_high = hist["High"].iloc[-PULLBACK_LOOKBACK:]
        near20_up = (recent_low.min() <= ema20.iloc[-1] * (1 + PULLBACK_TOUCH))
        near20_dn = (recent_high.max() >= ema20.iloc[-1] * (1 - PULLBACK_TOUCH))

        today_green = close.iloc[-1] > hist["Open"].iloc[-1]
        today_red = close.iloc[-1] < hist["Open"].iloc[-1]
        vol_ok = vol >= avg_vol

        bullish = uptrend and near20_up and today_green and rsi < RSI_BLOCK_HIGH and vol_ok
        bearish = downtrend and near20_dn and today_red and rsi > RSI_BLOCK_LOW and vol_ok
        if not (bullish or bearish):
            print(f"{ticker}: no swing setup (rsi {rsi:.1f})")
            return

        action = "CALL" if bullish else "PUT"
        strike = round(price)
        expiration = get_expiration()
        if action == "CALL":
            stop = price * (1 - STOP_PCT)
            target = price * (1 + TARGET_PCT)
        else:
            stop = price * (1 + STOP_PCT)
            target = price * (1 - TARGET_PCT)

        _reset_alerts_if_new_day()
        day = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        key = f"{day}-{ticker}-{action}"
        if key in sent_alerts:
            return
        sent_alerts.add(key)

        message = f"""
📈 SWING TRADE ALERT 📈
Ticker: {ticker}    Price: ${price:.2f}
PLAY: {"BUY CALL" if action=="CALL" else "BUY PUT"}  (multi-day hold)
Suggested contract: {ticker} {strike}{"C" if action=="CALL" else "P"}  exp {expiration}
🎯 Target: ${target:.2f}  ({TARGET_PCT*100:.0f}% move)
🛑 Stop:   ${stop:.2f}  ({STOP_PCT*100:.0f}% move)
Trend: EMA50 {'>' if action=='CALL' else '<'} EMA200, pullback-to-EMA20 reclaim
RSI: {rsi:.1f}   Volume vs 20d avg: {vol/avg_vol:.2f}x

>> Place stop + target as a BRACKET/OCO order at your broker so it exits
   itself while you're at work. Hold days, not minutes. Theta is slow on
   {OPTION_WEEKS_OUT}-week options, but it still adds up — don't marry the trade.
"""
        send_discord_alert(message)
        print(f"Swing alert: {ticker} {action}")
    except Exception as e:
        print(f"Error scanning {ticker}: {e}")


def scanner_loop():
    while True:
        print("BOT LOOP RUNNING")

        if market_is_open():
            print("Scanning (swing / daily)...")
            for t in WATCHLIST:
                scan_stock(t)
                time.sleep(TICKER_DELAY_SECONDS)
        else:
            print("Market closed - waiting...")

        print(f"Sleeping {SCAN_INTERVAL_SECONDS}s...")

        for _ in range(SCAN_INTERVAL_SECONDS):
            time.sleep(1)

@app.route("/")
def home():
    return "Swing Scanner Running"


def start_scanner():
    scanner_thread = Thread(target=scanner_loop)
    scanner_thread.daemon = True
    scanner_thread.start()
    print("Scanner thread started.")


start_scanner()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5051))  # Render provides PORT
    app.run(host="0.0.0.0", port=port)
