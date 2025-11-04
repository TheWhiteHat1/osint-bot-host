#!/usr/bin/env python3
# main.py - Render-ready Telegram OSINT bot (Fixed for Webhook/Render)
# Requirements: python-telegram-bot==13.15, requests, APScheduler, pytz, tzlocal, tornado, etc.

import json
import os
import re
import logging
import requests
import urllib3
import sys
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from telegram.error import BadRequest, TelegramError

# Disable insecure request warnings for third-party APIs (we use verify=False in some requests)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================== CONFIGURATION ==================
# Note: For production, you should store these in environment variables and not in source code.
BOT_TOKEN = os.getenv("BOT_TOKEN") 
OWNER_BOT_TOKEN = os.getenv("OWNER_BOT_TOKEN") 
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID")) if os.getenv("OWNER_CHAT_ID") else 0

ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME") or "@DARKGP0"
LOGO_URL = os.getenv("LOGO_URL") or "https://ibb.co/yc20Z7x1" # Note: This URL might need to be a direct image link

# Channels to require users to join before showing full welcome (replace with real channel usernames)
CHANNEL_1 = os.getenv("CHANNEL_1") or "@channel1_username"
CHANNEL_2 = os.getenv("CHANNEL_2") or "@channel2_username"

# APIs
API_URL = os.getenv("API_URL") or "https://seller-ki-mkc.taitanx.workers.dev/?mobile="  # NEW API no key required
API_URL_VEHICLE = os.getenv("API_URL_VEHICLE") or "https://rc-info-ng.vercel.app/?rc="
API_URL_PAK_SIM = os.getenv("API_URL_PAK_SIM") or "https://allnetworkdata.com/?number="

# Render webhook domain (your Render app URL) - MUST BE SET IN ENVIRONMENT VARIABLES
WEBHOOK_DOMAIN = os.getenv("WEBHOOK_DOMAIN") # e.g., https://osint-bot-host-3.onrender.com

# --- RENDER WEBHOOK PORT ---
# Render assigns a dynamic port that must be listened to.
PORT = int(os.environ.get('PORT', 5000))

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

# ================== PERSISTENCE ==================
def load_data():
    global user_credits, referral_data
    # Load user credits
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r") as f:
                raw = json.load(f)
                # convert keys to int
                user_credits = {int(k): v for k, v in raw.items()}
        except Exception as e:
            logger.error(f"Error loading {USER_DATA_FILE}: {e}")
            user_credits = {}
    else:
        user_credits = {}

    # Load referrals
    if os.path.exists(REFERRAL_DATA_FILE):
        try:
            with open(REFERRAL_DATA_FILE, "r") as f:
                raw = json.load(f)
                referral_data = {int(k): int(v) for k, v in raw.items()}
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

# ================== UTILS ==================
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

# Channel membership check helpers
def is_user_member_of(chat_identifier, user_id, bot):
    """
    Returns True if user_id is a member of chat_identifier (username or id).
    """
    try:
        member = bot.get_chat_member(chat_identifier, user_id)
        if member and member.status not in ("left", "kicked"):
            return True
        return False
    except TelegramError as e:
        logger.info(f"get_chat_member error for {chat_identifier}: {e}")
        return False

def is_bot_admin_in(chat_identifier, bot):
    """
    Returns True if our bot is admin in the channel.
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

# Safe edit or reply for callback queries
def _safe_edit_or_reply(query, text, parse_mode="Markdown", reply_markup=None):
    try:
        query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest as e:
        # If message is not modified, try to reply
        if "Message is not modified" in str(e):
             query.answer("No change.")
             return
        
        try:
            query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Fallback reply failed: {e2}")
    except Exception as e:
        logger.error(f"edit_message_text failed: {e}")
        try:
            query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Fallback reply failed: {e2}")

# ================== HANDLERS ==================

# /start - show join channels prompt first
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    args = context.args

    # Handle referral param
    if args and args[0].isdigit():
        referrer_id = int(args[0])
        if user_id not in referral_data and referrer_id != user_id:
            referral_data[user_id] = referrer_id
            save_referral_data()
            if referrer_id in user_credits:
                user_credits[referrer_id] = user_credits.get(referrer_id, 0) + 1
                save_user_data()
                try:
                    context.bot.send_message(referrer_id, "🎁 Congratulations! A new user joined using your referral link. You received 1 credit!")
                except Exception:
                    pass

    # Initialize credits if new
    if user_id not in user_credits:
        user_credits[user_id] = 2
        save_user_data()

    # Clear user_data for fresh start
    context.user_data.clear()

    # Check if user is already a member (skip join prompt)
    if is_user_member_of(CHANNEL_1, user_id, context.bot) and is_user_member_of(CHANNEL_2, user_id, context.bot):
        _send_welcome(update, context, use_reply=True)
        return

    # Prompt user to join channels first
    keyboard_join = [
        [InlineKeyboardButton(f"Join Channel 1 {CHANNEL_1}", url=f"https://t.me/{CHANNEL_1.replace('@','')}")],
        [InlineKeyboardButton(f"Join Channel 2 {CHANNEL_2}", url=f"https://t.me/{CHANNEL_2.replace('@','')}")],
        [InlineKeyboardButton("🔁 Verify Joined Channels", callback_data="verify_channels")]
    ]
    join_markup = InlineKeyboardMarkup(keyboard_join)

    caption = "⚠️ Please join both channels below to use the bot. After joining, tap *Verify Joined Channels*."
    try:
        try:
            update.message.reply_photo(photo=LOGO_URL, caption=caption, parse_mode="Markdown", reply_markup=join_markup)
        except Exception:
            update.message.reply_text(caption, parse_mode="Markdown", reply_markup=join_markup)
    except Exception as e:
        logger.error(f"Error sending join prompt: {e}")
        _send_welcome(update, context, use_reply=True) # Fallback if error occurs

def _send_welcome(update: Update, context: CallbackContext, use_reply=False):
    """Sends the main welcome message (used after /start or verification)"""
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
        if use_reply and update.message:
            update.message.reply_photo(photo=LOGO_URL, caption=welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            context.bot.send_photo(chat_id=user_id, photo=LOGO_URL, caption=welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception:
        if use_reply and update.message:
            update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            context.bot.send_message(chat_id=user_id, text=welcome_text, parse_mode="Markdown", reply_markup=reply_markup)

# Callback handler for inline keyboard
def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        query.answer()
    except Exception:
        pass

    user_id = query.from_user.id
    # Check membership before allowing interaction
    if not (is_user_member_of(CHANNEL_1, user_id, context.bot) and is_user_member_of(CHANNEL_2, user_id, context.bot)):
        if query.data != "verify_channels":
            _safe_edit_or_reply(query, "⚠️ Please *Verify Joined Channels* first to use the bot functions.")
            return

    # clear previous lookup_type
    context.user_data.clear()

    if query.data == "verify_channels":
        _handle_verify_channels(query, context)
        return

    try:
        if query.data == "number_info":
            context.user_data["lookup_type"] = "Number Lookup"
            _safe_edit_or_reply(query, "📱 Send the phone number you want to search. (e.g., 9876543210)")
        elif query.data == "vehicle_info":
            context.user_data["lookup_type"] = "Vehicle Lookup"
            _safe_edit_or_reply(query, "🚘 Send the vehicle RC number you want to search. (e.g., DL3CBP1234)")
        elif query.data == "pak_sim_info":
            context.user_data["lookup_type"] = "Pakistan SIM Lookup"
            _safe_edit_or_reply(query, "🇵🇰 Send the Pakistan SIM number you want to search. (e.g., 03001234567)")
        elif query.data == "profile":
            balance = user_credits.get(query.from_user.id, 0)
            _safe_edit_or_reply(query, f"👤 Profile\n🆔 ID: {query.from_user.id}\n🔋 Credits: {balance}")
        elif query.data == "referral":
            ref_link = f"https://t.me/{context.bot.username}?start={query.from_user.id}"
            _safe_edit_or_reply(query, f"🔗 Invite friends & earn free coins!\n\n👉 `{ref_link}`\n\n_You get +1 credit for every successful referral._")
        else:
            _safe_edit_or_reply(query, "Unknown action.")
    except Exception as e:
        logger.error(f"Error in handle_callback: {e}")
        _safe_edit_or_reply(query, "⚠️ An error occurred handling your action.")

def _handle_verify_channels(query, context):
    user_id = query.from_user.id
    bot = context.bot

    # Check bot admin status in both channels
    bot_admin_1 = is_bot_admin_in(CHANNEL_1, bot)
    bot_admin_2 = is_bot_admin_in(CHANNEL_2, bot)

    if not bot_admin_1 or not bot_admin_2:
        msg = "⚠️ I need to be an *administrator* in both channels to verify users automatically.\n\n"
        if not bot_admin_1:
            msg += f"• Promote me to admin in {CHANNEL_1}\n"
        if not bot_admin_2:
            msg += f"• Promote me to admin in {CHANNEL_2}\n"
        _safe_edit_or_reply(query, msg)
        return

    # Check user membership
    member1 = is_user_member_of(CHANNEL_1, user_id, bot)
    member2 = is_user_member_of(CHANNEL_2, user_id, bot)

    if member1 and member2:
        # Edit the verification message to confirm success
        try:
             query.edit_message_caption("✅ You are verified and joined both channels. Sending main menu...", parse_mode="Markdown")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                 query.message.reply_text("✅ Verification successful. Sending main menu...")
            
        # Now send welcome to user (main menu)
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

        # Send the main menu
        try:
            context.bot.send_photo(chat_id=user_id, photo=LOGO_URL, caption=welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            try:
                context.bot.send_message(chat_id=user_id, text=welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Failed to send welcome after verify: {e}")
    else:
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

# --- NEW HANDLER FOR TEXT INPUT ---
def handle_text_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    lookup_type = context.user_data.get("lookup_type")

    # 1. Check if user is banned
    if user_id in banned_users:
        update.message.reply_text("⛔ You are banned from using this bot.")
        return

    # 2. Check membership (if not verified, prompt them)
    if not (is_user_member_of(CHANNEL_1, user_id, context.bot) and is_user_member_of(CHANNEL_2, user_id, context.bot)):
        update.message.reply_text("⚠️ Please use the /start command and *Verify Joined Channels* first to use the bot.")
        return
        
    # 3. Check credits (only if a lookup type is selected)
    if lookup_type:
        balance = user_credits.get(user_id, 0)
        if balance <= 0:
            update.message.reply_text(
                f"❌ Not enough credits! Your current balance is {balance}.\n"
                f"💰 Buy credits from {ADMIN_USERNAME} or earn via /referral."
            )
            return

    # 4. Process lookup
    forward_to_owner(update.effective_user, text, lookup_type or "General Query")

    if lookup_type == "Number Lookup" and text.isdigit():
        update.message.reply_text(f"⏳ Searching number {text}...")
        number_lookup(update, context, text)
    elif lookup_type == "Vehicle Lookup":
        update.message.reply_text(f"⏳ Searching vehicle RC {text}...")
        vehicle_lookup(update, context, text)
    elif lookup_type == "Pakistan SIM Lookup" and text.isdigit():
        update.message.reply_text(f"⏳ Searching Pak SIM {text}...")
        pak_sim_lookup(update, context, text)
    else:
        # Default message or help
        update.message.reply_text(
            "⚠️ Please use the menu buttons to select a lookup type first. Type /start for the menu."
        )
    
    # Clear the lookup type after use
    if lookup_type:
        context.user_data.clear()

# ================== LOOKUP FUNCTIONS (No change in logic) ==================
def number_lookup(update: Update, context: CallbackContext, number: str):
    user_id = update.effective_user.id

    # deduct credit safely
    user_credits[user_id] = user_credits.get(user_id, 0) - 1
    save_user_data()

    try:
        number = re.sub(r'\D', '', number)
        url = API_URL + number  # new API doesn't require key
        res = requests.get(url, timeout=30, verify=False)
        if res.status_code == 200:
            try:
                data = res.json()
                if data:
                    if isinstance(data, dict):
                        data_list = [data]
                    elif isinstance(data, list):
                        data_list = data
                    else:
                        data_list = [data]

                    formatted_response = format_number_response(data_list)
                    update.message.reply_text(formatted_response, parse_mode="Markdown")
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
        if not isinstance(info, dict):
            # Attempt to convert list/tuple of (key, value) pairs into dict
            try:
                info = dict(info)
            except:
                info = {} # Fallback to empty dict

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

def vehicle_lookup(update: Update, context: CallbackContext, rc: str):
    user_id = update.effective_user.id
    user_credits[user_id] = user_credits.get(user_id, 0) - 1
    save_user_data()

    try:
        res = requests.get(API_URL_VEHICLE + rc, timeout=30, verify=False)
        if res.status_code == 200:
            try:
                data = res.json()
                if data and isinstance(data, dict):
                    formatted_response = format_vehicle_response(data)
                    update.message.reply_text(formatted_response, parse_mode="Markdown")
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

def pak_sim_lookup(update: Update, context: CallbackContext, number: str):
    user_id = update.effective_user.id
    user_credits[user_id] = user_credits.get(user_id, 0) - 1
    save_user_data()

    try:
        number = re.sub(r'\D', '', number)
        res = requests.get(API_URL_PAK_SIM + number, timeout=30, verify=False)
        if res.status_code == 200:
            try:
                data = res.json()
                if data and isinstance(data, dict):
                    formatted_response = format_pak_sim_response(data)
                    update.message.reply_text(formatted_response, parse_mode="Markdown")
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

# ================== MESSAGES & PRINTS (console - No Change) ==================
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
        print(f"\033[94m📍 Address:\033[0m {address}")
        print(f"\033[92m📱 Mobile:\033[0m {mobile}")
        print(f"\033[91m☎️ Alternate:\033[0m {alt}")
        print(f"\033[95m🌍 Circle:\033[0m {circle}")
        print(f"\033[93m🆔 ID Number:\033[0m {id_number}")
        print(f"\033[96m✉️ Email:\033[0m {email}")
        print("\n\033[95m" + "="*40 + "\033[0m\n")

def print_vehicle_results(info):
    print("\n\033[92mVehicle Details 🚘\033[0m\n")
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

# ================== ADMIN COMMANDS (No Change) ==================
def add_credits(update: Update, context: CallbackContext):
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

def deduct_credits(update: Update, context: CallbackContext):
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

def user_credits_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        balance = user_credits.get(target_id, 0)
        update.message.reply_text(f"👤 User {target_id} has {balance} credits.")
    except Exception:
        update.message.reply_text("⚠️ Usage: /usercredits <user_id>")

def delete_user(update: Update, context: CallbackContext):
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

def ban_user(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        banned_users.add(target_id)
        update.message.reply_text(f"⛔ User {target_id} has been banned.")
    except Exception:
        update.message.reply_text("⚠️ Usage: /ban <user_id>")

def unban_user(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        if target_id in banned_users:
            banned_users.remove(target_id)
            update.message.reply_text(f"✅ User {target_id} has been unbanned.")
        else:
            update.message.reply_text("⚠️ User not banned.")
    except Exception:
        update.message.reply_text("⚠️ Usage: /unban <user_id>")

# ================== MAIN EXECUTION BLOCK (FIXED FOR RENDER WEBHOOK) ==================
def main():
    """Start the bot using Webhook mode for Render."""
    load_data()
    
    # Check for required environment variables
    if not BOT_TOKEN or not WEBHOOK_DOMAIN or not OWNER_CHAT_ID or not ADMIN_ID:
        logger.critical("Critical environment variables (BOT_TOKEN, WEBHOOK_DOMAIN, OWNER_CHAT_ID, ADMIN_ID) are not set. Exiting.")
        sys.exit(1)

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Add handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("addcredits", add_credits))
    dp.add_handler(CommandHandler("deductcredits", deduct_credits))
    dp.add_handler(CommandHandler("usercredits", user_credits_cmd))
    dp.add_handler(CommandHandler("delete", delete_user))
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CommandHandler("unban", unban_user))

    # Handles text messages which are assumed to be lookup queries
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))
    dp.add_handler(CallbackQueryHandler(handle_callback))

    # --- RENDER WEBHOOK CONFIGURATION ---
    # Telegram requires a specific path for the webhook URL
    WEBHOOK_PATH = BOT_TOKEN # Use the BOT_TOKEN as a unique path
    
    # Construct the full webhook URL for Telegram 
    WEBHOOK_URL = f"{WEBHOOK_DOMAIN}/{WEBHOOK_PATH}"

    logger.info(f"Starting bot with Webhook mode on PORT: {PORT}")
    logger.info(f"Webhook URL set to: {WEBHOOK_URL}")

    try:
        # Start the Webhook
        # listen="0.0.0.0" is necessary to listen on the correct network interface
        # port=PORT is the dynamic port assigned by Render
        # url_path=WEBHOOK_PATH is the secret path the bot listens on
        # webhook_url=WEBHOOK_URL is the URL Telegram is set to send updates to
        updater.start_webhook(
            listen="0.0.0.0", 
            port=PORT, 
            url_path=WEBHOOK_PATH, 
            webhook_url=WEBHOOK_URL
        )
        logger.info("Webhook successfully started and set!")
        updater.idle() # Keep the bot running
    except Exception as e:
        logger.critical(f"Failed to start bot via webhook: {e}")
        # Optionally, you can add a fallback to Polling here, but Render generally works better with Webhook.
        sys.exit(1)


if __name__ == '__main__':
    main()
