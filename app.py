import os
import json
import csv
import random
import requests
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS
from twilio.rest import Client

# =============================================================================
# 1. INITIALIZE FLASK APP & LOAD ENVIRONMENT VARIABLES
# =============================================================================
app = Flask(__name__)
CORS(app)

# Load credentials from environment variables for security
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "EAAcwuh8kFaABPnP9gv7d8mNIrmJo58ef7xXoSzPEUvV1IVZCBBoLt5Vb8hDlu7i8VP3ZBUW1ZBJvtGUIVgZBZCX1LwaR4mQcnFRCEZCXeaBBJj8gZA4oUQMZBHbVLE9ZCq2HZA5muNSoLX97Ybh09fiA96isP89H0IWQzbINTe1z3S7LL0uIniUnjHRqI0ZBCCkG1P4NgZDZD")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "804581786068036")
TWILIO_ACCOUNT_SID = os.getenv("AC421d86ec58d4ea82010bfaac1b55e5e4")
TWILIO_AUTH_TOKEN = os.getenv("ef37983b955c269cb4513a7dd63bfc47")
TWILIO_PHONE_NUMBER = os.getenv("+16572932965")

# =============================================================================
# 2. LOAD ALL NECESSARY DATA
# =============================================================================
# Load training data to build the primary disease->symptoms map
training = pd.read_csv("Data/Training.csv")
diseases_data = {}
for col in training.columns[:-1]:  # Skip the 'prognosis' column
    for disease in training['prognosis'].unique():
        if disease not in diseases_data:
            diseases_data[disease] = []
        if training.loc[training['prognosis'] == disease, col].any():
            diseases_data[disease].append(col) # Keep underscore for internal logic

# Load helper data (descriptions, precautions, doctors)
description_dict = {}
precaution_dict = {}
doctors_db = []

with open("MasterData/symptom_Description.csv") as f:
    for row in csv.reader(f):
        if len(row) >= 2: description_dict[row[0].strip()] = row[1].strip()

with open("MasterData/symptom_precaution.csv") as f:
    for row in csv.reader(f):
        if len(row) >= 5: precaution_dict[row[0].strip()] = [row[1], row[2], row[3], row[4]]

with open("doctors.json", "r", encoding="utf-8") as f:
    doctors_db = json.load(f)

# Dictionary to track all user conversations
sessions = {}
MAX_QUESTIONS = 5

# =============================================================================
# 3. API HELPER FUNCTIONS (SMS & DOCTOR SEARCH)
# =============================================================================

def find_nearby_doctors(location_text):
    """Searches the local doctors.json file for a matching city or area."""
    location_text = location_text.lower()
    results = [doc for doc in doctors_db if location_text in doc["city"].lower() or location_text in doc["area"].lower()]
    
    if not results:
        return "Sorry, I couldn't find any doctors in that location in my database."
        
    reply = "Here are some doctors and clinics I found:\n\n"
    for place in results[:3]: # Limit to top 3 results
        reply += f"🏥 *{place['name']}*\n"
        reply += f"📍 Area: {place['area']}, {place['city']}\n\n"
    return reply.strip()

def send_sms_alert(recipient_phone, message_body):
    """Sends an SMS message using the Twilio API."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        print("Twilio credentials are not configured. Skipping SMS alert.")
        return
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(to=f"+{recipient_phone}", from_=TWILIO_PHONE_NUMBER, body=message_body)
        print(f"SMS alert sent successfully! SID: {message.sid}")
    except Exception as e:
        print(f"Error sending SMS alert: {e}")

# =============================================================================
# 4. CORE CHATBOT LOGIC (Based on the simpler filtering model)
# =============================================================================

def get_chatbot_response(session, user_input):
    """Contains the main filtering logic for the chatbot conversation."""
    
    # Filter possible diseases based on user's new input
    matching_diseases = []
    for disease, symptoms in diseases_data.items():
        for s in symptoms:
            if s.replace("_", " ").lower() in user_input:
                matching_diseases.append(disease)
                break
    
    if matching_diseases:
        # Intersect the current possibilities with the new matches
        session["possible_diseases"] = list(
            set(session["possible_diseases"]) & set(matching_diseases)
        )

    # Check if it's time to diagnose
    if session["question_count"] >= MAX_QUESTIONS or len(session["possible_diseases"]) <= 1:
        if session["possible_diseases"]:
            diagnosis = random.choice(session["possible_diseases"])
            desc = description_dict.get(diagnosis, "No description available.")
            precautions = precaution_dict.get(diagnosis, [])
            reply = f"🩺 Based on your symptoms, a possible condition is *{diagnosis}*.\n\n📖 *About:* {desc}"
            if precautions:
                reply += "\n\n🛡️ *Suggested Precautions:*\n"
                for i, p in enumerate(precautions, 1):
                    reply += f"{i}. {p}\n"
            reply += "\n\n*Disclaimer: This is an AI suggestion. Please consult a doctor.*"
        else:
            reply = "❌ Sorry, I couldn't identify a specific disease based on your answers. Please consult a doctor."
        
        session["stage"] = "awaiting_doctor_search_consent"
        session["diagnosis"] = diagnosis if 'diagnosis' in locals() else None
        return {"reply": reply}

    # Ask the next question
    remaining_symptoms = []
    for disease in session["possible_diseases"]:
        for symptom in diseases_data[disease]:
            if symptom not in session["asked_questions"]:
                remaining_symptoms.append(symptom)

    if not remaining_symptoms:
        reply = "I need more information, but I'm out of questions. Please consult a doctor."
        session["stage"] = "done"
        return {"reply": reply}

    next_question = random.choice(remaining_symptoms)
    session["asked_questions"].append(next_question)
    session["question_count"] += 1
    return {"reply": f"To help clarify, do you also have '{next_question.replace('_', ' ')}'? (Please reply with 'yes' or 'no')"}

# =============================================================================
# 5. WHATSAPP WEBHOOK SETUP
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
        if data.get("object") == "whatsapp_business_account":
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    if change.get("field") == "messages":
                        message_data = change["value"]["messages"][0]
                        sender_id = message_data["from"]
                        user_text = message_data["text"]["body"].lower().strip()
                        handle_conversation(sender_id, user_text)
    except (KeyError, IndexError, TypeError):
        pass # Ignore non-message notifications
    return "EVENT_RECEIVED", 200

def handle_conversation(sender_id, message):
    if sender_id not in sessions or message in ["hi", "hello", "start", "menu"]:
        sessions[sender_id] = {
            "stage": "symptom_gathering",
            "possible_diseases": list(diseases_data.keys()),
            "asked_questions": [],
            "question_count": 0,
            "diagnosis": None
        }
        send_whatsapp_message(sender_id, "Welcome to the HealthCare ChatBot! Please describe your main symptoms.")
        return

    session = sessions[sender_id]
    stage = session.get("stage")

    if stage == "symptom_gathering":
        result = get_chatbot_response(session, message)
        send_whatsapp_message(sender_id, result["reply"])
        
        if session.get("stage") == "awaiting_doctor_search_consent":
            send_whatsapp_message(sender_id, "Would you like me to find a nearby doctor? (yes/no)")
            # Trigger SMS alert if a diagnosis was made
            if session.get("diagnosis"):
                sms_body = f"HealthBot Alert: Your session concluded with a possible diagnosis of {session['diagnosis']}. Check WhatsApp for details & consult a doctor."
                send_sms_alert(sender_id, sms_body)

    elif stage == "awaiting_doctor_search_consent":
        if message in ["yes", "y"]:
            session["stage"] = "awaiting_location"
            send_whatsapp_message(sender_id, "Great! Please tell me your city or area (e.g., Mambakkam, Chennai).")
        else:
            send_whatsapp_message(sender_id, "Alright. Take care and consult a professional. Say 'hi' to start over.")
            del sessions[sender_id]
    
    elif stage == "awaiting_location":
        doctors_list = find_nearby_doctors(message)
        send_whatsapp_message(sender_id, doctors_list)
        send_whatsapp_message(sender_id, "I hope this helps! Wishing you a speedy recovery.")
        del sessions[sender_id]

def send_whatsapp_message(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "text": {"body": text}}
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Message sent to {to}, status: {response.status_code}")
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error sending message to {to}: {err}, Response: {response.text}")

# =============================================================================
# 6. RUN THE FLASK APP
# =============================================================================
if __name__ == "__main__":
    app.run(debug=True)

