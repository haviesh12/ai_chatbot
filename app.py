import os
import re
import csv
import json
import requests
import random
import numpy as np
import pandas as pd
from sklearn import preprocessing
from sklearn.ensemble import RandomForestClassifier
from difflib import get_close_matches
from flask import Flask, request, jsonify
from flask_cors import CORS

# =============================================================================
# 1. INITIALIZE FLASK APP & LOAD ENVIRONMENT VARIABLES
# =============================================================================
app = Flask(__name__)
CORS(app)

# Load your tokens from environment variables for security
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "EAAcwuh8kFaABPpxwHId5cO6y93vxNRRGi2AfRT1wUuFgUy6ZBiYyZAb7sKKPgSiUY9iZCxIZCSmZBeil62vaG9G8hDfFDsS7R3OaUaZAz4HYHDfcqVjKMqurxDHCZAmyD7xeL36kl72odlJnxCRIv33Vv0z1Yxcuzjit72Yk0gEgDTHZBd8BRIRoQZCixuZCOkX2UZAKIOqtZAcoRr9ZByjzwNT9Dryg2DDgnwpczFBsQEhVGXQOywwZDZD")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "804581786068036")

# =============================================================================
# 2. MACHINE LEARNING MODEL SETUP (Runs once on server startup)
# =============================================================================
# Load Data
training = pd.read_csv('Data/Training.csv')

# Data Cleaning
training.columns = training.columns.str.replace(r"\.\d+$", "", regex=True)
training = training.loc[:, ~training.columns.duplicated()]

cols = training.columns[:-1]
x = training[cols]
y = training['prognosis']

# Encode target variable
le = preprocessing.LabelEncoder()
y = le.fit_transform(y)

# Train the Random Forest Classifier
model = RandomForestClassifier(n_estimators=300, random_state=42)
model.fit(x, y)

# Create a dictionary for symptoms
symptoms_dict = {symptom: idx for idx, symptom in enumerate(x.columns)}

# Load helper data (descriptions, precautions)
description_list = {}
precautionDictionary = {}

def load_helper_data():
    global description_list, precautionDictionary
    with open('MasterData/symptom_Description.csv') as csv_file:
        for row in csv.reader(csv_file):
            description_list[row[0]] = row[1]
            
    with open('MasterData/symptom_precaution.csv') as csv_file:
        for row in csv.reader(csv_file):
            precautionDictionary[row[0]] = [row[1], row[2], row[3], row[4]]

load_helper_data()

# =============================================================================
# 3. CORE ML & TEXT PROCESSING FUNCTIONS
# =============================================================================
symptom_synonyms = {
    "stomach ache": "stomach_pain", "belly pain": "stomach_pain", "tummy pain": "stomach_pain",
    "loose motion": "diarrhoea", "motions": "diarrhoea", "high temperature": "fever",
    "temperature": "fever", "feaver": "fever", "coughing": "cough", "throat pain": "sore_throat",
    "cold": "chills", "breathing issue": "breathlessness", "shortness of breath": "breathlessness",
    "body ache": "muscle_pain",
}

def extract_symptoms(user_input, all_symptoms):
    extracted = []
    text = user_input.lower().replace("-", " ")
    for phrase, mapped in symptom_synonyms.items():
        if phrase in text:
            extracted.append(mapped)
    for symptom in all_symptoms:
        if symptom.replace("_", " ") in text:
            extracted.append(symptom)
    words = re.findall(r"\w+", text)
    for word in words:
        close = get_close_matches(word, [s.replace("_", " ") for s in all_symptoms], n=1, cutoff=0.8)
        if close:
            for sym in all_symptoms:
                if sym.replace("_", " ") == close[0]:
                    extracted.append(sym)
    return list(set(extracted))

def predict_disease(symptoms_list):
    input_vector = np.zeros(len(symptoms_dict))
    for symptom in symptoms_list:
        if symptom in symptoms_dict:
            input_vector[symptoms_dict[symptom]] = 1
    pred_class = model.predict([input_vector])[0]
    disease = le.inverse_transform([pred_class])[0]
    return disease

def format_final_diagnosis(disease):
    """Formats the final prediction into a single message string."""
    description = description_list.get(disease, "No description available.")
    
    # Start building the reply
    reply = f"🩺 *Possible Diagnosis: {disease}*\n\n"
    reply += f"📖 *About:* {description}\n\n"
    
    # Add precautions if they exist
    if disease in precautionDictionary:
        reply += "🛡️ *Suggested Precautions:*\n"
        for i, prec in enumerate(precautionDictionary[disease], 1):
            reply += f"{i}. {prec}\n"
            
    reply += "\n*Disclaimer: This is an AI-generated suggestion. Please consult a doctor for a professional diagnosis.*"
    return reply.strip()

# =============================================================================
# 4. WHATSAPP WEBHOOK LOGIC
# =============================================================================
# Dictionary to store user conversation state
user_sessions = {}

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
    except (KeyError, IndexError):
        pass # Ignore notifications that aren't messages
    return "EVENT_RECEIVED", 200

def handle_conversation(sender_id, user_text):
    session = user_sessions.get(sender_id)

    # If it's a new conversation or a reset command
    if not session or user_text in ["hi", "hello", "start", "menu"]:
        user_sessions[sender_id] = {"stage": "symptoms_initial"}
        send_whatsapp_message(sender_id, "🤖 Welcome to the HealthCare ChatBot!\nPlease describe your symptoms.")
        return

    # Stage 1: Receiving initial symptoms
    if session["stage"] == "symptoms_initial":
        symptoms_list = extract_symptoms(user_text, cols)
        if not symptoms_list:
            send_whatsapp_message(sender_id, "❌ Could not detect valid symptoms. Please try describing them again, for example: 'I have a fever and headache'.")
            return
        
        disease = predict_disease(symptoms_list)
        all_disease_symptoms = list(training[training['prognosis'] == disease].iloc[0][:-1].index[
            training[training['prognosis'] == disease].iloc[0][:-1] == 1
        ])
        
        # Filter out symptoms already mentioned
        follow_up_symptoms = [s for s in all_disease_symptoms if s not in symptoms_list]

        user_sessions[sender_id] = {
            "stage": "symptoms_followup",
            "symptoms_list": symptoms_list,
            "follow_up_queue": follow_up_symptoms,
            "asked_count": 0
        }
        send_whatsapp_message(sender_id, f"✅ Detected: {', '.join(symptoms_list)}\n\nTo help me narrow it down, please answer a few questions with 'yes' or 'no'.")
        ask_next_question(sender_id) # Ask the first follow-up question
        return

    # Stage 2: Handling follow-up questions
    if session["stage"] == "symptoms_followup":
        # Add symptom if user says yes
        last_questioned_symptom = session["follow_up_queue"][session["asked_count"]-1]
        if user_text == "yes":
            session["symptoms_list"].append(last_questioned_symptom)
        
        # Ask next question or provide diagnosis
        if session["asked_count"] >= 5 or session["asked_count"] >= len(session["follow_up_queue"]):
            disease = predict_disease(session["symptoms_list"])
            reply = format_final_diagnosis(disease)
            send_whatsapp_message(sender_id, reply)
            del user_sessions[sender_id] # End session
        else:
            ask_next_question(sender_id)

def ask_next_question(sender_id):
    session = user_sessions[sender_id]
    symptom_to_ask = session["follow_up_queue"][session["asked_count"]]
    session["asked_count"] += 1
    send_whatsapp_message(sender_id, f"👉 Do you also have {symptom_to_ask.replace('_', ' ')}? (yes/no)")

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
