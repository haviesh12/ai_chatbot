from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os

app = Flask(__name__)
CORS(app)

# Load dataset
DATA_FILE = os.path.join(os.path.dirname(__file__), "diseases.json")
with open(DATA_FILE, "r", encoding="utf-8") as f:
    diseases = json.load(f)

# Track user sessions
sessions = {}

MAX_QUESTIONS = 5  # Limit of questions per user session

def extract_symptoms(message, diseases_data):
    message = message.lower()
    found_symptoms = []
    for disease in diseases_data:
        for symptom in disease["symptoms"]:
            if symptom.lower() in message and symptom not in found_symptoms:
                found_symptoms.append(symptom)
    return found_symptoms

def choose_next_symptom(possible_diseases, known_symptoms):
    # Count frequency of remaining symptoms
    symptom_counts = {}
    for d in possible_diseases:
        for s in d["symptoms"]:
            if s not in known_symptoms:
                symptom_counts[s] = symptom_counts.get(s, 0) + 1
    if not symptom_counts:
        return None
    # Pick the symptom that appears in most remaining diseases
    next_symptom = max(symptom_counts, key=symptom_counts.get)
    return next_symptom

def get_best_guess(possible_diseases, known_symptoms):
    # Rank diseases by number of matched symptoms
    ranked = sorted(
        possible_diseases,
        key=lambda d: sum(1 for s in d["symptoms"] if s in known_symptoms),
        reverse=True
    )
    if ranked:
        d = ranked[0]
        return f"Based on your symptoms, the most likely condition is **{d['disease']}**.\nAdvice: {d['advice']}"
    return "I couldn't find a matching disease. Please consult a doctor."

def get_next_question(user_id, session):
    known_symptoms = session["symptoms"]
    possible_diseases = session.get("possible_diseases", diseases)
    questions_asked = session.get("questions_asked", 0)

    # Filter diseases based on known symptoms
    possible_diseases = [
        d for d in possible_diseases if all(s in d["symptoms"] for s in known_symptoms if s in d["symptoms"])
    ]
    session["possible_diseases"] = possible_diseases

    # Check if we reached max questions
    if questions_asked >= MAX_QUESTIONS:
        reply = get_best_guess(possible_diseases, known_symptoms)
        return {"reply": reply, "done": True}

    # Check if only one disease remains and all symptoms matched
    if len(possible_diseases) == 1:
        d = possible_diseases[0]
        if all(s in known_symptoms for s in d["symptoms"]):
            return {
                "reply": f"Based on your symptoms, it looks like **{d['disease']}**.\nAdvice: {d['advice']}",
                "done": True
            }

    # Choose next symptom to ask
    next_symptom = choose_next_symptom(possible_diseases, known_symptoms)
    if next_symptom:
        session["questions_asked"] = questions_asked + 1
        return {
            "reply": f"Do you also have '{next_symptom}'?",
            "next_question": next_symptom,
            "done": False
        }

    # If no more symptoms to ask
    reply = get_best_guess(possible_diseases, known_symptoms)
    return {"reply": reply, "done": True}

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_id = data.get("user_id", "default")
    message = data.get("message", "").lower().strip()

    if user_id not in sessions:
        sessions[user_id] = {
            "symptoms": [],
            "possible_diseases": diseases,
            "last_question": None,
            "questions_asked": 0
        }

    session = sessions[user_id]

    # Handle yes/no answer
    if session.get("last_question"):
        if message in ["yes", "y"]:
            session["symptoms"].append(session["last_question"])
        elif message in ["no", "n"]:
            # Remove diseases that require this symptom
            session["possible_diseases"] = [
                d for d in session["possible_diseases"] if session["last_question"] not in d["symptoms"]
            ]
        session["last_question"] = None
    else:
        # Extract symptoms from free-text input
        new_symptoms = extract_symptoms(message, diseases)
        if new_symptoms:
            for s in new_symptoms:
                if s not in session["symptoms"]:
                    session["symptoms"].append(s)
        else:
            # If no known symptom found, treat whole message as new symptom
            session["symptoms"].append(message)

    result = get_next_question(user_id, session)

    if "next_question" in result:
        session["last_question"] = result["next_question"]

    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
