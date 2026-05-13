from flask import Flask, request
import json
import requests
import yfinance as yf
import pandas as pd
import time
from threading import Thread

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1504082995479314502/zDYRdyJ5nkmMdZhu3oixMuRLwBZZLcFQwjUHMy1Jdl5BCzNypjYA3pQi5e04AAUNH_U7"

WATCHLIST = [
    "PLTR",
    "SOFI",
    "HOOD",
    "UBER",
    "NIO",
    "RIVN",
    "PYPL",
    "DIS",
    "BAC",
    "INTC",
    "PFE",
    "SHOP",
    "COIN",
    "AAPL",
    "QQQ",
    "SPY"
]

def send_alert(message):
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message})
    except Exception as e:
        print("Discord error:", e)

def scan_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d", interval="5m")

        if hist.empty or len(hist) < 50:
            print(f"{ticker}: not enough data")
            return

        close = hist["Close"]

        ema_9 = close.ewm(span=9).mean().iloc[-1]
        ema_20 = close.ewm(span=20).mean().iloc[-1]
        current_price = close.iloc[-1]

        volume = hist["Volume"].iloc[-1]
        avg_volume = hist["Volume"].tail(20).mean()

        score = 0

        if current_price > ema_9:
            score += 1

        if ema_9 > ema_20:
            score += 1

        if volume > avg_volume:
            score += 1

        if score >= 2:
            alert = f"""
🚨 STOCK ALERT 🚨

Ticker: {ticker}
Price: ${round(current_price, 2)}

EMA 9: {round(ema_9, 2)}
EMA 20: {round(ema_20, 2)}

Volume: {int(volume)}
Avg Volume: {int(avg_volume)}

Score: {score}/3

Possible Momentum Play 📈
"""
            send_alert(alert)
            print(f"Alert sent for {ticker}")

        else:
            print(f"Weak signal blocked: {ticker}")

    except Exception as e:
        print(f"Error scanning {ticker}: {e}")

def scanner_loop():
    while True:
        print("Scanning market...")

        for ticker in WATCHLIST:
            scan_stock(ticker)

        print("Sleeping 300 seconds...")
        time.sleep(300)

@app.route("/")
def home():
    return "Scanner running."

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    print("Webhook received:")
    print(json.dumps(data, indent=2))

    return {"status": "ok"}

scanner_thread = Thread(target=scanner_loop)
scanner_thread.daemon = True
scanner_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
