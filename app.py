from flask import Flask
import requests
import yfinance as yf
import time
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from threading import Thread

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1504082995479314502/zDYRdyJ5nkmMdZhu3oixMuRLwBZZLcFQwjUHMy1Jdl5BCzNypjYA3pQi5e04AAUNH_U7"

WATCHLIST = [
    "AMD", "HOOD", "SOFI", "BAC", "AFRM",
]

# ---- Tunable settings (these are GUESSES until you backtest them) ----
SCAN_INTERVAL_SECONDS = 300      # how often the loop runs
MIN_SCORE = 6                    # only fire on the strongest setups (max is 6)
RSI_BLOCK_HIGH = 75              # don't chase overbought longs
VOLUME_MULTIPLE = 1.5            # "strong volume" threshold
MOMENTUM_PCT = 0.003             # 0.3% move over last 5 bars

sent_alerts = set()
_alerts_date = None              # tracks which day sent_alerts belongs to


def _reset_alerts_if_new_day():
    """Clear the dedupe set when the trading day changes (prevents memory growth)."""
    global _alerts_date, sent_alerts
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if _alerts_date != today:
        sent_alerts = set()
        _alerts_date = today


def market_is_open():
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    return dt_time(9, 30) <= now.time() <= dt_time(16, 0)


def send_discord_alert(message):
    if not DISCORD_WEBHOOK or "PASTE_YOUR" in DISCORD_WEBHOOK:
        print("Discord webhook not set; skipping send.")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"Discord error: {e}")


def get_next_friday():
    today = datetime.now(ZoneInfo("America/New_York"))
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    return (today + timedelta(days=days_until_friday)).strftime("%B %d, %Y")


def calculate_rsi(data, period=14):
    """Wilder's RSI (matches TradingView / most brokers)."""
    delta = data.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]


def session_vwap(hist):
    """VWAP that resets at each session open (the correct way)."""
    dates = hist.index.tz_convert("America/New_York").date
    tpv = hist["Close"] * hist["Volume"]
    import pandas as pd
    cum_tpv = pd.Series(tpv.values, index=hist.index).groupby(dates).cumsum()
    cum_vol = pd.Series(hist["Volume"].values, index=hist.index).groupby(dates).cumsum()
    return (cum_tpv / cum_vol).iloc[-1]


def scan_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d", interval="5m")
        if hist.empty or len(hist) < 200:
            print(f"{ticker}: not enough data")
            return

        close = hist["Close"]
        current_price = close.iloc[-1]
        ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]

        latest_volume = int(hist["Volume"].iloc[-1])
        average_volume = int(hist["Volume"].mean())
        vwap = session_vwap(hist)

        last_open = hist["Open"].iloc[-1]
        last_close = hist["Close"].iloc[-1]
        green_candle = last_close > last_open
        red_candle = last_close < last_open

        volume_confirmed = latest_volume > average_volume * VOLUME_MULTIPLE
        rsi = calculate_rsi(close)

        if rsi > RSI_BLOCK_HIGH:
            print(f"No-chase blocked: {ticker} RSI too high ({rsi:.2f})")
            return

        bullish = ema9 > ema20 > ema200
        bearish = ema9 < ema20 < ema200

        if not (bullish or bearish):
            print(f"No trend: {ticker}")
            return

        # ---- Scoring: max is 6 for either direction ----
        score = 1  # trend confirmed (we already returned if neither)
        if volume_confirmed:
            score += 1
        if (bullish and rsi > 60) or (bearish and rsi < 40):
            score += 1
        if abs(close.iloc[-1] - close.iloc[-5]) > current_price * MOMENTUM_PCT:
            score += 1
        if (bullish and current_price > vwap) or (bearish and current_price < vwap):
            score += 1
        if (bullish and green_candle) or (bearish and red_candle):
            score += 1

        max_score = 6
        if score < MIN_SCORE:
            print(f"Weak signal blocked: {ticker} ({score}/{max_score})")
            return

        action = "CALL" if bullish else "PUT"
        strike = round(current_price)
        expiration = get_next_friday()

        if action == "CALL":
            stop_loss = current_price * 0.995
            take_profit_1 = current_price * 1.005
            take_profit_2 = current_price * 1.01
        else:
            stop_loss = current_price * 1.005
            take_profit_1 = current_price * 0.995
            take_profit_2 = current_price * 0.99

        _reset_alerts_if_new_day()
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        alert_key = f"{today}-{ticker}-{action}-{score}"
        if alert_key in sent_alerts:
            print(f"Duplicate blocked: {ticker} ({score}/{max_score})")
            return
        sent_alerts.add(alert_key)

        message = f"""
🚨 OPTIONS TRADE ALERT 🚨
📈 Ticker: {ticker}
💰 Stock Price: ${current_price:.2f}
⚡ PLAY: {"BUY CALL" if action == "CALL" else "BUY PUT"}
📄 Suggested Contract: {ticker} {strike}{"C" if action == "CALL" else "P"}
📅 Expiration: {expiration}
🎯 Take Profit 1: ${take_profit_1:.2f}
🎯 Take Profit 2: ${take_profit_2:.2f}
🛑 Stop Loss: ${stop_loss:.2f}
⚠️ Exit Rule: Exit fast if price closes back against VWAP.
📊 EMA 9/20/200: {ema9:.2f} / {ema20:.2f} / {ema200:.2f}
📈 VWAP: {vwap:.2f}
🕯️ Candle: {"Green" if green_candle else "Red"}
📦 Volume (latest/avg): {latest_volume} / {average_volume}
✅ Volume Confirmed: {volume_confirmed}
🔥 RSI: {rsi:.2f}
⭐ Signal Strength: {score}/{max_score}
{"🚀 Strong Bullish Momentum" if action == "CALL" else "🩸 Strong Bearish Momentum"}

NOTE: These levels are based on the STOCK price, not the option.
A 0.5% stock move can swing a weekly contract 10-30%+. Size accordingly.
"""
        send_discord_alert(message)
        print(f"🔥 Alert sent for {ticker} ({score}/{max_score})")

    except Exception as e:
        print(f"Error scanning {ticker}: {e}")


def scanner_loop():
    while True:
        if market_is_open():
            print("Market open - scanning...")
            for ticker in WATCHLIST:
                scan_stock(ticker)
        else:
            print("Market closed - waiting...")
        print(f"Sleeping {SCAN_INTERVAL_SECONDS} seconds...")
        time.sleep(SCAN_INTERVAL_SECONDS)


@app.route("/")
def home():
    return "Scanner Running"


scanner_thread = Thread(target=scanner_loop)
scanner_thread.daemon = True
scanner_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
