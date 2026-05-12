kfrom flask import Flask, request
import json
import requests
import csv
import yfinance as yf
from datetime import datetime, timedelta

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1503446068191428659/KBg6fARNmmbG1vbVADQjQ5arHPYZxqGoS16iQY7psvCj-LKd0gYbv8SMBwTE9a_WUclk"

def get_next_friday():
    today = datetime.now()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    next_friday = today + timedelta(days=days_until_friday)
    return next_friday.strftime("%B %d, %Y")

def suggest_option_contract(price, action):
    price = float(price)

    if action == "buy_call":
        strike = round(price + 1)
        contract_type = "CALL"
    elif action == "buy_put":
        strike = round(price - 1)
        contract_type = "PUT"
    else:
        strike = round(price)
        contract_type = "STOCK"

    expiration = get_next_friday()
    return strike, contract_type, expiration

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)

    print("\n🔥 NEW ALERT RECEIVED 🔥")
    print(json.dumps(data, indent=2))

    ticker = data.get("ticker", "UNKNOWN")
    price = data.get("price", "N/A")
    action = data.get("action", "N/A")
    strategy = data.get("strategy", "N/A")
    stop_loss = data.get("stop_loss", "N/A")
    take_profit = data.get("take_profit", "N/A")
    alert_time = data.get("time", "N/A")

    latest_volume = "N/A"
    average_volume = "N/A"
    volume_confirmed = False

    ema_200 = "N/A"
    trend_confirmed = False

    suggested_strike = "N/A"
    contract_type = "N/A"
    expiration = "N/A"

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d", interval="5m")

        if not hist.empty:
            latest_volume = int(hist["Volume"].iloc[-1])
            average_volume = int(hist["Volume"].mean())
            volume_confirmed = latest_volume > average_volume

            hist["EMA200"] = hist["Close"].ewm(span=200).mean()
            ema_200 = round(hist["EMA200"].iloc[-1], 2)

            current_price = float(price)

            if action == "buy_call":
                trend_confirmed = current_price > ema_200
            elif action == "buy_put":
                trend_confirmed = current_price < ema_200

            suggested_strike, contract_type, expiration = suggest_option_contract(price, action)

    except Exception as e:
        print("yfinance error:", e)

    score = 0

    if ticker != "UNKNOWN":
        score += 1

    if price != "N/A":
        score += 1

    if action in ["buy_call", "buy_put"]:
        score += 1

    if volume_confirmed:
        score += 1

    if trend_confirmed:
        score += 1

    if action == "buy_call":
        emoji = "🟢"
    elif action == "buy_put":
        emoji = "🔴"
    else:
        emoji = "🟡"

    message = {
        "content": f"""
{emoji} OPTIONS TRADE ALERT {emoji}

📈 Ticker: {ticker}
💰 Stock Price: ${price}
⚡ Action: {action}
📊 Strategy: {strategy}

🧾 Suggested Contract: {ticker} {suggested_strike} {contract_type}
📅 Expiration: {expiration}

🛑 Stop Loss: {stop_loss}
🎯 Take Profit: {take_profit}
🕒 Time: {alert_time}

📦 Latest Volume: {latest_volume}
📊 Average Volume: {average_volume}
✅ Volume Confirmed: {volume_confirmed}

📈 EMA 200: {ema_200}
✅ Trend Confirmed: {trend_confirmed}

🔥 Signal Score: {score}/5

⚠️ Confirm chart and option contract before entering.
"""
    }

    with open("alerts_log.csv", "a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            ticker,
            price,
            action,
            strategy,
            stop_loss,
            take_profit,
            alert_time,
            latest_volume,
            average_volume,
            volume_confirmed,
            ema_200,
            trend_confirmed,
            suggested_strike,
            contract_type,
            expiration,
            score
        ])

    requests.post(DISCORD_WEBHOOK, json=message)

    return {
        "status": "success",
        "score": score,
        "trend_confirmed": trend_confirmed,
        "contract": f"{ticker} {suggested_strike} {contract_type}",
        "expiration": expiration
    }, 200

@app.route('/')
def home():
    return "Trading bot running."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050)
