import os
import logging
import sqlite3
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

# Load environment variables from local .env file
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ ERROR: TELEGRAM_TOKEN is missing from your .env file or environment variables!")

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

# --- MEDICAL & TRIAGE DATABASE (WITH HUMAN-FRIENDLY KEYWORDS) ---
RED_FLAGS = [
    "chest pain", "difficulty breathing", "shortness of breath", "severe abdominal pain",
    "coughing blood", "stiff neck", "sudden weakness", "fainting", "seizure", "unconscious"
]

SYMPTOM_DB = {
    "headache": {
        "keywords": ["headache", "head ache", "head pain", "migraine"],
        "condition": "Tension Headache / Mild Pain",
        "otc_drugs": ["Paracetamol (500mg)", "Ibuprofen (200mg - take with food)"],
        "advice": "Try resting in a quiet, dimly lit room for a bit. Put away your phone/screens, drink a full glass of water, and apply a cool compress to your forehead."
    },
    "stomach": {
        "keywords": ["stomach pain", "stomachache", "stomach ache", "belly pain", "tummy ache", "acidity", "indigestion", "heartburn", "gastric"],
        "condition": "Mild Indigestion / Upset Stomach",
        "otc_drugs": ["Antacid tablets or liquid (e.g., Magnesium/Aluminium Hydroxide)", "Simethicone (for bloating/gas)"],
        "advice": "Sip some warm water or peppermint tea. Stick to bland foods like plain rice or toast for now, and try to avoid heavy, spicy, or greasy meals until you feel better."
    },
    "fever": {
        "keywords": ["fever", "high temperature", "feeling hot", "chills", "body ache"],
        "condition": "Mild Fever & Body Aches",
        "otc_drugs": ["Paracetamol (500mg)"],
        "advice": "Make sure you're resting up and sipping plenty of fluids (water or oral rehydration drinks) to keep your temperature down. Wear light clothing and use a damp cloth to cool off."
    },
    "cold": {
        "keywords": ["cold", "runny nose", "blocked nose", "congestion", "sneezing", "flu"],
        "condition": "Common Cold / Nasal Congestion",
        "otc_drugs": ["Decongestant nasal spray (e.g., Oxymetazoline - use max 3-5 days)", "Vitamin C / Zinc supplements"],
        "advice": "Try doing a gentle steam inhalation with hot water. Keep yourself warm, get plenty of sleep, and drink lots of warm fluids with honey and lemon."
    },
    "cough": {
        "keywords": ["cough", "coughing", "throat irritation", "itchy throat"],
        "condition": "Mild Throat Irritation / Cough",
        "otc_drugs": ["Dextromethorphan (for dry cough)", "Guaifenesin (for chesty/phlegm cough)", "Throat lozenges"],
        "advice": "Sip on warm water with honey and lemon to coat your throat. Avoid cold drinks and dusty environments until your cough settles."
    },
    "diarrhea": {
        "keywords": ["diarrhea", "diarrhoea", "loose stool", "stomach upset", "running stomach"],
        "condition": "Acute Mild Diarrhea",
        "otc_drugs": ["Oral Rehydration Salts (ORS packets - mix with clean water)", "Loperamide (Imodium - for short-term relief)"],
        "advice": "Hydration is your top priority right now! Keep sipping ORS solution steadily throughout the day. Avoid dairy, caffeine, and oily foods until your digestion stabilizes."
    },
    "allergy": {
        "keywords": ["allergy", "allergic", "rash", "itching", "itchy skin", "sneezing fits", "hives"],
        "condition": "Mild Allergic Reaction / Skin Irritation",
        "otc_drugs": ["Cetirizine (10mg)", "Loratadine (10mg)", "Calamine lotion (for itchy skin rashes)"],
        "advice": "Try to figure out and stay away from what triggered the allergy. If it's a skin rash, dab a bit of calamine lotion gently on the area and avoid scratching."
    }
}

MANDATORY_DISCLAIMER = (
    "\n\n🩺 *A friendly note from your chemist:* I'm here to give you quick, general over-the-counter guidance, "
    "but I'm an AI assistant—not a replacement for a real doctor. If your symptoms hang around or start getting worse, "
    "please make sure to visit a licensed pharmacist or healthcare provider in person!"
)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hi {user_name}! 👋 I'm your virtual neighborhood pharmacist.\n\n"
        "Tell me what's bothering you today—whether you have a stubborn headache, a upset stomach, "
        "a cold, or anything else—and I'll help recommend safe over-the-counter options you can grab at the chemist shop! 💊"
    )

async def handle_symptoms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_text = update.message.text.lower()
    
    # 1. Emergency Red Flags Check
    for flag in RED_FLAGS:
        if flag in user_text:
            emergency_msg = (
                f"🚨 *PLEASE READ THIS CAREFULLY* 🚨\n\n"
                f"You mentioned experiencing *'{flag}'*. Because this can sometimes point to a more serious medical emergency, "
                "I strongly urge you **not** to try self-medicating.\n\n"
                "Please head directly to the nearest hospital emergency room or contact your doctor right away!"
            )
            log_interaction(user.id, user.username or user.first_name, user_text, emergency_msg)
            await update.message.reply_markdown(emergency_msg)
            return

    # 2. Flexible Keyword Matching across Synonyms
    matched_conditions = []
    for key, data in SYMPTOM_DB.items():
        for keyword in data["keywords"]:
            if keyword in user_text:
                if data not in matched_conditions:
                    matched_conditions.append(data)
                break

    # 3. Craft a Warm, Human-like Response
    if matched_conditions:
        response_text = "Hey there! I hear you, let's see how we can get you feeling better. Based on what you described:\n\n"
        
        for item in matched_conditions:
            response_text += f"💡 *What it sounds like:* {item['condition']}\n"
            response_text += f"💊 *Safe Chemist Options:* {', '.join(item['otc_drugs'])}\n"
            response_text += f"🌱 *What you can do at home:* {item['advice']}\n\n"
            
        response_text += "Take it easy and take care of yourself!" + MANDATORY_DISCLAIMER
    else:
        response_text = (
            "I'm so sorry you're not feeling well, but I want to make sure I give you the right advice. "
            "Could you tell me a bit more specifically? For example, are you dealing with a **headache**, **stomach pain**, "
            "a **fever**, **cold**, **cough**, or **diarrhea**? \n\n"
            "You can also pop into your local chemist shop and speak directly with the pharmacist on duty!"
        )

    # Log interaction to SQLite database
    log_interaction(user.id, user.username or user.first_name, user_text, response_text)
    await update.message.reply_markdown(response_text)

if __name__ == "__main__":
    init_db()

    # Configure robust network timeout settings
    custom_request = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=30.0,
        write_timeout=30.0,
        connect_timeout=30.0,
    )

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(custom_request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_symptoms))

    print("Human-like Pharmacy Bot is running securely with .env...")
    app.run_polling()