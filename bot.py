import os
import logging
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ ERROR: TELEGRAM_TOKEN is missing from your environment variables!")

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("pharmacy_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            message TEXT,
            response TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def log_interaction(user_id, username, message, response):
    conn = sqlite3.connect("pharmacy_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chat_history (user_id, username, message, response)
        VALUES (?, ?, ?, ?)
    """, (user_id, username, message, response))
    conn.commit()
    conn.close()

# --- MEDICAL & TRIAGE DATABASE ---
RED_FLAGS = [
    "chest pain", "difficulty breathing", "shortness of breath", "severe abdominal pain",
    "coughing blood", "stiff neck", "sudden weakness", "fainting", "seizure", "unconscious"
]

SYMPTOM_DB = {
    "headache": {
        "keywords": ["headache", "head ache", "head pain", "migraine"],
        "condition": "Tension Headache / Mild Pain",
        "otc_drugs": ["Paracetamol (500mg)", "Ibuprofen (200mg - take with food)"],
        "advice": "Try resting in a quiet, dimly lit room. Put away screens, drink a full glass of water, and apply a cool compress to your forehead."
    },
    "stomach": {
        "keywords": ["stomach pain", "stomachache", "stomach ache", "belly pain", "tummy ache", "acidity", "indigestion", "heartburn", "gastric"],
        "condition": "Mild Indigestion / Upset Stomach",
        "otc_drugs": ["Antacid tablets or liquid", "Simethicone (for bloating/gas)"],
        "advice": "Sip warm water or peppermint tea. Stick to bland foods like plain rice or toast, and avoid heavy, spicy, or greasy meals."
    },
    "fever": {
        "keywords": ["fever", "high temperature", "feeling hot", "chills", "body ache"],
        "condition": "Mild Fever & Body Aches",
        "otc_drugs": ["Paracetamol (500mg)"],
        "advice": "Rest and sip plenty of fluids (water or oral rehydration drinks). Wear light clothing and use a damp cloth to cool off."
    },
    "cold": {
        "keywords": ["cold", "runny nose", "blocked nose", "congestion", "sneezing", "flu"],
        "condition": "Common Cold / Nasal Congestion",
        "otc_drugs": ["Decongestant nasal spray (use max 3-5 days)", "Vitamin C / Zinc supplements"],
        "advice": "Do a gentle steam inhalation with hot water. Keep warm, get plenty of sleep, and drink warm fluids with honey and lemon."
    },
    "cough": {
        "keywords": ["cough", "coughing", "throat irritation", "itchy throat"],
        "condition": "Mild Throat Irritation / Cough",
        "otc_drugs": ["Dextromethorphan (for dry cough)", "Guaifenesin (for chesty cough)", "Throat lozenges"],
        "advice": "Sip warm water with honey and lemon to coat your throat. Avoid cold drinks and dusty environments."
    },
    "diarrhea": {
        "keywords": ["diarrhea", "diarrhoea", "loose stool", "stomach upset", "running stomach"],
        "condition": "Acute Mild Diarrhea",
        "otc_drugs": ["Oral Rehydration Salts (ORS packets)", "Loperamide (Imodium - short-term)"],
        "advice": "Hydration is your top priority! Keep sipping ORS solution steadily. Avoid dairy, caffeine, and oily foods."
    },
    "allergy": {
        "keywords": ["allergy", "allergic", "rash", "itching", "itchy skin", "sneezing fits", "hives"],
        "condition": "Mild Allergic Reaction / Skin Irritation",
        "otc_drugs": ["Cetirizine (10mg)", "Loratadine (10mg)", "Calamine lotion (for skin rash)"],
        "advice": "Stay away from known allergens. For skin rashes, dab calamine lotion gently on the area and avoid scratching."
    }
}

MANDATORY_DISCLAIMER = (
    "\n\n🩺 *A friendly note from your chemist:* I'm here to give you quick, general over-the-counter guidance, "
    "but I'm an AI assistant—not a replacement for a real doctor. If your symptoms persist or worsen, "
    "please visit a licensed pharmacist or healthcare provider in person!"
)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hi {user_name}! 👋 I'm your virtual neighborhood pharmacist.\n\n"
        "Tell me what's bothering you today—whether you have a headache, stomach pain, "
        "a cold, or anything else—and I'll help recommend safe over-the-counter options! 💊"
    )

async def handle_symptoms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_text = update.message.text.lower()
    
    for flag in RED_FLAGS:
        if flag in user_text:
            emergency_msg = (
                f"🚨 *PLEASE READ THIS CAREFULLY* 🚨\n\n"
                f"You mentioned experiencing *'{flag}'*. Because this can point to a serious medical emergency, "
                "please **do not** self-medicate. Head directly to the nearest hospital emergency room right away!"
            )
            log_interaction(user.id, user.username or user.first_name, user_text, emergency_msg)
            await update.message.reply_markdown(emergency_msg)
            return

    matched_conditions = []
    for key, data in SYMPTOM_DB.items():
        for keyword in data["keywords"]:
            if keyword in user_text:
                if data not in matched_conditions:
                    matched_conditions.append(data)
                break

    if matched_conditions:
        response_text = "Hey there! I hear you, let's see how we can get you feeling better. Based on what you described:\n\n"
        for item in matched_conditions:
            response_text += f"💡 *What it sounds like:* {item['condition']}\n"
            response_text += f"💊 *Safe Chemist Options:* {', '.join(item['otc_drugs'])}\n"
            response_text += f"🌱 *What you can do at home:* {item['advice']}\n\n"
        response_text += "Take it easy and take care of yourself!" + MANDATORY_DISCLAIMER
    else:
        response_text = (
            "I'm so sorry you're not feeling well! Could you tell me a bit more specifically? "
            "For example, are you dealing with a **headache**, **stomach pain**, **fever**, **cold**, **cough**, or **diarrhea**?"
        )

    log_interaction(user.id, user.username or user.first_name, user_text, response_text)
    await update.message.reply_markdown(response_text)

# --- TINY HTTP SERVER FOR RENDER WEB SERVICE HEALTH CHECKS ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Pharmacy Bot Web Service is active!")
        
    def log_message(self, format, *args):
        return  # Suppress default server logs to keep console clean

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health check web server listening on port {port}...")
    server.serve_forever()

if __name__ == "__main__":
    init_db()

    # Start the web server in a background thread so Render's health checks pass
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # Configure timeout and start bot polling
    custom_request = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=30.0,
        write_timeout=30.0,
        connect_timeout=30.0,
    )

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(custom_request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_symptoms))

    print("Human-like Pharmacy Bot is running via polling with health server...")
    app.run_polling()