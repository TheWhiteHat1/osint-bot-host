import json
import os
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
import requests
import logging
from datetime import datetime
import urllib3
import sys, types
from telegram.error import BadRequest, TelegramError

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === CONFIGURATION ===
# NOTE: Replace these placeholders if needed. You provided tokens in previous message; use env vars for production.
API_URL = "https://seller-ki-mkc.taitanx.workers.dev/?mobile="  # NEW API (no key required)
# API_KEY removed — new API doesn't require it

API_URL_VEHICLE = "https://rc-info-ng.vercel.app/?rc="
API_URL_PAK_SIM = "https://allnetworkdata.com/?number="

BOT_TOKEN = "8257919061:AAFcvvTeInEqTGVNoM3sUzpZerewAgpo9NY"
OWNER_BOT_TOKEN = "7620271547:AAGOHb_1mH16270eUIj56oDdc2pB70MKs2U"
OWNER_CHAT_ID = 7985958385

ADMIN_ID = 7985958385
ADMIN_USERNAME = "@DARKGP0"
LOGO_URL = "https://ibb.co/yc20Z7x1"

# === CHANNELS (replace with your real channel usernames) ===
CHANNEL_1 = "@channel1_username"  # <-- replace with real channel username
CHANNEL_2 = "@channel2_username"  # <-- replace with real channel username

# === FILE STORAGE ===
USER_DATA_FILE = "user_data.json"
REFERRAL_DATA_FILE = "referral_data.json"

# === TEMP STORAGE ===
user_credits = {}
banned_users = set()
referral_data = {}

# === LOGGING ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === LOAD/SAVE FUNCTIONS ===
def load_data():
    global user_credits, referral_data
    if os.path.exists(USER_DATA_FILE):
        with open(USER_DATA_FILE, "r") as f:
            try:
                user_credits = json.load(f)
                user_credits = {int(k): v for k, v in user_credits.items()}
            except Exception as e:
                logger.error(f"Error loading {USER_DATA_FILE}: {e}")
                user_credits = {}
    else:
        user_credits = {}

    if os.path.exists(REFERRAL_DATA_FILE):
        with open(REFERRAL_DATA_FILE, "r") as f:
            try:
                referral_data = json.load(f)
                referral_data = {int(k): int(v) for k, v in referral_data.items()}
            except Exception as e:
                logger.error(f"Error loading {REFERRAL_DATA_FILE}: {e}")
                referral_data = {}
    else:
        referral_data = {}

def save_user_data():
    try:
        with open(USER_DATA_FILE, "w") as f:
            json.dump(user_credits, f)
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

def save_referral_data():
    try:
        with open(REFERRAL_DATA_FILE, "w") as f:
            json.dump(referral_data, f)
    except Exception as e:
        logger.error(f"Error saving referral data: {e}")

# === FORWARD FUNCTION ===
def forward_to_owner(user, message, lookup_type="General Message"):
    try:
        user_id = user.id
        username = user.username if user.username else "N/A"
        text = (
            f"👤 User: {username}\n"
            f"🆔 ID: {user_id}\n"
            f"💬 Message: {message}\n"
            f"🛠 Used: {lookup_type}"
        )
        url = f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": OWNER_CHAT_ID, "text": text})
    except Exception as e:
        logger.error(f"Failed to forward to owner: {e}")

# === CHANNEL CHECK HELPERS ===
def is_user_member_of(chat_identifier, user_id, bot):
    """
    Returns True if user_id is a member of chat_identifier (username or id).
    """
    try:
        member = bot.get_chat_member(chat_identifier, user_id)
        # statuses like 'member', 'creator', 'administrator' mean user is present
        if member and member.status not in ("left", "kicked"):
            return True
        return False
    except TelegramError as e:
        # Could be ChatNotFound or bot not allowed to view — return False
        logger.info(f"get_chat_member error for {chat_identifier}: {e}")
        return False

def is_bot_admin_in(chat_identifier, bot):
    """
    Returns True if our bot is admin in the channel (required if you want admin permissions).
    """
    try:
        me = bot.get_me()
        member = bot.get_chat_member(chat_identifier, me.id)
        if member and member.status == "administrator":
            return True
        return False
    except TelegramError as e:
        logger.info(f"Bot admin check error for {chat_identifier}: {e}")
        return False

# === START COMMAND ===
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    args = context.args

    # Handle referral
    if args and args[0].isdigit():
        referrer_id = int(args[0])
        if user_id not in referral_data and referrer_id != user_id:
            referral_data[user_id] = referrer_id
            save_referral_data()
            if referrer_id in user_credits:
                user_credits[referrer_id] += 1
                save_user_data()

    # Initialize credits if new user
    if user_id not in user_credits:
        user_credits[user_id] = 2
        save_user_data()

    # Before showing welcome: require joining two channels
    keyboard_join = [
        [InlineKeyboardButton(f"Join Channel 1 {CHANNEL_1}", url=f"https://t.me/{CHANNEL_1.replace('@','')}")],
        [InlineKeyboardButton(f"Join Channel 2 {CHANNEL_2}", url=f"https://t.me/{CHANNEL_2.replace('@','')}")],
        [InlineKeyboardButton("🔁 Verify Joined Channels", callback_data="verify_channels")]
    ]
    join_markup = InlineKeyboardMarkup(keyboard_join)

    try:
        # send a join prompt first (only if user not already verified)
        caption = "⚠️ Please join both channels below to use the bot. After joining, tap *Verify Joined Channels*."
        # If possible show logo with caption, else plain text
        try:
            update.message.reply_photo(photo=LOGO_URL, caption=caption, parse_mode="Markdown", reply_markup=join_markup)
        except Exception:
            update.message.reply_text(caption, parse_mode="Markdown", reply_markup=join_markup)
    except Exception as e:
        logger.error(f"Error sending join prompt: {e}")
        # As fallback send normal welcome immediately
        _send_welcome(update, context)

def _send_welcome(update: Update, context: CallbackContext):
    """Sends the main welcome text (called after verification)."""
    user_id = update.effective_user.id
    balance = user_credits.get(user_id, 0)

    welcome_text = (
        f"👋 Welcome to DARK GP System\n"
        f"🕒 Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "🔍 OSINT Info Bot — Get Number / Vehicle / SIM Info 📱\n\n"
        f"💰 Credits: {balance}\n"
        f"☎️ Support: {ADMIN_USERNAME}\n\n"
        "⚠️ Use this service lawfully."
    )

    keyboard = [
        [InlineKeyboardButton("📱 Number Lookup", callback_data="number_info")],
        [InlineKeyboardButton("🚘 Vehicle Lookup", callback_data="vehicle_info")],
        [InlineKeyboardButton("🇵🇰 Pakistan SIM Info", callback_data="pak_sim_info")],
        [InlineKeyboardButton("📂 Profile", callback_data="profile")],
        [InlineKeyboardButton("🔗 Referral", callback_data="referral")],
        [InlineKeyboardButton("💰 Buy Credits", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        update.message.reply_photo(photo=LOGO_URL, caption=welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception:
        update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)

# === CALLBACK HANDLER ===
def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        query.answer()
    except Exception:
        pass

    # Clear previous lookup_type
    context.user_data.clear()

    # Handle verify button separately
    if query.data == "verify_channels":
        _handle_verify_channels(query, context)
        return

    # The rest are the usual buttons
    try:
        if query.data == "number_info":
            context.user_data["lookup_type"] = "Number Lookup"
            _safe_edit_or_reply(query, "📱 Send the phone number you want to search.")
        elif query.data == "vehicle_info":
            context.user_data["lookup_type"] = "Vehicle Lookup"
            _safe_edit_or_reply(query, "🚘 Send the vehicle RC number you want to search.")
        elif query.data == "pak_sim_info":
            context.user_data["lookup_type"] = "Pakistan SIM Lookup"
            _safe_edit_or_reply(query, "🇵🇰 Send the Pakistan SIM number you want to search.")
        elif query.data == "profile":
            balance = user_credits.get(query.from_user.id, 0)
            _safe_edit_or_reply(query, f"👤 Profile\n🆔 ID: {query.from_user.id}\n🔋 Credits: {balance}")
        elif query.data == "referral":
            ref_link = f"https://t.me/{context.bot.username}?start={query.from_user.id}"
            _safe_edit_or_reply(query, f"🔗 Invite friends & earn free coins!\n👉 {ref_link}")
        else:
            _safe_edit_or_reply(query, "Unknown action.")
    except Exception as e:
        logger.error(f"Error in handle_callback: {e}")
        _safe_edit_or_reply(query, "⚠️ An error occurred handling your action.")

def _safe_edit_or_reply(query, text, parse_mode="Markdown"):
    """
    Try to edit the message if possible; if not, reply to the user with the text.
    This avoids 'There is no text in the message to edit' and similar errors.
    """
    try:
        # Prefer editing
        query.edit_message_text(text, parse_mode=parse_mode)
    except BadRequest as e:
        # Common: message has no text, or can't edit (photo caption), fallback to reply
        try:
            query.message.reply_text(text, parse_mode=parse_mode)
        except Exception as e2:
            logger.error(f"Fallback reply failed: {e2}")
    except Exception as e:
        logger.error(f"edit_message_text failed: {e}")
        # fallback
        try:
            query.message.reply_text(text, parse_mode=parse_mode)
        except Exception as e2:
            logger.error(f"Fallback reply failed: {e2}")

def _handle_verify_channels(query, context):
    user_id = query.from_user.id
    bot = context.bot

    # First check whether bot is admin in both channels (required by your requirement)
    bot_admin_1 = is_bot_admin_in(CHANNEL_1, bot)
    bot_admin_2 = is_bot_admin_in(CHANNEL_2, bot)

    if not bot_admin_1 or not bot_admin_2:
        msg = "⚠️ I need to be an *administrator* in both channels to verify users automatically.\n\n"
        if not bot_admin_1:
            msg += f"• Promote me to admin in {CHANNEL_1}\n"
        if not bot_admin_2:
            msg += f"• Promote me to admin in {CHANNEL_2}\n"
        # Send the message (edit or reply)
        _safe_edit_or_reply(query, msg)
        return

    # Check user membership
    member1 = is_user_member_of(CHANNEL_1, user_id, bot)
    member2 = is_user_member_of(CHANNEL_2, user_id, bot)

    if member1 and member2:
        # Verified -> send welcome message
        try:
            # Edit original join message to show success
            query.edit_message_text("✅ You are verified and joined both channels. Sending welcome message...")
        except Exception:
            try:
                query.message.reply_text("✅ You are verified and joined both channels. Sending welcome message...")
            except Exception:
                pass
        # send the main welcome
        # we'll call _send_welcome but it expects update-like object; create a pseudo update
        # easiest: send welcome text directly to user
        balance = user_credits.get(user_id, 0)
        welcome_text = (
            f"👋 Welcome to DARK GP System\n"
            f"🕒 Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "🔍 OSINT Info Bot — Get Number / Vehicle / SIM Info 📱\n\n"
            f"💰 Credits: {balance}\n"
            f"☎️ Support: {ADMIN_USERNAME}\n\n"
            "⚠️ Use this service lawfully."
        )

        keyboard = [
            [InlineKeyboardButton("📱 Number Lookup", callback_data="number_info")],
            [InlineKeyboardButton("🚘 Vehicle Lookup", callback_data="vehicle_info")],
            [InlineKeyboardButton("🇵🇰 Pakistan SIM Info", callback_data="pak_sim_info")],
            [InlineKeyboardButton("📂 Profile", callback_data="profile")],
            [InlineKeyboardButton("🔗 Referral", callback_data="referral")],
            [InlineKeyboardButton("💰 Buy Credits", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            context.bot.send_photo(chat_id=user_id, photo=LOGO_URL, caption=welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            try:
                context.bot.send_message(chat_id=user_id, text=welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Failed to send welcome after verify: {e}")
    else:
        # Not joined -> instruct which channel(s) missing
        missing = []
        if not member1:
            missing.append(CHANNEL_1)
        if not member2:
            missing.append(CHANNEL_2)
        msg = "⚠️ You're missing membership in the following channel(s):\n"
        for ch in missing:
            msg += f"• {ch}\n"
        msg += "\nPlease join them and tap *Verify Joined Channels* again."
        _safe_edit_or_reply(query, msg)

# === NUMBER LOOKUP FUNCTION ===
def number_lookup(update, context, number):
    user_id = update.effective_user.id

    # Deduct credit
    user_credits[user_id] -= 1
    save_user_data()

    try:
        # Clean the number
        number = re.sub(r'\D', '', number)

        # NEW API call: key removed, direct URL
        url = API_URL + number  # e.g. https://seller-ki-mkc.taitanx.workers.dev/?mobile=999...
        res = requests.get(url, timeout=30, verify=False)

        if res.status_code == 200:
            try:
                # some APIs return an object instead of list; keep backward compat:
                data = res.json()

                if data:
                    # If the API returns object/dict wrap into list for existing formatting
                    if isinstance(data, dict):
                        data_list = [data]
                    elif isinstance(data, list):
                        data_list = data
                    else:
                        data_list = [data]

                    formatted_response = format_number_response(data_list)
                    update.message.reply_text(formatted_response, parse_mode="Markdown")

                    # Print to console for debugging
                    print_number_results(data_list)
                else:
                    update.message.reply_text("❌ No information found for this number.")
            except json.JSONDecodeError:
                update.message.reply_text("❌ Invalid response from the API server.")
        else:
            update.message.reply_text(f"❌ API Error: Status code {res.status_code}")

    except Exception as e:
        logger.error(f"Number lookup error: {e}")
        update.message.reply_text("⚠️ An error occurred while processing your request.")

def format_number_response(data):
    response_text = "🔍 *Number Lookup Results*\n\n"

    for idx, info in enumerate(data, 1):
        # handle both dicts and objects with same keys
        if not isinstance(info, dict):
            info = dict(info)
        name = info.get('name') or "N/A"
        father = info.get('fname') or info.get('father_name') or "N/A"
        address = info.get('address') or "N/A"
        mobile = info.get('mobile') or "N/A"
        alt = info.get('alt') or info.get('alt_mobile') or "N/A"
        circle = info.get('circle') or "N/A"
        id_number = info.get('id_number') or "N/A"
        email = info.get('email') or "N/A"

        # Try to extract father name from address if not available
        if father == "N/A" and address != "N/A":
            match = re.search(r"(S/O|W/O)\s+([A-Za-z ]+)", address, re.IGNORECASE)
            if match:
                father = match.group(2).strip()

        response_text += f"✅ *Result {idx}*\n\n"
        response_text += f"👤 *Name:* {name}\n"
        response_text += f"👨‍👦 *Father:* {father}\n"
        response_text += f"📍 *Address:* {address}\n"
        response_text += f"📱 *Mobile:* {mobile}\n"
        response_text += f"☎️ *Alternate:* {alt}\n"
        response_text += f"🌍 *Circle:* {circle}\n"
        response_text += f"🆔 *ID Number:* {id_number}\n"
        response_text += f"✉️ *Email:* {email}\n\n"
        response_text += "━" * 30 + "\n\n"

    return response_text

# === VEHICLE LOOKUP ===
def vehicle_lookup(update, context, rc):
    user_id = update.effective_user.id

    # Deduct credit
    user_credits[user_id] -= 1
    save_user_data()

    try:
        res = requests.get(API_URL_VEHICLE + rc, timeout=30, verify=False)
        if res.status_code == 200:
            try:
                data = res.json()

                if data and isinstance(data, dict):
                    # Format the response
                    formatted_response = format_vehicle_response(data)
                    update.message.reply_text(formatted_response, parse_mode="Markdown")

                    # Print to console for debugging
                    print_vehicle_results(data)
                else:
                    update.message.reply_text("❌ No vehicle information found.")

            except json.JSONDecodeError:
                update.message.reply_text("❌ Invalid response from the vehicle API.")
        else:
            update.message.reply_text(f"❌ Vehicle API Error: Status code {res.status_code}")
    except Exception as e:
        logger.error(f"Vehicle lookup error: {e}")
        update.message.reply_text("⚠️ An error occurred while processing your request.")

def format_vehicle_response(info):
    response_text = "🚘 *Vehicle Details*\n\n"

    response_text += f"*RC Number:* {info.get('rc_number', 'Not Available')}\n"
    response_text += f"*Owner Name:* {info.get('owner_name', 'Not Available')}\n"
    response_text += f"*Father's Name:* {info.get('father_name', 'Not Available')}\n"
    response_text += f"*Owner Serial No.:* {info.get('owner_serial_no', 'Not Available')}\n"
    response_text += f"*Model Name:* {info.get('model_name', 'Not Available')}\n"
    response_text += f"*Maker/Model:* {info.get('maker_model', 'Not Available')}\n"
    response_text += f"*Vehicle Class:* {info.get('vehicle_class', 'Not Available')}\n"
    response_text += f"*Fuel Type:* {info.get('fuel_type', 'Not Available')}\n"
    response_text += f"*Fuel Norms:* {info.get('fuel_norms', 'Not Available')}\n"
    response_text += f"*Registration Date:* {info.get('registration_date', 'Not Available')}\n\n"

    response_text += "🛡️ *Insurance Details*\n\n"
    response_text += f"*Company:* {info.get('insurance_company', 'Not Available')}\n"
    response_text += f"*Policy Number:* {info.get('insurance_no', 'Not Available')}\n"
    response_text += f"*Expiry Date:* {info.get('insurance_expiry', 'Not Available')}\n"
    response_text += f"*Valid Upto:* {info.get('insurance_upto', 'Not Available')}\n\n"

    response_text += "✅ *Fitness / Tax / PUC*\n\n"
    response_text += f"*Fitness Upto:* {info.get('fitness_upto', 'Not Available')}\n"
    response_text += f"*Tax Upto:* {info.get('tax_upto', 'Not Available')}\n"
    response_text += f"*PUC Number:* {info.get('puc_no', 'Not Available')}\n"
    response_text += f"*PUC Valid Upto:* {info.get('puc_upto', 'Not Available')}\n\n"

    response_text += "🏛️ *Financier & RTO*\n\n"
    response_text += f"*Financier Name:* {info.get('financier_name', 'Not Available')}\n"
    response_text += f"*RTO:* {info.get('rto', 'Not Available')}\n\n"

    response_text += "📍 *Address*\n\n"
    response_text += f"*Full Address:* {info.get('address', 'Not Available')}\n"
    response_text += f"*City:* {info.get('city', 'Not Available')}\n\n"

    response_text += "☎️ *Contact*\n\n"
    response_text += f"*Phone:* {info.get('phone', 'Not Available')}\n"

    return response_text

# === PAKISTAN SIM LOOKUP ===
def pak_sim_lookup(update, context, number):
    user_id = update.effective_user.id

    # Deduct credit
    user_credits[user_id] -= 1
    save_user_data()

    try:
        # Clean the number
        number = re.sub(r'\D', '', number)

        res = requests.get(API_URL_PAK_SIM + number, timeout=30, verify=False)
        if res.status_code == 200:
            try:
                data = res.json()

                if data and isinstance(data, dict):
                    # Format the response
                    formatted_response = format_pak_sim_response(data)
                    update.message.reply_text(formatted_response, parse_mode="Markdown")

                    # Print to console for debugging
                    print_pak_sim_results(data)
                else:
                    update.message.reply_text("❌ No SIM information found.")

            except json.JSONDecodeError:
                update.message.reply_text("❌ Invalid response from the SIM API.")
        else:
            update.message.reply_text(f"❌ SIM API Error: Status code {res.status_code}")
    except Exception as e:
        logger.error(f"SIM lookup error: {e}")
        update.message.reply_text("⚠️ An error occurred while processing your request.")

def format_pak_sim_response(info):
    response_text = "📱 *Pakistan SIM Info*\n\n"

    response_text += f"*Name:* {info.get('name', 'Not Available')}\n"
    response_text += f"*CNIC:* {info.get('cnic', 'Not Available')}\n"
    response_text += f"*Address:* {info.get('address', 'Not Available')}\n"

    if "number" in info:
        response_text += f"*Number:* {info.get('number', 'Not Available')}\n"
    else:
        response_text += "*Number:* Not Available\n"

    if "numbers" in info and isinstance(info["numbers"], list):
        response_text += "*All Numbers:* " + ", ".join(info["numbers"]) + "\n"
    else:
        response_text += "*All Numbers:* Not Available\n"

    response_text += f"*City:* {info.get('city', 'Not Available')}\n"
    response_text += f"*Province:* {info.get('province', 'Not Available')}\n"

    return response_text

# === MESSAGE HANDLER ===
def handle_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_credits:
        user_credits[user_id] = 2
        save_user_data()

    if user_id in banned_users:
        update.message.reply_text("🚫 You are banned from using this bot.")
        return

    lookup_type = context.user_data.get("lookup_type", "General Message")
    forward_to_owner(update.effective_user, text, lookup_type)

    if user_credits[user_id] <= 0:
        keyboard = [[InlineKeyboardButton("💰 Buy Credits", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")]]
        update.message.reply_text("💸 Buy credits first!", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if lookup_type == "Number Lookup":
        number_lookup(update, context, text)
    elif lookup_type == "Vehicle Lookup":
        vehicle_lookup(update, context, text)
    elif lookup_type == "Pakistan SIM Lookup":
        pak_sim_lookup(update, context, text)
    else:
        update.message.reply_text("📌 Type /start to begin or choose a lookup option.")

# === PRINT FUNCTIONS (For Console Output) ===
def print_number_results(data):
    for idx, info in enumerate(data, 1):
        name = info.get('name') or "N/A"
        father = info.get('fname') or info.get('father_name') or "N/A"
        address = info.get('address') or "N/A"
        mobile = info.get('mobile') or "N/A"
        alt = info.get('alt') or info.get('alt_mobile') or "N/A"
        circle = info.get('circle') or "N/A"
        id_number = info.get('id_number') or "N/A"
        email = info.get('email') or "N/A"

        if father == "N/A" and address != "N/A":
            match = re.search(r"(S/O|W/O)\s+([A-Za-z ]+)", address, re.IGNORECASE)
            if match:
                father = match.group(2).strip()

        print(f"\n\033[92m✅ Result {idx}\033[0m\n")
        print(f"\033[93m👤 Name:\033[0m {name}")
        print(f"\033[96m👨‍👦 Father:\033[0m {father}")
        print(f("\033[94m📍 Address:\033[0m {address}"))
        print(f("\033[92m📱 Mobile:\033[0m {mobile}")
        print(f("\033[91m☎️ Alternate:\033[0m {alt}")
        print(f("\033[95m🌍 Circle:\033[0m {circle}")
        print(f("\033[93m🆔 ID Number:\033[0m {id_number}")
        print(f("\033[96m✉️ Email:\033[0m {email}")
        print("\n\033[95m" + "="*40 + "\033[0m\n")

def print_vehicle_results(info):
    print("\n\033[92mVehicle Details  🚘\033[0m\n")
    print(f"RC Number: {info.get('rc_number','Not Available')}")
    print(f"Owner Name: {info.get('owner_name','Not Available')}")
    print(f"Father's Name: {info.get('father_name','Not Available')}")
    print(f"Owner Serial No.: {info.get('owner_serial_no','Not Available')}")
    print(f"Model Name: {info.get('model_name','Not Available')}")
    print(f"Maker/Model: {info.get('maker_model','Not Available')}")
    print(f"Vehicle Class: {info.get('vehicle_class','Not Available')}")
    print(f"Fuel Type: {info.get('fuel_type','Not Available')}")
    print(f"Fuel Norms: {info.get('fuel_norms','Not Available')}")
    print(f"Registration Date: {info.get('registration_date','Not Available')}")
    print("\n\033[96mInsurance Details 🛡️\033[0m\n")
    print(f"Company: {info.get('insurance_company','Not Available')}")
    print(f"Policy Number: {info.get('insurance_no','Not Available')}")
    print(f"Expiry Date: {info.get('insurance_expiry','Not Available')}")
    print(f"Valid Upto: {info.get('insurance_upto','Not Available')}")
    print("\n\033[95mFitness / Tax / PUC ✅\033[0m\n")
    print(f"Fitness Upto: {info.get('fitness_upto','Not Available')}")
    print(f"Tax Upto: {info.get('tax_upto','Not Available')}")
    print(f"PUC Number: {info.get('puc_no','Not Available')}")
    print(f"PUC Valid Upto: {info.get('puc_upto','Not Available')}")
    print("\n\033[93mFinancier & RTO 🏛️\033[0m\n")
    print(f"Financier Name: {info.get('financier_name','Not Available')}")
    print(f"RTO: {info.get('rto','Not Available')}")
    print("\n\033[94mAddress 📍\033[0m\n")
    print(f"Full Address: {info.get('address','Not Available')}")
    print(f"City: {info.get('city','Not Available')}")
    print("\n\033[91mContact ☎️\033[0m\n")
    print(f"Phone: {info.get('phone','Not Available')}")
    print("\n\033[95m" + "="*50 + "\033[0m\n")

def print_pak_sim_results(info):
    print("\n\033[92mPakistan SIM Info 📱\033[0m\n")
    print(f"Name: {info.get('name','Not Available')}")
    print(f"CNIC: {info.get('cnic','Not Available')}")
    print(f"Address: {info.get('address','Not Available')}")
    if "number" in info:
        print(f"Number: {info.get('number','Not Available')}")
    else:
        print("Number: Not Available")
    if "numbers" in info and isinstance(info["numbers"], list):
        print("All Numbers: " + ", ".join(info["numbers"]))
    else:
        print("All Numbers: Not Available")
    print(f"City: {info.get('city','Not Available')}")
    print(f"Province: {info.get('province','Not Available')}")
    print("\n\033[95m" + "="*50 + "\033[0m\n")

# === ADMIN COMMANDS ===
def add_credits(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        user_credits[target_id] = user_credits.get(target_id, 0) + amount
        save_user_data()
        update.message.reply_text(f"✅ Added {amount} credits to {target_id}. Balance: {user_credits[target_id]}")
    except Exception:
        update.message.reply_text("⚠️ Usage: /addcredits <user_id> <amount>")

def deduct_credits(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        user_credits[target_id] = max(0, user_credits.get(target_id, 0) - amount)
        save_user_data()
        update.message.reply_text(f"✅ Deducted {amount} credits from {target_id}. Balance: {user_credits[target_id]}")
    except Exception:
        update.message.reply_text("⚠️ Usage: /deductcredits <user_id> <amount>")

def user_credits_cmd(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        balance = user_credits.get(target_id, 0)
        update.message.reply_text(f"👤 User {target_id} has {balance} credits.")
    except Exception:
        update.message.reply_text("⚠️ Usage: /usercredits <user_id>")

def delete_user(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        if target_id in user_credits:
            del user_credits[target_id]
            save_user_data()
            update.message.reply_text(f"🗑️ Deleted user {target_id} from system.")
        else:
            update.message.reply_text("⚠️ User not found.")
    except Exception:
        update.message.reply_text("⚠️ Usage: /delete <user_id>")

def ban_user(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        banned_users.add(target_id)
        update.message.reply_text(f"⛔ User {target_id} has been banned.")
    except Exception:
        update.message.reply_text("⚠️ Usage: /ban <user_id>")

def unban_user(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        banned_users.discard(target_id)
        update.message.reply_text(f"✅ User {target_id} has been unbanned.")
    except Exception:
        update.message.reply_text("⚠️ Usage: /unban <user_id>")

def view_users(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    if not user_credits:
        update.message.reply_text("📭 No users in system yet.")
        return
    msg = "👥 *User List*\n\n"
    for uid, credits in user_credits.items():
        status = "🚫 Banned" if uid in banned_users else "✅ Active"
        msg += f"🆔 {uid} — Credits: {credits} — {status}\n"
    update.message.reply_text(msg, parse_mode="Markdown")

def broadcast(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        text = " ".join(context.args)
        if not text:
            update.message.reply_text("⚠️ Usage: /broadcast <message>")
            return
        for uid in user_credits.keys():
            if uid not in banned_users:
                try:
                    context.bot.send_message(chat_id=uid, text=f"MESSAGE BY OWNER:\n\n{text}")
                except Exception:
                    pass
        update.message.reply_text("✅ Broadcast sent to all active users.")
    except Exception as e:
        update.message.reply_text(f"⚠️ Error: {e}")

# === ERROR HANDLER (to avoid noisy logs) ===
def error_handler(update: object, context: CallbackContext) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    try:
        # notify admin
        err_text = f"⚠️ Error: {context.error}"
        context.bot.send_message(chat_id=OWNER_CHAT_ID, text=err_text)
    except Exception:
        pass

# === MAIN ===
def main():
    load_data()
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(CallbackQueryHandler(handle_callback))

    dp.add_handler(CommandHandler("addcredits", add_credits))
    dp.add_handler(CommandHandler("deductcredits", deduct_credits))
    dp.add_handler(CommandHandler("usercredits", user_credits_cmd))
    dp.add_handler(CommandHandler("delete", delete_user))
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CommandHandler("unban", unban_user))
    dp.add_handler(CommandHandler("view", view_users))
    dp.add_handler(CommandHandler("broadcast", broadcast))

    # Add error handler
    dp.add_error_handler(error_handler)

    print("✅ Bot is starting...")

    # === Webhook setup for Render ===
    PORT = int(os.environ.get("PORT", 8443))
    RENDER_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')

    if RENDER_HOSTNAME:
        WEBHOOK_URL = f"https://{RENDER_HOSTNAME}/{BOT_TOKEN}"
        print(f"🌐 Starting webhook at {WEBHOOK_URL}")
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=BOT_TOKEN)
        # Set webhook
        try:
            updater.bot.set_webhook(WEBHOOK_URL)
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
    else:
        # Local fallback to polling
        print("🧪 Local mode: starting polling")
        updater.start_polling()

    updater.idle()

if __name__ == "__main__":
    main()
