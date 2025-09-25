from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os

app = Flask(__name__)
CORS(app)  # allow requests from frontend

VERIFY_TOKEN = "12345"  # set this, use same in Meta Dev console

# Load dataset (expects diseases.json in same folder)
DATA_FILE = os.path.join(os.path.dirname(__file__), "diseases.json")
with open(DATA_FILE, "r", encoding="utf-8") as f:
    diseases = json.load(f)


# ---------------- Chat Logic ----------------
def get_chatbot_reply(user_input: str):
    user_input = user_input.lower()
    matched = []

    for d in diseases:
        for s in d.get("symptoms", []):
            if s.lower() in user_input:
                matched.append({"disease": d["disease"], "advice": d.get("advice", "")})
                break

    if matched:
        reply_lines = ["Based on the symptom(s) you mentioned, possible conditions:"]
        for m in matched:
            reply_lines.append(f"- {m['disease']}: {m['advice']}")
        reply = "\n".join(reply_lines)
    else:
        reply = "I couldn't find a match. Please try listing specific symptoms like 'fever', 'cough', or 'headache'."

    return reply


# ---------------- Webhook Verify (GET) ----------------
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    else:
        return "Verification failed", 403


# ---------------- Webhook Messages (POST) ----------------
@app.route("/webhook", methods=["POST"])
def webhook_messages():
    data = request.get_json()

    if data and "entry" in data:
        for entry in data["entry"]:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for message in messages:
                    if "text" in message:
                        user_text = message["text"]["body"]
                        sender_id = message["from"]  # user's WhatsApp number

                        # get chatbot reply
                        reply_text = get_chatbot_reply(user_text)

                        # send reply back via WhatsApp API
                        send_whatsapp_message(sender_id, reply_text)

    return "EVENT_RECEIVED", 200


# ---------------- Send WhatsApp Message ----------------
import requests

WHATSAPP_TOKEN = "EAAcwuh8kFaABPvPez0BmXYcs00qnZC6CWDniP1N4ldxfoZAoCTmGAZCXVsOZBWs0QotaBKFxOubGHgZCzeYmccpe6ZCI6lu20SUpIqkdve6G5zeSXO1WgXrzvKEYq0nz2jc6s0HXymCsQrftNluYCwJEsDQ0lJ7WCZB24tsXy4yLh7cVDLTfsI6IBhOxRzVt3pLA8kDHQXAPL7oijW6JUFEYiwzcOZBSQUpTVkzMzlIZBYPsvqS8ZD" #business_id
PHONE_NUMBER_ID = "804581786068036"

def send_whatsapp_message(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=payload)


if __name__ == "__main__":
    app.run(debug=True, port=5000)



