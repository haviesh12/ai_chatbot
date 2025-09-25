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

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "EAAcwuh8kFaABPnP9gv7d8mNIrmJo58ef7xXoSzPEUvV1IVZCBBoLt5Vb8hDlu7i8VP3ZBUW1ZBJvtGUIVgZBZCX1LwaR4mQcnFRCEZCXeaBBJj8gZA4oUQMZBHbVLE9ZCq2HZA5muNSoLX97Ybh09fiA96isP89H0IWQzbINTe1z3S7LL0uIniUnjHRqI0ZBCCkG1P4NgZDZD")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "804581786068036")

# =============================================================================
# 2. LOAD DATA & INITIALIZE SESSION TRACKING
# =============================================================================
DATA_FILE = os.path.join(os.path.dirname(__file__), "diseases.json")
with open(DATA_FILE, "r", encoding="utf-8") as f:
    diseases = json.load(f)

sessions = {}
MAX_QUESTIONS = 5

# =============================================================================
# 3. ADVANCED CHATBOT LOGIC (Fine-Tuned and Refactored)
# =============================================================================

def extract_symptoms(message, diseases_data):
    message = message.lower()
    found_symptoms = []
    for disease in diseases_data:
        for symptom in disease["symptoms"]:
            # Check for whole word match to avoid partial matches (e.g., 'ache' in 'headache')
            if f" {symptom.lower()} " in f" {message} ":
                if symptom not in found_symptoms:
                    found_symptoms.append(symptom)
    return found_symptoms

def rank_diseases(all_diseases, has_symptoms, has_not_symptoms):
    """
    Scores and ranks diseases based on user's symptoms.
    +1 for each matching symptom.
    -1 for each symptom the user denies having.
    """
    scores = {}
    for disease in all_diseases:
        score = 0
        for symptom in disease["symptoms"]:
            if symptom in has_symptoms:
                score += 1
            if symptom in has_not_symptoms:
                score -= 1
        scores[disease["disease"]] = score

    # Sort diseases by score in descending order
    ranked_diseases = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    
    # Return the full disease objects, not just names
    ranked_list = []
    for disease_name, score in ranked_diseases:
        for d in all_diseases:
            if d['disease'] == disease_name:
                ranked_list.append(d)
                break
    return ranked_list

def choose_next_symptom(top_diseases, known_symptoms):
    """
    Chooses the most effective symptom to ask about next to differentiate
    between the top-ranked diseases.
    """
    symptom_counts = {}
    # Consider only the top 3-5 diseases to find a differentiator
    for d in top_diseases[:3]: 
        for s in d["symptoms"]:
            if s not in known_symptoms:
                symptom_counts[s] = symptom_counts.get(s, 0) + 1
    
    if not symptom_counts:
        return None
        
    # Find a symptom that is present in some top diseases but not all
    for symptom, count in sorted(symptom_counts.items(), key=lambda item: item[1], reverse=True):
        if count < len(top_diseases[:3]):
             return symptom # This is a good differentiator

    # Fallback if all top diseases share the same remaining symptoms
    return max(symptom_counts, key=symptom_counts.get) if symptom_counts else None


def get_final_diagnosis(ranked_diseases):
    if not ranked_diseases:
         return "I couldn't find a matching disease. It's best to consult a doctor."
    
    best_guess = ranked_diseases[0]
    return f"Based on your symptoms, the most likely condition is *{best_guess['disease']}*.\n\n*Advice:* {best_guess['advice']}\n\n*Disclaimer: This is an AI suggestion. Please consult a doctor for a professional diagnosis.*"

def get_next_response(session):
    has_symptoms = session["has_symptoms"]
    has_not_symptoms = session["has_not_symptoms"]
    questions_asked = session.get("questions_asked", 0)
    
    ranked_diseases = rank_diseases(diseases, has_symptoms, has_not_symptoms)

    if questions_asked >= MAX_QUESTIONS or not ranked_diseases:
        return {"reply": get_final_diagnosis(ranked_diseases), "done": True}

    next_symptom = choose_next_symptom(ranked_diseases, has_symptoms + has_not_symptoms)
    
    if next_symptom:
        session["questions_asked"] = questions_asked + 1
        return {
            "reply": f"To help clarify, do you also have '{next_symptom}'? (Please reply with 'yes' or 'no')",
            "next_question": next_symptom,
            "done": False
        }

    return {"reply": get_final_diagnosis(ranked_diseases), "done": True}

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
                        handle_conversation(sender_id, user_text)
    except (KeyError, IndexError, TypeError):
        pass
    return "EVENT_RECEIVED", 200

def handle_conversation(sender_id, message):
    if sender_id not in sessions or message in ["hi", "hello", "start", "menu"]:
        sessions[sender_id] = {
            "has_symptoms": [],
            "has_not_symptoms": [],
            "last_question": None,
            "questions_asked": 0
        }
        send_whatsapp_message(sender_id, "Welcome to the HealthCare ChatBot! Please describe your symptoms (e.g., 'I have a fever and a headache').")
        return

    session = sessions[sender_id]

    if session.get("last_question"):
        last_symptom = session["last_question"]
        if message in ["yes", "y"]:
            session["has_symptoms"].append(last_symptom)
        elif message in ["no", "n"]:
            session["has_not_symptoms"].append(last_symptom)
        session["last_question"] = None
    else:
        new_symptoms = extract_symptoms(message, diseases)
        if new_symptoms:
            for s in new_symptoms:
                if s not in session["has_symptoms"]:
                    session["has_symptoms"].append(s)
        else:
            send_whatsapp_message(sender_id, "I couldn't recognize any symptoms. Could you please try rephrasing? For example: 'I have a sore throat'.")
            return

    result = get_next_response(session)
    send_whatsapp_message(sender_id, result["reply"])

    if result.get("done"):
        del sessions[sender_id]
    else:
        session["last_question"] = result.get("next_question")

def send_whatsapp_message(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "text": {"body": text}}
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

