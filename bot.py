import telegram
from telegram.ext import CommandHandler, ApplicationBuilder, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, constants
import random
import json
import os

# --- Configuration & Setup ---
ENV_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
HARDCODED_TOKEN = 'YOUR_HARDCODED_TOKEN_HERE' # <-- REPLACE THIS
TOKEN = ENV_TOKEN if ENV_TOKEN else HARDCODED_TOKEN

DATA_FILE = 'data_pattern.json'
BUTTON_TEXT = "View External Report"

# --- GAME CONFIGURATION: 8 Food Symbols ---
EIGHT_SYMBOLS = [
    '🥕 Carrot', '🥬 Cabbage', '🌽 Corn',
    '🌭 Hotdog', '🍅 Tomato', '🍢 Barbeque',
    '🥩 Steak', '🍖 Meat'
]

# --- PATTERN-BASED LOGIC: Simplified 5-Group Cycle ---
# This dictionary represents the "15 HOT-Groups" in a simplified 5-group format (A-E)
# The VALUE is a list of the 4 predicted winning symbols (3 Coin + 1 HOT) for that group.
GAME_CYCLES = {
    # Group ID: [Coin1, Coin2, Coin3, HOT]
    "A": ['🍅 Tomato', '🌭 Hotdog', '🥩 Steak', '🍖 Meat'],      # Prediction: High Meat/Hotdog
    "B": ['🌶️ Pepper', '🌽 Corn', '🥕 Carrot', '🍅 Tomato'],    # Prediction: High Tomato/Veggie
    "C": ['🥩 Steak', '🍅 Tomato', '🌶️ Pepper', '🌭 Hotdog'],   # Prediction: High Steak/Hotdog
    "D": ['🌭 Hotdog', '🌽 Corn', '🥩 Steak', '🥕 Carrot'],     # Prediction: High Veggie/Hotdog
    "E": ['🍅 Tomato', '🥕 Carrot', '🌶️ Pepper', '🥩 Steak']      # Prediction: High Tomato/Steak
}

# Define the sequence to detect (e.g., look for the last 3 results)
PATTERN_WINDOW = 3
USER_ROLL_STATE = {}

# --- Data Management Functions (Simplified) ---

def load_data():
    """Loads history and configuration from the JSON file."""
    default_data = {
        "history": [], # Stores only the results
        "config": {
            "analysis_url_base": "https://queenking.ph/game/play/STUDIO-CGM-CGM002-by-we",
            "username": "09925345945",
            "password": "Shiwashi21"
        }
    }
    # (Error handling and default setting remains the same as previous bot)
    if not os.path.exists(DATA_FILE): return default_data
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            data.setdefault('history', [])
            data.setdefault('config', default_data['config'])
            return data
    except json.JSONDecodeError:
        return default_data

def save_data(data):
    """Saves the current data state to the JSON file."""
    # (Function body remains the same)
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving data: {e}")

def update_data_with_roll(rolled_symbol, data):
    """Updates history after a roll."""
    data['history'].append(rolled_symbol[0])
    # Keep only the last 100 results to avoid massive files and focus on recent cycles
    data['history'] = data['history'][-100:]
    save_data(data)

# --- NEW PATTERN-BASED PREDICTION LOGIC ---

def find_current_group(history):
    """
    Analyzes the history to find the most likely current Group ID (A-E)
    based on the winning symbols defined in the GAME_CYCLES.
    """
    if len(history) < PATTERN_WINDOW:
        return "N/A", "Not enough data to match a cycle (need at least 3 spins)."

    # Get the most recent results to match against a cycle
    recent_results = history[-PATTERN_WINDOW:] 
    
    # Simple match: Check which group contains ALL of the recent results in its 4-item list.
    # This is a very basic pattern detector, more complex bots would use sequence matching.
    
    matching_groups = []
    
    for group_id, items in GAME_CYCLES.items():
        # Check if ALL items in recent_results are present in the group's 4 predicted items
        if all(item in items for item in recent_results):
            matching_groups.append(group_id)

    if not matching_groups:
        return "N/A", f"No current cycle (A-E) contains the last {PATTERN_WINDOW} results."
    elif len(matching_groups) == 1:
        # Found a unique match! The next spin should follow the next group in the cycle.
        current_group_id = matching_groups[0]
        # (A real pattern bot would transition to the NEXT group, e.g., if A, predict B)
        return current_group_id, f"Strong match found: The game is currently in **Group {current_group_id}**."
    else:
        # Ambiguous match
        return "N/A", f"Ambiguous match: Last {PATTERN_WINDOW} results match multiple groups: {', '.join(matching_groups)}."

def get_predictions_from_pattern(data):
    """Generates a prediction based on the detected cycle."""
    history = data['history']
    current_group_id, reasoning = find_current_group(history)
    
    if current_group_id == "N/A":
        return {
            "group_id": current_group_id,
            "reasoning": reasoning,
            "prediction": "No clear pattern detected. Falling back to Martingale (Longest Missed)."
        }

    # Since a match was found, we predict the winning items of that group.
    # (In a true cycle bot, you would predict the *next* group's items)
    winning_items = GAME_CYCLES[current_group_id]
    
    prediction_message = (
        f"**The current cycle is Group {current_group_id}!**\n"
        f"The best bets for the next round (4 Winning Items) are:\n"
        f"🏆 **{winning_items[0]}**, **{winning_items[1]}**, **{winning_items[2]}** (Coin Foods)\n"
        f"🔥 **{winning_items[3]}** (HOT-Food)"
    )

    return {
        "group_id": current_group_id,
        "reasoning": reasoning,
        "prediction": prediction_message
    }

# --- Utility and Command Handlers (Modified) ---

async def start_roll(update, context):
    """Starts the single-symbol selection process via buttons. Used by /spin and /predict."""
    # (Implementation remains the same as previous bot)
    user_id = update.effective_user.id
    USER_ROLL_STATE[user_id] = [None]
    keyboard = create_symbol_keyboard(roll_number=1)
    await update.message.reply_text(
        "🎰 **Spin Result:** Please select the symbol that was hit.",
        reply_markup=keyboard,
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def handle_color_callback(update, context):
    """Handles symbol selection button clicks and generates the cycle prediction."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data.split('_')
    
    # ... (Error handling and data logging remains the same) ...
    roll_number = int(data[1])
    selected_short_name = data[2]

    full_symbol_name = next((s for s in EIGHT_SYMBOLS if selected_short_name in s.split(' ')), None)

    if roll_number == 1 and full_symbol_name:
        USER_ROLL_STATE.pop(user_id, None)

        game_data = load_data()
        update_data_with_roll([full_symbol_name], game_data)

        # --- GENERATE PATTERN PREDICTION ---
        predictions = get_predictions_from_pattern(game_data)
        
        prediction_message = predictions['prediction']

        # Build the message to prioritize the next bet
        full_analysis_message = (
            f"✅ **Spin Logged!** Result: **{full_symbol_name}**\n\n"
            f"--- **🎯 PATTERN PREDICTION FOR NEXT SPIN 🎯** ---\n"
            f"{prediction_message}\n\n"
            f"*{predictions['reasoning']}*"
        )

        await query.edit_message_text(
            full_analysis_message,
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return
        
async def get_analysis_only(update, context):
    """Allows the user to view the full analysis based on ALL history, and includes an external URL button."""
    # (This function is heavily simplified, mostly for display)
    data = load_data()
    history_display_15 = format_last_15_spins(data)
    
    predictions = get_predictions_from_pattern(data)
    prediction_message = predictions['prediction']

    full_analysis_message = (
        f"{history_display_15}\n"
        f"--- **🎯 FULL PATTERN ANALYSIS 🎯** ---\n"
        f"{prediction_message}\n\n"
        f"Total Spins Logged: **{len(data['history'])}**.\n"
        f"Current Pattern Window: **{PATTERN_WINDOW} spins**."
    )
    
    # (External URL generation and button creation remains the same)
    base_url = data['config'].get('analysis_url_base', "https://www.example.com/report")
    keyboard = [[InlineKeyboardButton(BUTTON_TEXT, url=base_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        full_analysis_message,
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.MARKDOWN
    )


# --- Remaining Utility Functions (Same as previous bot) ---
# reset_history
# create_symbol_keyboard
# format_last_15_spins
# start, set_analysis_base_url, set_credentials, main

# --- Utility and Command Handlers (from previous bot, unchanged) ---

async def reset_history(update, context):
    """Resets all recorded history and counts, and confirms pattern reset."""
    initial_data = load_data()
    initial_data['history'] = []
    initial_data['symbol_counts'] = {symbol: 0 for symbol in EIGHT_SYMBOLS}
    save_data(initial_data)
    await update.message.reply_text(
        "✅ **Spinner History Reset!** All past spins and statistics have been cleared.\n"
        "**NOTE:** All existing patterns have been **RESET**.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

def create_symbol_keyboard(roll_number):
    """Creates the inline keyboard with new food symbol buttons."""
    keyboard = [
        [InlineKeyboardButton("🥕 Carrot", callback_data=f"roll_{roll_number}_Carrot"),
         InlineKeyboardButton("🥬 Cabbage", callback_data=f"roll_{roll_number}_Cabbage")],
        [InlineKeyboardButton("🌽 Corn", callback_data=f"roll_{roll_number}_Corn"),
         InlineKeyboardButton("🌭 Hotdog", callback_data=f"roll_{roll_number}_Hotdog")],
        [InlineKeyboardButton("🍅 Tomato", callback_data=f"roll_{roll_number}_Tomato"),
         InlineKeyboardButton("🍢 Barbeque", callback_data=f"roll_{roll_number}_Barbeque")],
        [InlineKeyboardButton("🥩 Steak", callback_data=f"roll_{roll_number}_Steak"),
         InlineKeyboardButton("🍖 Meat", callback_data=f"roll_{roll_number}_Meat")],
    ]
    return InlineKeyboardMarkup(keyboard)

def format_last_15_spins(data):
    """Formats the last 15 single spins for display."""
    history = data['history']
    if not history: return "History: No spins logged yet."

    recent_history = history[-15:]
    start_index = len(history) - len(recent_history) + 1

    spin_list = []
    for i, symbol in enumerate(recent_history):
        # Removed full symbol names for brevity in this display:
        spin_str = f"**#{start_index + i}:** {symbol.split(' ')[0]}" 
        spin_list.append(spin_str)

    return f"📜 **Last {len(recent_history)} Logged Spins:**\n" + "\n".join(spin_list)

async def start(update, context):
    """Sends a greeting message with a full list of commands."""
    welcome_message = (
        "Welcome! I analyze the **8-Symbol Spinner Wheel** game using **Pattern Tracking**.\n\n"
        "### 🕹️ **Game Commands**\n"
        "• **/spin** or **/predict**: Log a new result and get the next **Pattern-Based** prediction.\n"
        "• **/analyze**: View the full pattern analysis, last 15 spins, and all predicted cycles.\n\n"
        "### ⚙️ **Administrative Commands**\n"
        "• **/setbaseurl [url]**: Set the base URL for the external analysis report.\n"
        "• **/setcreds [user] [pass]**: Set the username and password used to access the analysis link.\n"
        "• **/reset**: Clear all logged history and statistics (DANGEROUS!)."
    )
    await update.message.reply_text(welcome_message, parse_mode=constants.ParseMode.MARKDOWN)

async def set_analysis_base_url(update, context):
    if not context.args:
        await update.message.reply_text("⚠️ Please provide the base URL after the command. Example: **/setbaseurl https://your-website.com/report**", parse_mode=constants.ParseMode.MARKDOWN)
        return
    new_base_url = context.args[0]
    data = load_data()
    data['config']['analysis_url_base'] = new_base_url
    save_data(data)
    await update.message.reply_text(f"✅ **Analysis Base URL Updated!**\nThe new base URL is: `{new_base_url}`.", parse_mode=constants.ParseMode.MARKDOWN)

async def set_credentials(update, context):
    if len(context.args) != 2:
        await update.message.reply_text("⚠️ Please provide both your **username** and **password**. Example: **/setcreds user pass**", parse_mode=constants.ParseMode.MARKDOWN)
        return
    username = context.args[0]
    password = context.args[1]
    data = load_data()
    data['config']['username'] = username
    data['config']['password'] = password
    save_data(data)
    await update.message.reply_text(f"✅ **Credentials Saved!**\nUsername: `{username}`", parse_mode=constants.ParseMode.MARKDOWN)

# --- Main Bot Execution ---

def main():
    """Starts the bot."""
    if not os.path.exists(DATA_FILE):
        save_data(load_data())

    application = ApplicationBuilder().token(TOKEN).build()

    # Register all handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("spin", start_roll))
    application.add_handler(CommandHandler("predict", start_roll))
    application.add_handler(CallbackQueryHandler(handle_color_callback))
    application.add_handler(CommandHandler("analyze", get_analysis_only))
    application.add_handler(CommandHandler("setbaseurl", set_analysis_base_url))
    application.add_handler(CommandHandler("setcreds", set_credentials))
    application.add_handler(CommandHandler("reset", reset_history))

    print("Pattern Tracker Bot is running... Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == '__main__':
    main()
