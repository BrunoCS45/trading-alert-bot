from flask import Flask, request
import json
import requests
import csv
import yfinance as yf
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
import time
import threading

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1503446068191428659/KBg6fARNmmbG1vbVADQjQ5arHPYZxqGoS16iQY7psvCj-LKd0gYbv8SMBwTE9a_WUclk"

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

sent_alerts = set()

def market_is_open():
    now = datetime.now(ZoneInfo("America/New_York"))

    if now.weekday() >= 5:
        return False

    market_open = dt_time(9, 30)
    market_close = dt_time(16, 0)

    return market_open <= now.time() <= market_close

def get_next_friday():
    today = datetime.now(ZoneInfo("America/New_York"))
    days_until_friday = (4 - today.weekday()) % 7

    if days_until_friday == 0:
        days_until_friday = 7

    next_friday = today + timedelta(days=days_until_friday)
    return next_friday.strftime("%b %d, %Y")

def calculate_rsi(closes, period=14):
    delta = closes.diff()

    gains = delta.where(delta > 0, 0)
    losses = -delta.where(delta < 0, 0)

    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi.iloc[-1]

def send_alert(message):
    requests.post(DISCORD_WEBHOOK, json={"content": message})

def scan_ticker(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d", interval="5m")

        if hist.empty or len(hist) < 220:
            print(f"{ticker}: not enough data")
            return

        close = hist["Close"]
        volume = hist["Volume"]

        current_price = close.iloc[-1]

        ema_9 = close.ewm(span=9).mean().iloc[-1]
        ema_20 = close.ewm(span=20).mean().iloc[-1]
        ema_200 = close.ewm(span=200).mean().iloc[-1]

        latest_volume = volume.iloc[-1]
        average_volume = volume.mean()
        volume_confirmed = latest_volume > average_volume

        rsi = calculate_rsi(close)

        action = None

        if ema_9 > ema_20 and current_price > ema_200 and rsi < 70:
            action = "BUY CALL"

        elif ema_9 < ema_20 and current_price < ema_200 and rsi > 30:
            action = "BUY PUT"

        if not action:
            print(f"{ticker}: no setup")
            return

        score = 0

        if volume_confirmed:
            score += 1

        if current_price > ema_200 and action == "BUY CALL":
            score += 1

        if current_price < ema_200 and action == "BUY PUT":
            score += 1

        if action == "BUY CALL" and ema_9 > ema_20:
            score += 1

        if action == "BUY PUT" and ema_9 < ema_20:
            score += 1

        if 30 < rsi < 70:
            score += 1

        if score < 4:
            print(f"Weak signal blocked: {ticker} score {score}/5")
            return

        today_key = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        alert_key = f"{today_key}-{ticker}-{action}"

        if alert_key in sent_alerts:
            print(f"{ticker}: duplicate alert blocked")
            return

        sent_alerts.add(alert_key)

        rounded_price = round(current_price)

        if action == "BUY CALL":
            suggested_contract = f"{ticker} {rounded_price + 1} CALL"
            emoji = "🟢"
        else:
            suggested_contract = f"{ticker} {rounded_price - 1} PUT"
            emoji = "🔴"

        expiration = get_next_friday()

        message = f"""
{emoji} AUTO OPTIONS SCANNER ALERT {emoji}

📈 Ticker: {ticker}
💰 Stock Price: ${round(current_price, 2)}
⚡ Action: {action}

📄 Suggested Contract:
{suggested_contract}

📅 Expiration:
{expiration}

📊 EMA 9: {round(ema_9, 2)}
📊 EMA 20: {round(ema_20, 2)}
📊 EMA 200: {round(ema_200, 2)}

📦 Latest Volume: {int(latest_volume)}
📈 Average Volume: {int(average_volume)}
✅ Volume Confirmed: {volume_confirmed}

🔥 RSI: {round(rsi, 2)}
⭐ Signal Score: {score}/5

⚠️ Confirm chart and option contract before entering.
"""

        send_alert(message)
        print(f"Alert sent for {ticker}")

        with open("alerts_log.csv", "a", newline="") as file:
            writer = csv.writer(file)

            writer.writerow([
                datetime.now(ZoneInfo("America/New_York")),
                ticker,
                round(current_price, 2),
                action,
                suggested_contract,
                expiration,
                int(latest_volume),
                int(average_volume),
                volume_confirmed,
                round(rsi, 2),
                score
            ])

    except Exception as e:
        print(f"Error scanning {ticker}: {e}")

def scanner_loop():
    while True:
        if market_is_open():
            print("Market open — scanning...")

            for ticker in WATCHLIST:
                scan_ticker(ticker)

        else:
            print("Market closed — waiting...")

        time.sleep(300)

@app.route("/")
def home():
    return "Trading bot running"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    print("Webhook received:")
    print(json.dumps(data, indent=2))

    return {"status": "success"}, 200

scanner_thread = threading.Thread(target=scanner_loop, daemon=True)
scanner_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
