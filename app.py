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

# Create a fast lookup for all unique symptoms
all_symptoms_set = set(s for d in diseases for s in d["symptoms"])

sessions = {}
MAX_QUESTIONS = 5

# =============================================================================
# 3. ADVANCED CHATBOT LOGIC (Final Corrected Version)
# =============================================================================

def extract_symptoms(message, all_symptoms):
    """Accurate symptom extraction that handles single and multi-word messages."""
    message = f" {message.lower()} " # Add spaces to handle word boundaries
    found_symptoms = set()
    for symptom in all_symptoms:
        if f" {symptom.lower()} " in message:
            found_symptoms.add(symptom)
    return list(found_symptoms)

def rank_diseases(candidate_diseases, has_symptoms, has_not_symptoms):
    """Scores and ranks a pre-filtered list of candidate diseases."""
    scores = {}
    for disease in candidate_diseases:
        score = 0
        YES_SCORE = 2  # Give more weight to confirmed symptoms
        NO_PENALTY = -1 # A "no" is a penalty, but less destructive than filtering

        for symptom in disease["symptoms"]:
            if symptom in has_symptoms:
                score += YES_SCORE
            if symptom in has_not_symptoms:
                score += NO_PENALTY
        scores[disease["disease"]] = score

    ranked_diseases = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    
    ranked_list = []
    for disease_name, score in ranked_diseases:
        for d in candidate_diseases:
            if d['disease'] == disease_name:
                # Attach the score to the disease object for confidence checks
                d['score'] = score 
                ranked_list.append(d)
                break
    return ranked_list

def choose_next_symptom(top_diseases, known_symptoms):
    """Chooses the most effective symptom to ask about next."""
    symptom_counts = {}
    # Focus on the top 3-5 contenders to find a differentiator
    for d in top_diseases[:4]: 
        for s in d["symptoms"]:
            if s not in known_symptoms:
                symptom_counts[s] = symptom_counts.get(s, 0) + 1
    
    if not symptom_counts:
        return None
        
    # Prefer a symptom that can differentiate (is not present in all top contenders)
    for symptom, count in sorted(symptom_counts.items(), key=lambda item: item[1], reverse=True):
        if count < len(top_diseases[:4]):
             return symptom

    # Fallback if all top diseases share the same remaining symptoms
    return max(symptom_counts, key=symptom_counts.get) if symptom_counts else None

def get_final_diagnosis(ranked_diseases, session):
    """Provides a final diagnosis ONLY if confidence is high enough."""
    if not ranked_diseases:
        return "Based on your answers, I am unable to make a suggestion. It is best to consult a doctor."

    best_guess = ranked_diseases[0]
    
    # ✅ CONFIDENCE THRESHOLD: Check if the score is positive and meaningful.
    # The score must be at least twice the number of initial symptoms to be confident.
    if best_guess['score'] < len(session.get('initial_symptoms', [])) * 2:
        return "Your symptoms are not specific enough for me to make a confident suggestion. Please consult a doctor for an accurate diagnosis."

    return f"Based on your symptoms, the most likely condition is *{best_guess['disease']}*.\n\n*Advice:* {best_guess['advice']}\n\n*Disclaimer: This is an AI suggestion. Please consult a doctor for a professional diagnosis.*"

def get_next_response(session):
    has_symptoms = session["has_symptoms"]
    has_not_symptoms = session["has_not_symptoms"]
    questions_asked = session.get("questions_asked", 0)
    
    # Use the pre-filtered candidate list from the session
    candidate_diseases = session.get("candidate_diseases", [])
    
    ranked_diseases = rank_diseases(candidate_diseases, has_symptoms, has_not_symptoms)

    if questions_asked >= MAX_QUESTIONS or not ranked_diseases:
        return {"reply": get_final_diagnosis(ranked_diseases, session), "done": True}

    next_symptom = choose_next_symptom(ranked_diseases, has_symptoms + has_not_symptoms)
    
    if next_symptom:
        session["questions_asked"] = questions_asked + 1
        return {
            "reply": f"To help clarify, do you also have '{next_symptom}'? (Please reply with 'yes' or 'no')",
            "next_question": next_symptom,
            "done": False
        }

    return {"reply": get_final_diagnosis(ranked_diseases, session), "done": True}

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
            "stage": "symptom_gathering",
            "initial_symptoms": [],
            "has_symptoms": [],
            "has_not_symptoms": [],
            "candidate_diseases": [],
            "last_question": None,
            "questions_asked": 0
        }
        welcome_message = "Welcome to the HealthCare ChatBot! Please describe your main symptoms. For example: 'I have a high fever and a severe headache'."
        send_whatsapp_message(sender_id, welcome_message)
        return

    session = sessions[sender_id]

    if session.get("last_question"):
        last_symptom = session["last_question"]
        if message in ["yes", "y"]:
            session["has_symptoms"].append(last_symptom)
        elif message in ["no", "n"]:
            session["has_not_symptoms"].append(last_symptom)
        session["last_question"] = None
    else: # This is the initial message with symptoms
        new_symptoms = extract_symptoms(message, all_symptoms_set)
        if new_symptoms:
            session["has_symptoms"] = new_symptoms
            session["initial_symptoms"] = list(new_symptoms) # Keep a record
            
            # ✅ CANDIDATE FILTERING: Only consider diseases relevant to the initial symptoms
            session["candidate_diseases"] = [
                d for d in diseases if any(s in d["symptoms"] for s in new_symptoms)
            ]
        else:
            send_whatsapp_message(sender_id, "I couldn't recognize any symptoms. Please be more specific, for example: 'I have a sore throat and body ache'.")
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

