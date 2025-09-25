import os
import json
import requests
import openai  # Import the new library
from flask import Flask, request, jsonify
from flask_cors import CORS

# =============================================================================
# 1. INITIALIZE FLASK APP & CLIENTS
# =============================================================================
app = Flask(__name__)
CORS(app)

# Load environment variables
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "EAAcwuh8kFaABPnP9gv7d8mNIrmJo58ef7xXoSzPEUvV1IVZCBBoLt5Vb8hDlu7i8VP3ZBUW1ZBJvtGUIVgZBZCX1LwaR4mQcnFRCEZCXeaBBJj8gZA4oUQMZBHbVLE9ZCq2HZA5muNSoLX97Ybh09fiA96isP89H0IWQzbINTe1z3S7LL0uIniUnjHRqI0ZBCCkG1P4NgZDZD")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "804581786068036")
# NEW: Initialize OpenAI Client
openai.api_key = os.getenv("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")

# =============================================================================
# 2. LOAD DATA & INITIALIZE SESSION TRACKING
# =============================================================================
DATA_FILE = os.path.join(os.path.dirname(__file__), "diseases.json")
with open(DATA_FILE, "r", encoding="utf-8") as f:
    diseases = json.load(f)

# Create a fast lookup for all unique symptoms
all_symptoms_list = sorted(list(set(s for d in diseases for s in d["symptoms"])))

sessions = {}
MAX_QUESTIONS = 5

# =============================================================================
# 3. OPENAI-POWERED LANGUAGE FUNCTIONS
# =============================================================================

def call_openai(prompt):
    """A wrapper function to call the OpenAI API."""
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "You are a helpful medical assistant."},
                      {"role": "user", "content": prompt}],
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        return "Error: Could not process the request with AI."

def extract_symptoms_with_gpt(user_message, known_symptoms_list):
    """Uses GPT to extract symptoms from user text and match them to our list."""
    prompt = f'''
    Analyze the following user message: "{user_message}"
    Extract any medical symptoms mentioned.
    Return ONLY a comma-separated list of symptoms that are present in this master list: {', '.join(known_symptoms_list)}.
    Do not add any explanation or introductory text.
    Example: If the user says 'my head hurts and i have a high temp', and the list contains 'headache' and 'fever', you should return: headache,fever'''
    
    response_text = call_openai(prompt)
    if "Error:" in response_text:
        return []
    # Clean up the list from GPT's response
    extracted = [s.strip() for s in response_text.split(',') if s.strip() in known_symptoms_list]
    return extracted

def generate_question_with_gpt(symptom_to_ask):
    """Uses GPT to ask a follow-up question in a natural way."""
    prompt = f"You are a friendly medical chatbot. Ask the user if they have the symptom '{symptom_to_ask}'. Keep the question brief and clear. Ask them to reply with 'yes' or 'no'."
    return call_openai(prompt)

def generate_summary_with_gpt(disease_name):
    """Uses GPT to create a helpful summary of a disease."""
    prompt = f"The user has been provisionally diagnosed with '{disease_name}'. Provide a simple, easy-to-understand summary in about 3-4 sentences. Include what it is, common home care advice, and a clear recommendation to see a professional doctor for a real diagnosis."
    return call_openai(prompt)


# =============================================================================
# 4. CORE CHATBOT LOGIC (Your "Brain")
# =============================================================================

def rank_diseases(candidate_diseases, has_symptoms, has_not_symptoms):
    # ... (This function remains the same as your best version)
    scores = {}
    for disease in candidate_diseases:
        score = 0
        YES_SCORE = 2
        NO_PENALTY = -1
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
                d['score'] = score
                ranked_list.append(d)
                break
    return ranked_list

def choose_next_symptom(top_diseases, known_symptoms):
    # ... (This function remains the same)
    symptom_counts = {}
    for d in top_diseases[:4]:
        for s in d["symptoms"]:
            if s not in known_symptoms:
                symptom_counts[s] = symptom_counts.get(s, 0) + 1
    if not symptom_counts: return None
    for symptom, count in sorted(symptom_counts.items(), key=lambda item: item[1], reverse=True):
        if count < len(top_diseases[:4]): return symptom
    return max(symptom_counts, key=symptom_counts.get)

def get_final_diagnosis(ranked_diseases, session):
    # ... (This function remains the same)
    if not ranked_diseases:
        return "Based on your answers, I am unable to make a suggestion. It is best to consult a doctor."
    best_guess = ranked_diseases[0]
    if best_guess['score'] < len(session.get('initial_symptoms', [])) * 2:
        return "Your symptoms are not specific enough for me to make a confident suggestion. Please consult a doctor for an accurate diagnosis."
    
    # NEW: Generate the final summary using GPT
    final_summary = generate_summary_with_gpt(best_guess['disease'])
    return f"Based on your symptoms, it appears the most likely condition is *{best_guess['disease']}*.\n\n{final_summary}"


def get_next_response(session):
    # ... (This function's logic remains the same)
    has_symptoms = session["has_symptoms"]
    has_not_symptoms = session["has_not_symptoms"]
    questions_asked = session.get("questions_asked", 0)
    candidate_diseases = session.get("candidate_diseases", [])
    ranked_diseases = rank_diseases(candidate_diseases, has_symptoms, has_not_symptoms)
    if questions_asked >= MAX_QUESTIONS or not ranked_diseases:
        return {"reply": get_final_diagnosis(ranked_diseases, session), "done": True}
    next_symptom = choose_next_symptom(ranked_diseases, has_symptoms + has_not_symptoms)
    if next_symptom:
        session["questions_asked"] = questions_asked + 1
        # NEW: Generate the question using GPT
        question_text = generate_question_with_gpt(next_symptom)
        return {"reply": question_text, "next_question": next_symptom, "done": False}
    return {"reply": get_final_diagnosis(ranked_diseases, session), "done": True}

# =============================================================================
# 5. WHATSAPP WEBHOOK SETUP
# =============================================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook(): # ... (remains the same)
    mode, token, challenge = request.args.get("hub.mode"), request.args.get("hub.verify_token"), request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN: return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook_messages(): # ... (remains the same)
    data = request.get_json()
    try:
        if data["object"] == "whatsapp_business_account":
            for entry in data["entry"]:
                for change in entry["changes"]:
                    if change["field"] == "messages":
                        message_data = change["value"]["messages"][0]
                        sender_id, user_text = message_data["from"], message_data["text"]["body"].lower().strip()
                        handle_conversation(sender_id, user_text)
    except (KeyError, IndexError, TypeError): pass
    return "EVENT_RECEIVED", 200

def handle_conversation(sender_id, message):
    if sender_id not in sessions or message in ["hi", "hello", "start", "menu"]:
        sessions[sender_id] = { "initial_symptoms": [], "has_symptoms": [], "has_not_symptoms": [], "candidate_diseases": [], "last_question": None, "questions_asked": 0 }
        welcome_message = "Welcome to the HealthCare ChatBot! Please describe your main symptoms. For example: 'I have a high fever and a severe headache'."
        send_whatsapp_message(sender_id, welcome_message)
        return

    session = sessions[sender_id]

    if session.get("last_question"):
        last_symptom = session["last_question"]
        if message in ["yes", "y"]: session["has_symptoms"].append(last_symptom)
        elif message in ["no", "n"]: session["has_not_symptoms"].append(last_symptom)
        session["last_question"] = None
    else:
        # NEW: Use GPT for symptom extraction
        new_symptoms = extract_symptoms_with_gpt(message, all_symptoms_list)
        if new_symptoms:
            session["has_symptoms"], session["initial_symptoms"] = new_symptoms, list(new_symptoms)
            session["candidate_diseases"] = [d for d in diseases if any(s in d["symptoms"] for s in new_symptoms)]
        else:
            send_whatsapp_message(sender_id, "I'm sorry, I couldn't recognize any specific symptoms from your message. Could you please try rephrasing? For example: 'I have a sore throat and body ache'.")
            return

    result = get_next_response(session)
    send_whatsapp_message(sender_id, result["reply"])

    if result.get("done"): del sessions[sender_id]
    else: session["last_question"] = result.get("next_question")

def send_whatsapp_message(to, text): # ... (remains the same)
    url, headers = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages", {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "text": {"body": text}}
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Message sent to {to}, status: {response.status_code}")
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error: {err}, Response: {response.text}")

# =============================================================================
# 6. RUN THE FLASK APP
# =============================================================================
if __name__ == "__main__":
    app.run(debug=True)
