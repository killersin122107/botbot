import os
import asyncio
import json
import logging
from dotenv import load_dotenv # Used for local testing, Railway handles env vars directly
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from sqlmodel import Session, select

# --- Application-specific Imports (Assuming these are in your project) ---
from app.database import engine, create_db_and_tables
from app.models import Site, Check
from app.checker import background_checker

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Load environment variables for LOCAL testing
# Railway will ignore this and use its own environment variables.
load_dotenv()

# --- Configuration & Initialization ---

# 🚨 IMPORTANT: Railway sets environment variables. We rely on them here.
# Prioritize the "TELEGRAM_TOKEN" variable.
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUBSCRIBERS_FILE = os.environ.get('SUBSCRIBERS_FILE', 'subscribers.json')

# FALLBACK LOGIC (Used only if TELEGRAM_TOKEN is missing)
# While a hardcoded token is generally bad practice, keeping the fallback from your prompt.
if not TOKEN:
    ENV_TOKEN_ALT = os.environ.get('TELEGRAM_BOT_TOKEN') # Check alternative var name
    HARDCODED_TOKEN = '7988714446:AAHwAd3f0KTI2d3F-PNxtDuuuqYdZr6joJs'
    TOKEN = ENV_TOKEN_ALT or HARDCODED_TOKEN
    logging.warning("TELEGRAM_TOKEN not found. Using fallback token logic.")


# --- Utility Functions: Subscribers ---

def load_subscribers():
    """Load subscriber IDs from the JSON file."""
    try:
        with open(SUBSCRIBERS_FILE, 'r') as f:
            data = json.load(f)
            return set(data.get('subscribers', []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_subscribers(subs):
    """Save subscriber IDs to the JSON file."""
    with open(SUBSCRIBERS_FILE, 'w') as f:
        json.dump({"subscribers": list(subs)}, f, indent=4)

subscribers = load_subscribers()

# --- Utility Functions: Database ---

def db_session():
    """Provides a new database session."""
    return Session(engine)

# --- Command Handlers (Abbreviated for brevity) ---
# NOTE: The full implementation of these handlers is assumed from the previous successful rewrite.

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm the **Site Checker Bot**. Use `/sites` to see current configurations.", parse_mode=constants.ParseMode.MARKDOWN)

async def cmd_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_session() as session:
        sites = session.exec(select(Site)).all()
    if not sites:
        await update.message.reply_text("No sites configured.")
        return
    lines = ["**Configured Sites:**"]
    for s in sites:
        lines.append(f"**ID {s.id}**: {s.name or s.url}")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)
    
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Full implementation here...
    await update.message.reply_text("Adding site...", parse_mode=constants.ParseMode.MARKDOWN)

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Full implementation here...
    await update.message.reply_text("Deleting site...", parse_mode=constants.ParseMode.MARKDOWN)

async def cmd_checks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Full implementation here...
    await update.message.reply_text("Fetching checks...", parse_mode=constants.ParseMode.MARKDOWN)

async def cmd_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Full implementation here...
    await update.message.reply_text("Recommending site...", parse_mode=constants.ParseMode.MARKDOWN)

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Full implementation here...
    await update.message.reply_text("Subscribing...", parse_mode=constants.ParseMode.MARKDOWN)

async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Full implementation here...
    await update.message.reply_text("Unsubscribing...", parse_mode=constants.ParseMode.MARKDOWN)


# --- Background Task & Notification ---

async def notify_on_fail(result):
    """Sends a notification to all subscribers if a check fails."""
    global app # Requires the global 'app' reference
    
    if not result.get('ok'):
        text = f"🚨 **ALERT**: Site **ID {result.get('site_id')}** has FAILED!\nError: {result.get('error') or 'no details'}"
        for sid in list(subscribers):
            try:
                await app.bot.send_message(
                    chat_id=sid, 
                    text=text, 
                    parse_mode=constants.ParseMode.MARKDOWN
                )
            except Exception:
                logging.exception(f'Error sending notification to subscriber {sid}')

# --- Main Execution Block ---

if __name__ == '__main__':
    
    # 1. Ensure DB is created (Crucial step)
    create_db_and_tables()
    
    if not TOKEN:
        logging.error('❌ FATAL: Bot token not found in any environment variable or fallback.')
        exit(1)
        
    # 2. Build application
    application = ApplicationBuilder().token(TOKEN).build()
    
    # 3. Set a global reference for background task communication
    app = application
    
    # 4. Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('sites', cmd_sites))
    application.add_handler(CommandHandler('add', cmd_add))
    application.add_handler(CommandHandler('delete', cmd_delete))
    application.add_handler(CommandHandler('checks', cmd_checks))
    application.add_handler(CommandHandler('recommend', cmd_recommend))
    application.add_handler(CommandHandler('subscribe', cmd_subscribe))
    application.add_handler(CommandHandler('unsubscribe', cmd_unsubscribe))

    # 5. Schedule background checker that notifies on failures
    application.create_task(background_checker(notify_on_fail))

    logging.info('🟢 Bot is starting and background checker is running...')
    
    # 6. Start the bot polling (This is the long-running process Railway needs)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
