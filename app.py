import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# =============================================================================
# 1. INITIALIZE FLASK APP & LOAD ENVIRONMENT VARIABLES
# =============================================================================
app = Flask(__name__)
CORS(app)

# Load your tokens from environment variables for security and best practice
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "EAAcwuh8kFaABPnP9gv7d8mNIrmJo58ef7xXoSzPEUvV1IVZCBBoLt5Vb8hDlu7i8VP3ZBUW1ZBJvtGUIVgZBZCX1LwaR4mQcnFRCEZCXeaBBJj8gZA4oUQMZBHbVLE9ZCq2HZA5muNSoLX97Ybh09fiA96isP89H0IWQzbINTe1z3S7LL0uIniUnjHRqI0ZBCCkG1P4NgZDZD")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "804581786068036")

# =============================================================================
# 2. LOAD DATA & INITIALIZE SESSION TRACKING
# =============================================================================
# Load dataset from diseases.json
DATA_FILE = os.path.join(os.path.dirname(__file__), "diseases.json")
with open(DATA_FILE, "r", encoding="utf-8") as f:
    diseases = json.load(f)

# Dictionary to track user conversation sessions
sessions = {}
MAX_QUESTIONS = 5  # Limit of questions per user session

# =============================================================================
# 3. ADVANCED CHATBOT LOGIC
# =============================================================================

def extract_symptoms(message, diseases_data):
    message = message.lower()
    found_symptoms = []
    for disease in diseases_data:
        for symptom in disease["symptoms"]:
            if symptom.lower() in message and symptom not in found_symptoms:
                found_symptoms.append(symptom)
    return found_symptoms

def choose_next_symptom(possible_diseases, known_symptoms):
    symptom_counts = {}
    for d in possible_diseases:
        for s in d["symptoms"]:
            if s not in known_symptoms:
                symptom_counts[s] = symptom_counts.get(s, 0) + 1
    if not symptom_counts:
        return None
    next_symptom = max(symptom_counts, key=symptom_counts.get)
    return next_symptom

def get_best_guess(possible_diseases, known_symptoms):
    ranked = sorted(
        possible_diseases,
        key=lambda d: sum(1 for s in d["symptoms"] if s in known_symptoms),
        reverse=True
    )
    if ranked:
        d = ranked[0]
        # Using WhatsApp's markdown for bold text
        return f"Based on your symptoms, the most likely condition is *{d['disease']}*.\n\n*Advice:* {d['advice']}\n\n*Disclaimer: This is an AI suggestion. Please consult a doctor for a professional diagnosis.*"
    return "I couldn't find a matching disease based on the symptoms provided. It's best to consult a doctor."

def get_next_response(session):
    known_symptoms = session["symptoms"]
    possible_diseases = session.get("possible_diseases", diseases)
    questions_asked = session.get("questions_asked", 0)

    # Filter diseases based on known symptoms
    possible_diseases = [d for d in possible_diseases if all(s in d["symptoms"] for s in known_symptoms)]
    session["possible_diseases"] = possible_diseases

    if questions_asked >= MAX_QUESTIONS or not possible_diseases:
        reply = get_best_guess(possible_diseases, known_symptoms)
        return {"reply": reply, "done": True}

    if len(possible_diseases) == 1:
        d = possible_diseases[0]
        reply = f"Based on your symptoms, it looks like *{d['disease']}*.\n\n*Advice:* {d['advice']}\n\n*Disclaimer: This is an AI suggestion. Please consult a doctor.*"
        return {"reply": reply, "done": True}

    next_symptom = choose_next_symptom(possible_diseases, known_symptoms)
    if next_symptom:
        session["questions_asked"] = questions_asked + 1
        return {
            "reply": f"To help clarify, do you also have '{next_symptom}'? (Please reply with 'yes' or 'no')",
            "next_question": next_symptom,
            "done": False
        }

    reply = get_best_guess(possible_diseases, known_symptoms)
    return {"reply": reply, "done": True}

# =============================================================================
# 4. WHATSAPP WEBHOOK SETUP
# =============================================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook_messages():
    data = request.get_json()
    try:
        if data["object"] == "whatsapp_business_account":
            for entry in data["entry"]:
                for change in entry["changes"]:
                    if change["field"] == "messages":
                        message_data = change["value"]["messages"][0]
                        sender_id = message_data["from"]
                        user_text = message_data["text"]["body"].lower().strip()

                        # --- Main Conversation Handling ---
                        handle_conversation(sender_id, user_text)

    except (KeyError, IndexError, TypeError):
        # Handle cases where the incoming payload is not a user message
        pass
    return "EVENT_RECEIVED", 200

def handle_conversation(sender_id, message):
    # Start a new session if one doesn't exist or if user wants to restart
    if sender_id not in sessions or message in ["hi", "hello", "start", "menu"]:
        sessions[sender_id] = {
            "symptoms": [],
            "possible_diseases": diseases,
            "last_question": None,
            "questions_asked": 0
        }
        send_whatsapp_message(sender_id, "Welcome to the HealthCare ChatBot! Please describe your symptoms (e.g., 'I have a fever and a headache').")
        return

    session = sessions[sender_id]

    # Handle yes/no answer to a previous question
    if session.get("last_question"):
        last_symptom = session["last_question"]
        if message in ["yes", "y"]:
            session["symptoms"].append(last_symptom)
        elif message in ["no", "n"]:
            # Filter out diseases that require this symptom
            session["possible_diseases"] = [
                d for d in session["possible_diseases"] if last_symptom not in d["symptoms"]
            ]
        session["last_question"] = None
    else:
        # Handle initial symptom description
        new_symptoms = extract_symptoms(message, diseases)
        if new_symptoms:
            for s in new_symptoms:
                if s not in session["symptoms"]:
                    session["symptoms"].append(s)
        else:
            # If no symptoms are found, ask user to rephrase
            send_whatsapp_message(sender_id, "I couldn't recognize any symptoms in your message. Could you please try rephrasing? For example: 'I have a sore throat'.")
            return

    # Get the next response from the bot
    result = get_next_response(session)
    send_whatsapp_message(sender_id, result["reply"])

    if result.get("done"):
        # End of conversation, remove session
        del sessions[sender_id]
    else:
        # Update session with the next question
        session["last_question"] = result.get("next_question")

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
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Message sent to {to}, status: {response.status_code}")
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error sending message to {to}: {err}")
        print(f"Error Response Body: {response.text}")

# =============================================================================
# 5. RUN THE FLASK APP
# =============================================================================
if __name__ == "__main__":
    app.run(debug=True)


