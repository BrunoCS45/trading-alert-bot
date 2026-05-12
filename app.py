from flask import Flask, request
import json
import requests
import csv
import yfinance as yf

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1503446068191428659/KBg6fARNmmbG1vbVADQjQ5arHPYZxqGoS16iQY7psvCj-LKd0gYbv8SMBwTE9a_WUclk"

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

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d", interval="5m")

        if not hist.empty:
            latest_volume = int(hist["Volume"].iloc[-1])
            average_volume = int(hist["Volume"].mean())
            volume_confirmed = latest_volume > average_volume

    except Exception as e:
        print("yfinance error:", e)

    score = 0

    if ticker != "UNKNOWN":
        score += 1

    if price != "N/A":
        score += 1

    if action in ["buy", "buy_call", "sell", "buy_put"]:
        score += 1

    if volume_confirmed:
        score += 1

    if action in ["buy", "buy_call"]:
        emoji = "🟢"
    elif action in ["sell", "buy_put"]:
        emoji = "🔴"
    else:
        emoji = "🟡"

    message = {
        "content": f"""
{emoji} TRADE ALERT {emoji}

📈 Ticker: {ticker}
💰 Price: ${price}
⚡ Action: {action}
📊 Strategy: {strategy}
🛑 Stop Loss: {stop_loss}
🎯 Take Profit: {take_profit}
🕒 Time: {alert_time}

📦 Latest Volume: {latest_volume}
📊 Average Volume: {average_volume}
✅ Volume Confirmed: {volume_confirmed}

🔥 Signal Score: {score}/4

⚠️ Confirm chart before entering.
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
            score
        ])

    requests.post(DISCORD_WEBHOOK, json=message)

    return {
        "status": "success",
        "received": data,
        "volume_confirmed": volume_confirmed,
        "score": score
    }, 200

@app.route('/')
def home():
    return "Trading bot running."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050)
