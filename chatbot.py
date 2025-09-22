from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
import requests

app = Flask(__name__)
CORS(app)

# Load dataset
DATA_FILE = os.path.join(os.path.dirname(__file__), "diseases.json")
with open(DATA_FILE, "r", encoding="utf-8") as f:
    diseases = json.load(f)

# WhatsApp Cloud API config
WHATSAPP_TOKEN = "EAAcwuh8kFaABPg2ejtbCft9N328gyhmm6eEEqMZBRIDJquPWkUJgZBAcxvOV7kPdRYmObYKw76uv3xjUvL7mzj4vdhqYpCz35hIQtTsCh6rFlSWiXcmk0RqgJG1CqfktkyPGvBULhSuPS8ZC47jh5yp4ZAQOcD9HmShPasNGQPUtdq8x3lQOHo4F2hnDX5wQUeXrjNdZAwryw71Mz9zrVAHyULjuKtujKm4FJnkWQZAVKX5wZDZD"
PHONE_NUMBER_ID = "804581786068036"
GRAPH_API_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"

# ---------- Chatbot logic ----------
def chatbot_reply(user_input):
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
        reply = "I couldn't find a match. Try listing symptoms like 'fever', 'cough', or 'headache'."

    return reply

# ---------- Webhook verification (needed by Meta setup) ----------
@app.route("/webhook", methods=["GET"])
def verify():
    VERIFY_TOKEN = "my_verify_token"  # set any string and use the same in Meta setup
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    else:
        return "Verification failed", 403

# ---------- Receive WhatsApp messages ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    try:
        entry = data["entry"][0]["changes"][0]["value"]
        if "messages" in entry:
            message = entry["messages"][0]
            sender = message["from"]        # user's WhatsApp number
            user_text = message["text"]["body"]

            # Get chatbot reply
            bot_reply = chatbot_reply(user_text)

            # Send back via WhatsApp API
            payload = {
                "messaging_product": "whatsapp",
                "to": sender,
                "type": "text",
                "text": {"body": bot_reply}
            }
            headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}",
                       "Content-Type": "application/json"}
            requests.post(GRAPH_API_URL, headers=headers, json=payload)

    except Exception as e:
        print("Error handling message:", e)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    app.run(port=5000, debug=True)
