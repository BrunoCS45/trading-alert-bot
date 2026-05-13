from flask import Flask
import requests
import yfinance as yf
import pandas as pd
import time
from datetime import datetime, timedelta

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1504082995479314502/zDYRdyJ5nkmMdZhu3oixMuRLwBZZLcFQwjUHMy1Jdl5BCzNypjYA3pQi5e04AAUNH_U7"

WATCHLIST = [
    "PLTR",
    "SOFI",
    "HOOD",
    "NIO",
    "PYPL",
    "DIS",
    "BAC",
    "PFE",
    "COIN",
    "AAPL",
    "QQQ",
    "SPY"
]

def send_discord_alert(message):
    requests.post(DISCORD_WEBHOOK, json={"content": message})

def get_next_friday():
    today = datetime.now()
    days_until_friday = (4 - today.weekday()) % 7

    if days_until_friday == 0:
        days_until_friday = 7

    next_friday = today + timedelta(days=days_until_friday)
    return next_friday.strftime("%B %d, %Y")

def calculate_rsi(data, period=14):
    delta = data.diff()

    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss

    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def scan_stock(ticker):
    try:
        stock = yf.Ticker(ticker)

        hist = stock.history(period="5d", interval="5m")

        if hist.empty or len(hist) < 200:
            print(f"{ticker}: not enough data")
            return

        close = hist["Close"]

        current_price = close.iloc[-1]

        ema9 = close.ewm(span=9).mean().iloc[-1]
        ema20 = close.ewm(span=20).mean().iloc[-1]
        ema200 = close.ewm(span=200).mean().iloc[-1]

        latest_volume = int(hist["Volume"].iloc[-1])
        average_volume = int(hist["Volume"].mean())

        volume_confirmed = latest_volume > average_volume

        rsi = calculate_rsi(close)

        score = 0

        # Trend confirmation
        bullish = ema9 > ema20 > ema200
        bearish = ema9 < ema20 < ema200

        if bullish or bearish:
            score += 1

        # Volume confirmation
        if volume_confirmed:
            score += 1

        # RSI confirmation
        if bullish and rsi > 60:
            score += 1

        if bearish and rsi < 40:
            score += 1

        # Momentum confirmation
        momentum = abs(close.iloc[-1] - close.iloc[-5])

        if momentum > (current_price * 0.003):
            score += 1

        # ONLY SEND STRONG/FIRE ALERTS
        if score < 4:
            print(f"Weak signal blocked: {ticker} ({score}/5)")
            return

        action = "CALL" if bullish else "PUT"

        strike = round(current_price)

        expiration = get_next_friday()

        message = f"""
🚨 OPTIONS TRADE ALERT 🚨

📈 Ticker: {ticker}
💰 Stock Price: ${current_price:.2f}

⚡ PLAY:
{"BUY CALL" if action == "CALL" else "BUY PUT"}

📄 Suggested Contract:
{ticker} {strike}{'C' if action == 'CALL' else 'P'}

📅 Expiration:
{expiration}

📊 EMA 9: {ema9:.2f}
📊 EMA 20: {ema20:.2f}
📊 EMA 200: {ema200:.2f}

📦 Latest Volume: {latest_volume}
📈 Average Volume: {average_volume}

✅ Volume Confirmed: {volume_confirmed}
🔥 RSI Momentum: {rsi:.2f}

⭐ Signal Strength: {score}/5

{"🚀 Strong Bullish Momentum Confirmed" if action == "CALL" else "🩸 Strong Bearish Momentum Confirmed"}
"""

        send_discord_alert(message)

        print(f"🔥 Strong alert sent for {ticker} ({score}/5)")

    except Exception as e:
        print(f"Error scanning {ticker}: {e}")

@app.route("/")
def home():
    return "Scanner Running"

if __name__ == "__main__":

    while True:

        now = datetime.now()

        market_open = now.replace(hour=9, minute=30, second=0)
        market_close = now.replace(hour=16, minute=0, second=0)

        if now.weekday() < 5 and market_open <= now <= market_close:

            print("Scanning market...")

            for ticker in WATCHLIST:
                scan_stock(ticker)

        else:
            print("Market closed - waiting...")

        print("Sleeping 300 seconds...")
        time.sleep(300)
