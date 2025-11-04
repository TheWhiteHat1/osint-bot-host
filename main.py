#!/usr/bin/env python3
# main.py - Render-ready Telegram OSINT bot (Fixed for Webhook/Render)

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

# Disable insecure request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================== CONFIGURATION ==================
BOT_TOKEN = os.getenv("BOT_TOKEN") 
OWNER_BOT_TOKEN = os.getenv("OWNER_BOT_TOKEN") or os.getenv("BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID")) if os.getenv("OWNER_CHAT_ID") else 0

ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME") or "@DARKGP0"
LOGO_URL = os.getenv("LOGO_URL") or "https://ibb.co/yc20Z7x1"

# Channels to require users to join (FIXED: Support both private and public)
CHANNEL_1 = os.getenv("CHANNEL_1") or "darkgp_in"
CHANNEL_2 = os.getenv("CHANNEL_2") or "darkgp_in2"

# APIs
API_URL = os.getenv("API_URL") or "https://seller-ki-mkc.taitanx.workers.dev/?mobile="
API_URL_VEHICLE = os.getenv("API_URL_VEHICLE") or "https://rc-info-ng.vercel.app/?rc="
API_URL_PAK_SIM = os.getenv("API_URL_PAK_SIM") or "https://allnetworkdata.com/?number="

WEBHOOK_DOMAIN = os.getenv("WEBHOOK_DOMAIN")

# === FILE STORAGE ===
USER_DATA_FILE = "user_data.json"
REFERRAL_DATA_FILE = "referral_data.json"
BANNED_USERS_FILE = "banned_users.json"

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
    global user_credits, referral_data, banned_users
    
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r") as f:
                raw = json.load(f)
                user_credits = {int(k): v for k, v in raw.items()}
        except Exception as e:
            logger.error(f"Error loading {USER_DATA_FILE}: {e}")
            user_credits = {}
    else:
        user_credits = {}

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

    if os.path.exists(BANNED_USERS_FILE):
        try:
            with open(BANNED_USERS_FILE, "r") as f:
                banned_list = json.load(f)
                banned_users = set(banned_list)
        except Exception as e:
            logger.error(f"Error loading {BANNED_USERS_FILE}: {e}")
            banned_users = set()
    else:
        banned_users = set()

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

def save_banned_users():
    try:
        with open(BANNED_USERS_FILE, "w") as f:
            json.dump(list(banned_users), f)
    except Exception as e:
        logger.error(f"Error saving banned users: {e}")

# ================== UTILS ==================
def forward_to_owner(user, message, lookup_type="General Message"):
    try:
        user_id = user.id
        username = user.username if user.username else "N/A"
        first_name = user.first_name or "N/A"
        text = (
            f"👤 User: {username}\n"
            f"📛 Name: {first_name}\n"
            f"🆔 ID: {user_id}\n"
            f"💬 Message: {message}\n"
            f"🛠 Used: {lookup_type}"
        )
        if OWNER_BOT_TOKEN and OWNER_CHAT_ID:
            url = f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": OWNER_CHAT_ID, "text": text})
    except Exception as e:
        logger.error(f"Failed to forward to owner: {e}")

# FIXED: Channel membership check for both private and public channels
def is_user_member_of(chat_identifier, user_id, bot):
    try:
        # Try with @ prefix first
        try:
            member = bot.get_chat_member("@" + chat_identifier, user_id)
            if member and member.status not in ("left", "kicked"):
                return True
        except TelegramError:
            # If @ fails, try without @ (for private channels/groups)
            try:
                member = bot.get_chat_member(chat_identifier, user_id)
                if member and member.status not in ("left", "kicked"):
                    return True
            except TelegramError:
                return False
        return False
    except TelegramError as e:
        logger.info(f"get_chat_member error for {chat_identifier}: {e}")
        return False

def is_bot_admin_in(chat_identifier, bot):
    try:
        me = bot.get_me()
        # Try with @ prefix first
        try:
            member = bot.get_chat_member("@" + chat_identifier, me.id)
            if member and member.status == "administrator":
                return True
        except TelegramError:
            # If @ fails, try without @
            try:
                member = bot.get_chat_member(chat_identifier, me.id)
                if member and member.status == "administrator":
                    return True
            except TelegramError:
                return False
        return False
    except TelegramError as e:
        logger.info(f"Bot admin check error for {chat_identifier}: {e}")
        return False

def _safe_edit_or_reply(query, text, parse_mode="Markdown", reply_markup=None):
    try:
        query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest as e:
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

# ================== COMMAND HANDLERS ==================
def help_command(update: Update, context: CallbackContext):
    help_text = """
🤖 *DARK GP OSINT Bot Help*

*Available Commands:*
/start - Start the bot
/help - Show this help message  
/profile - Check your profile and credits
/referral - Get your referral link
/credits - Check your credit balance

*Quick Search Commands:*
/num <number> - Quick number lookup
/paknum <number> - Quick Pakistan SIM lookup
/aadhaar <number> - Quick Aadhaar lookup (Coming Soon)

*Lookup Services:*
• 📱 Number Lookup
• 🚘 Vehicle RC Lookup  
• 🇵🇰 Pakistan SIM Info

*How to Use:*
1. Use /start to begin OR use quick commands
2. Select a lookup service
3. Send the required information
4. Get instant results!

*Credits System:*
- Start with 2 free credits
- Earn 1 credit per referral
- Buy more credits from admin

*Support:* {}
    """.format(ADMIN_USERNAME)
    
    update.message.reply_text(help_text, parse_mode="Markdown")

def profile_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    balance = user_credits.get(user_id, 0)
    username = update.effective_user.username or "Not set"
    first_name = update.effective_user.first_name or "Not set"
    
    profile_text = f"""
👤 *User Profile*

📛 *Name:* {first_name}
🔖 *Username:* @{username}
🆔 *User ID:* `{user_id}`
💰 *Credits:* {balance}

*Referral Stats:*
• Total Referrals: {sum(1 for ref in referral_data.values() if ref == user_id)}
• Referral Link: `https://t.me/{context.bot.username}?start={user_id}`
    """
    
    update.message.reply_text(profile_text, parse_mode="Markdown")

def referral_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    ref_link = f"https://t.me/{context.bot.username}?start={user_id}"
    referral_count = sum(1 for ref in referral_data.values() if ref == user_id)
    
    ref_text = f"""
🔗 *Referral Program*

Invite friends and earn *+1 credit* for each successful referral!

*Your Referral Link:*
`{ref_link}`

*Your Referral Stats:*
• Total Referrals: {referral_count}
• Credits Earned: {referral_count}

*How it works:*
1. Share your referral link
2. When someone joins using your link
3. You automatically get +1 credit
4. They get started with 2 credits

Start inviting and earn free credits! 🎁
    """
    
    update.message.reply_text(ref_text, parse_mode="Markdown")

def credits_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    balance = user_credits.get(user_id, 0)
    
    credits_text = f"""
💰 *Credit Balance*

*Current Credits:* {balance}

*Ways to Get Credits:*
• 🎁 Start bonus: 2 credits
• 🔗 Referral: +1 credit per referral  
• 💰 Purchase from admin

*Credit Usage:*
• Each lookup costs 1 credit
• Check balance before searching

*Need more credits?*
Contact {ADMIN_USERNAME}
    """
    
    update.message.reply_text(credits_text, parse_mode="Markdown")

# ================== QUICK COMMAND HANDLERS ==================
def quick_number_lookup(update: Update, context: CallbackContext):
    # FIXED: Check if in group - skip channel verification in groups
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        update.message.reply_text("❌ Please use this command in private chat with the bot.")
        return
        
    user_id = update.effective_user.id
    
    if user_id in banned_users:
        update.message.reply_text("⛔ You are banned from using this bot.")
        return

    if not context.args:
        update.message.reply_text("⚠️ Usage: /num <phone_number>\nExample: /num 9876543210")
        return
    
    number = context.args[0]
    
    if not number.isdigit():
        update.message.reply_text("❌ Please enter a valid phone number (digits only)")
        return
        
    # Check credits
    balance = user_credits.get(user_id, 0)
    if balance <= 0:
        update.message.reply_text(
            f"❌ Not enough credits! Your current balance is {balance}.\n"
            f"💰 Buy credits from {ADMIN_USERNAME} or earn via /referral."
        )
        return

    update.message.reply_text(f"⏳ Quick searching number {number}...")
    number_lookup(update, context, number)

def quick_pak_sim_lookup(update: Update, context: CallbackContext):
    # FIXED: Check if in group - skip channel verification in groups
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        update.message.reply_text("❌ Please use this command in private chat with the bot.")
        return
        
    user_id = update.effective_user.id
    
    if user_id in banned_users:
        update.message.reply_text("⛔ You are banned from using this bot.")
        return

    if not context.args:
        update.message.reply_text("⚠️ Usage: /paknum <phone_number>\nExample: /paknum 03001234567")
        return
    
    number = context.args[0]
    
    if not number.isdigit():
        update.message.reply_text("❌ Please enter a valid phone number (digits only)")
        return
        
    # Check credits
    balance = user_credits.get(user_id, 0)
    if balance <= 0:
        update.message.reply_text(
            f"❌ Not enough credits! Your current balance is {balance}.\n"
            f"💰 Buy credits from {ADMIN_USERNAME} or earn via /referral."
        )
        return

    update.message.reply_text(f"⏳ Quick searching Pakistan SIM {number}...")
    pak_sim_lookup(update, context, number)

def quick_aadhaar_lookup(update: Update, context: CallbackContext):
    # FIXED: Check if in group - skip channel verification in groups
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        update.message.reply_text("❌ Please use this command in private chat with the bot.")
        return
        
    user_id = update.effective_user.id
    
    if user_id in banned_users:
        update.message.reply_text("⛔ You are banned from using this bot.")
        return

    if not context.args:
        update.message.reply_text("⚠️ Usage: /aadhaar <aadhaar_number>\nExample: /aadhaar 123456789012")
        return
    
    aadhaar = context.args[0]
    
    if not aadhaar.isdigit() or len(aadhaar) != 12:
        update.message.reply_text("❌ Please enter a valid 12-digit Aadhaar number")
        return
        
    # Check credits
    balance = user_credits.get(user_id, 0)
    if balance <= 0:
        update.message.reply_text(
            f"❌ Not enough credits! Your current balance is {balance}.\n"
            f"💰 Buy credits from {ADMIN_USERNAME} or earn via /referral."
        )
        return

    update.message.reply_text("🏠 *Aadhaar Lookup*\n\n⏳ This feature is coming soon! Stay tuned for updates.")

# ================== MAIN HANDLERS ==================
def start(update: Update, context: CallbackContext):
    # FIXED: Check if in group - show simple message in groups
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        group_help = f"""
🤖 *DARK GP OSINT Bot*

Hello! I'm an OSINT information bot.

*Available Commands:*
/num <number> - Number lookup
/paknum <number> - Pakistan SIM lookup  
/aadhaar <number> - Aadhaar lookup (Coming Soon)
/help - Show help

*Note:* For full features, please message me privately.

*Support:* {ADMIN_USERNAME}
        """
        update.message.reply_text(group_help, parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    args = context.args
    logger.info(f"Start command received from user {user_id}")

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

    # FIXED: Channel check with both @ and without @
    member1 = is_user_member_of(CHANNEL_1, user_id, context.bot)
    member2 = is_user_member_of(CHANNEL_2, user_id, context.bot)

    # Check if user is already a member (skip join prompt)
    if member1 and member2:
        _send_welcome(update, context, use_reply=True)
        return

    # Clean channel names for URLs
    channel1_clean = CHANNEL_1.replace('@', '')
    channel2_clean = CHANNEL_2.replace('@', '')

    # Prompt user to join channels first
    keyboard_join = [
        [InlineKeyboardButton("📢 Join Channel 1", url=f"https://t.me/{channel1_clean}")],
        [InlineKeyboardButton("📢 Join Channel 2", url=f"https://t.me/{channel2_clean}")],
        [InlineKeyboardButton("✅ Verify Joined Channels", callback_data="verify_channels")]
    ]
    join_markup = InlineKeyboardMarkup(keyboard_join)

    caption = f"""⚠️ *Please Join Our Channels*

To use this bot, you need to join both of our channels:

• *Channel 1:* @{CHANNEL_1.replace('@', '')}
• *Channel 2:* @{CHANNEL_2.replace('@', '')}

After joining, tap *Verify Joined Channels* below.
"""
    try:
        update.message.reply_photo(photo=LOGO_URL, caption=caption, parse_mode="Markdown", reply_markup=join_markup)
    except Exception:
        update.message.reply_text(caption, parse_mode="Markdown", reply_markup=join_markup)

def _send_welcome(update: Update, context: CallbackContext, use_reply=False):
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
        [InlineKeyboardButton("💰 Buy Credits", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
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

def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        query.answer()
    except Exception:
        pass

    user_id = query.from_user.id
    
    # For verify_channels, always allow
    if query.data == "verify_channels":
        _handle_verify_channels(query, context)
        return
        
    # For other actions, check membership
    member1 = is_user_member_of(CHANNEL_1, user_id, context.bot)
    member2 = is_user_member_of(CHANNEL_2, user_id, context.bot)
    
    if not (member1 and member2):
        _safe_edit_or_reply(query, "⚠️ Please use /start and *Verify Joined Channels* first to use the bot functions.")
        return

    context.user_data.clear()

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
            username = query.from_user.username or "Not set"
            _safe_edit_or_reply(query, f"👤 *Profile*\n\n📛 Name: {query.from_user.first_name}\n🔖 Username: @{username}\n🆔 ID: `{query.from_user.id}`\n💰 Credits: {balance}")
        elif query.data == "referral":
            ref_link = f"https://t.me/{context.bot.username}?start={query.from_user.id}"
            referral_count = sum(1 for ref in referral_data.values() if ref == query.from_user.id)
            _safe_edit_or_reply(query, f"🔗 *Referral Program*\n\nInvite friends & earn free coins!\n\n👉 `{ref_link}`\n\n📊 Your Referrals: {referral_count}\n💰 Credits Earned: {referral_count}\n\n_You get +1 credit for every successful referral._")
        elif query.data == "help":
            help_text = """
🤖 *Available Lookup Services:*

• 📱 *Number Lookup* - Get mobile number details
• 🚘 *Vehicle Lookup* - Vehicle RC information  
• 🇵🇰 *Pakistan SIM* - SIM card details

*Quick Commands:*
/num <number> - Quick number search
/paknum <number> - Quick Pakistan SIM search
/aadhaar <number> - Aadhaar search (Coming Soon)

*How to Use:*
1. Select a lookup service
2. Send the required data
3. Get instant results!

*Credits:* Each lookup costs 1 credit
*Support:* {ADMIN_USERNAME}
            """.format(ADMIN_USERNAME=ADMIN_USERNAME)
            _safe_edit_or_reply(query, help_text)
        else:
            _safe_edit_or_reply(query, "Unknown action.")
    except Exception as e:
        logger.error(f"Error in handle_callback: {e}")
        _safe_edit_or_reply(query, "⚠️ An error occurred handling your action.")

def _handle_verify_channels(query, context):
    user_id = query.from_user.id
    bot = context.bot

    # FIXED: Channel check with both @ and without @
    member1 = is_user_member_of(CHANNEL_1, user_id, bot)
    member2 = is_user_member_of(CHANNEL_2, user_id, bot)

    if member1 and member2:
        try:
            query.edit_message_caption("✅ Verification successful! Sending main menu...", parse_mode="Markdown")
        except BadRequest:
            query.message.reply_text("✅ Verification successful! Sending main menu...")
        
        _send_welcome(update=query, context=context, use_reply=False)
    else:
        missing = []
        if not member1:
            missing.append("@" + CHANNEL_1.replace('@', ''))
        if not member2:
            missing.append("@" + CHANNEL_2.replace('@', ''))
        
        msg = "❌ *Verification Failed*\n\nYou need to join both channels:\n"
        for ch in missing:
            msg += f"• {ch}\n"
        msg += "\nPlease join them and tap *Verify Joined Channels* again."
        
        _safe_edit_or_reply(query, msg)

def handle_text_message(update: Update, context: CallbackContext):
    # FIXED: Check if in group - skip processing in groups
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        return
        
    user_id = update.effective_user.id
    text = update.message.text.strip()
    lookup_type = context.user_data.get("lookup_type")

    if user_id in banned_users:
        update.message.reply_text("⛔ You are banned from using this bot.")
        return

    # FIXED: Channel check with both @ and without @
    member1 = is_user_member_of(CHANNEL_1, user_id, context.bot)
    member2 = is_user_member_of(CHANNEL_2, user_id, context.bot)
    
    if not (member1 and member2):
        update.message.reply_text("⚠️ Please use the /start command and *Verify Joined Channels* first to use the bot.")
        return
        
    if lookup_type:
        balance = user_credits.get(user_id, 0)
        if balance <= 0:
            update.message.reply_text(
                f"❌ Not enough credits! Your current balance is {balance}.\n"
                f"💰 Buy credits from {ADMIN_USERNAME} or earn via /referral."
            )
            return

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
        update.message.reply_text("⚠️ Please use the menu buttons to select a lookup type first. Type /start for the menu.")
    
    if lookup_type:
        context.user_data.clear()

# ================== LOOKUP FUNCTIONS ==================
def number_lookup(update: Update, context: CallbackContext, number: str):
    user_id = update.effective_user.id
    user_credits[user_id] = user_credits.get(user_id, 0) - 1
    save_user_data()

    try:
        number = re.sub(r'\D', '', number)
        url = API_URL + number
        logger.info(f"Making API request to: {url}")
        
        res = requests.get(url, timeout=30, verify=False)
        logger.info(f"API response status: {res.status_code}")
        
        if res.status_code == 200:
            try:
                data = res.json()
                logger.info(f"API response data: {data}")
                
                if data:
                    # FIXED: Handle both direct array and nested data structure
                    if isinstance(data, dict) and 'data' in data:
                        # API returns {"data": [...], "credit": "...", "developer": "..."}
                        data_list = data['data']
                        credit_info = data.get('credit', '@oxmzoo')
                        developer_info = data.get('developer', '@oxmzoo')
                    elif isinstance(data, list):
                        # API returns direct array
                        data_list = data
                        credit_info = "@Bossssss191"  # Your custom credit
                        developer_info = "@darkgp0"   # Your custom developer
                    elif isinstance(data, dict):
                        # Single result as dict
                        data_list = [data]
                        credit_info = "@Bossssss191"
                        developer_info = "@darkgp0"
                    else:
                        data_list = []
                        credit_info = "@Bossssss191"
                        developer_info = "@darkgp0"

                    if data_list:
                        formatted_response = format_number_response(data_list, credit_info, developer_info)
                        update.message.reply_text(formatted_response, parse_mode="Markdown")
                        print_number_results(data_list)
                    else:
                        update.message.reply_text("❌ No information found for this number.")
                else:
                    update.message.reply_text("❌ No information found for this number.")
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                update.message.reply_text("❌ Invalid response from the API server.")
            except Exception as e:
                logger.error(f"Error processing API response: {e}")
                update.message.reply_text("❌ Error processing API response.")
        else:
            update.message.reply_text(f"❌ API Error: Status code {res.status_code}")
    except Exception as e:
        logger.error(f"Number lookup error: {e}")
        update.message.reply_text("⚠️ An error occurred while processing your request.")

# FIXED: Updated format_number_response with custom credits
def format_number_response(data, credit_info="@Bossssss191", developer_info="@darkgp0"):
    response_text = "🔍 *Number Lookup Results*\n\n"
    
    for idx, info in enumerate(data, 1):
        if not isinstance(info, dict):
            try:
                info = dict(info)
            except:
                info = {}

        # FIXED: Extract fields properly from API response
        name = info.get('name') or "N/A"
        father = info.get('fname') or info.get('father_name') or "N/A"
        address = info.get('address') or "N/A"
        mobile = info.get('mobile') or "N/A"
        alt = info.get('alt') or info.get('alt_mobile') or "N/A"
        circle = info.get('circle') or "N/A"
        id_number = info.get('id') or info.get('id_number') or "N/A"
        email = info.get('email') or "N/A"

        # Extract father name from address if not available
        if father == "N/A" and address != "N/A":
            match = re.search(r"(S/O|W/O|s/o|w/o)\s+([A-Za-z ]+)", address, re.IGNORECASE)
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
        if email != "N/A":
            response_text += f"✉️ *Email:* {email}\n"
        response_text += "\n" + "━" * 30 + "\n\n"
    
    # FIXED: Add custom credit information
    response_text += f"*Credits:* {credit_info}\n"
    response_text += f"*Developer:* {developer_info}\n"
    
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
    # FIXED: Add custom credits
    response_text += f"\n*Credits:* @Bossssss191\n"
    response_text += f"*Developer:* @darkgp0\n"
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
    # FIXED: Add custom credits
    response_text += f"\n*Credits:* @Bossssss191\n"
    response_text += f"*Developer:* @darkgp0\n"
    return response_text

# ================== ADMIN COMMANDS ==================
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
        save_banned_users()
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
            save_banned_users()
            update.message.reply_text(f"✅ User {target_id} has been unbanned.")
        else:
            update.message.reply_text("⚠️ User not banned.")
    except Exception:
        update.message.reply_text("⚠️ Usage: /unban <user_id>")

def broadcast(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    
    if not context.args:
        update.message.reply_text("⚠️ Usage: /broadcast <message>")
        return
    
    message = " ".join(context.args)
    success_count = 0
    fail_count = 0
    
    for user_id in user_credits.keys():
        try:
            context.bot.send_message(user_id, f"📢 *Broadcast Message*\n\n{message}", parse_mode="Markdown")
            success_count += 1
        except Exception as e:
            fail_count += 1
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
    
    update.message.reply_text(f"📊 Broadcast Results:\n✅ Success: {success_count}\n❌ Failed: {fail_count}")

def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    
    total_users = len(user_credits)
    total_credits = sum(user_credits.values())
    banned_count = len(banned_users)
    referral_count = len(referral_data)
    
    stats_text = f"""
📊 *Bot Statistics*

👥 Total Users: {total_users}
💰 Total Credits: {total_credits}
⛔ Banned Users: {banned_count}
🔗 Referrals: {referral_count}

*Top 5 Users by Credits:*
"""
    
    # Get top 5 users by credits
    top_users = sorted(user_credits.items(), key=lambda x: x[1], reverse=True)[:5]
    for i, (user_id, credits) in enumerate(top_users, 1):
        stats_text += f"{i}. User {user_id}: {credits} credits\n"
    
    update.message.reply_text(stats_text, parse_mode="Markdown")

# ================== CONSOLE PRINT FUNCTIONS ==================
def print_number_results(data):
    for idx, info in enumerate(data, 1):
        name = info.get('name') or "N/A"
        father = info.get('fname') or info.get('father_name') or "N/A"
        address = info.get('address') or "N/A"
        mobile = info.get('mobile') or "N/A"
        alt = info.get('alt') or info.get('alt_mobile') or "N/A"
        circle = info.get('circle') or "N/A"
        id_number = info.get('id') or info.get('id_number') or "N/A"
        email = info.get('email') or "N/A"

        if father == "N/A" and address != "N/A":
            match = re.search(r"(S/O|W/O|s/o|w/o)\s+([A-Za-z ]+)", address, re.IGNORECASE)
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

# ================== MAIN EXECUTION BLOCK ==================
def main():
    """Start the bot using Webhook mode for Render."""
    load_data()
    
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN not set. Exiting.")
        sys.exit(1)

    if not WEBHOOK_DOMAIN:
        logger.warning("WEBHOOK_DOMAIN not set. Using polling mode as fallback.")
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher

        # Add ALL handlers
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("profile", profile_command))
        dp.add_handler(CommandHandler("referral", referral_command))
        dp.add_handler(CommandHandler("credits", credits_command))
        
        # FIXED: Add quick command handlers
        dp.add_handler(CommandHandler("num", quick_number_lookup))
        dp.add_handler(CommandHandler("paknum", quick_pak_sim_lookup))
        dp.add_handler(CommandHandler("aadhaar", quick_aadhaar_lookup))
        
        # Admin commands
        dp.add_handler(CommandHandler("addcredits", add_credits))
        dp.add_handler(CommandHandler("deductcredits", deduct_credits))
        dp.add_handler(CommandHandler("usercredits", user_credits_cmd))
        dp.add_handler(CommandHandler("delete", delete_user))
        dp.add_handler(CommandHandler("ban", ban_user))
        dp.add_handler(CommandHandler("unban", unban_user))
        dp.add_handler(CommandHandler("broadcast", broadcast))
        dp.add_handler(CommandHandler("stats", stats))
        
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))
        dp.add_handler(CallbackQueryHandler(handle_callback))

        logger.info("Starting bot with POLLING mode...")
        updater.start_polling()
        updater.idle()
        return

    # Webhook mode
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Add ALL handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("profile", profile_command))
    dp.add_handler(CommandHandler("referral", referral_command))
    dp.add_handler(CommandHandler("credits", credits_command))
    
    # FIXED: Add quick command handlers
    dp.add_handler(CommandHandler("num", quick_number_lookup))
    dp.add_handler(CommandHandler("paknum", quick_pak_sim_lookup))
    dp.add_handler(CommandHandler("aadhaar", quick_aadhaar_lookup))
    
    # Admin commands
    dp.add_handler(CommandHandler("addcredits", add_credits))
    dp.add_handler(CommandHandler("deductcredits", deduct_credits))
    dp.add_handler(CommandHandler("usercredits", user_credits_cmd))
    dp.add_handler(CommandHandler("delete", delete_user))
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CommandHandler("unban", unban_user))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(CommandHandler("stats", stats))
    
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))
    dp.add_handler(CallbackQueryHandler(handle_callback))

    PORT = int(os.environ.get('PORT', 5000))
    WEBHOOK_PATH = BOT_TOKEN
    WEBHOOK_URL = f"{WEBHOOK_DOMAIN}/{WEBHOOK_PATH}"

    logger.info(f"Starting bot with Webhook mode on PORT: {PORT}")
    logger.info(f"Webhook URL set to: {WEBHOOK_URL}")

    try:
        updater.bot.set_webhook(url=WEBHOOK_URL)
        logger.info("Webhook set successfully!")
        
        updater.start_webhook(
            listen="0.0.0.0", 
            port=PORT, 
            url_path=WEBHOOK_PATH,
            webhook_url=WEBHOOK_URL
        )
        logger.info("Webhook server started successfully!")
        updater.idle()
    except Exception as e:
        logger.critical(f"Failed to start bot via webhook: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
