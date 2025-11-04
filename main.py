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
    # FIXED: Groups में भी काम करे
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        update.message.reply_text("📝 Please use this command in private chat with the bot for your profile details.")
        return
        
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
    # FIXED: Groups में भी काम करे
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        update.message.reply_text("🔗 Please use this command in private chat with the bot for referral details.")
        return
        
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
    # FIXED: Groups में भी काम करे
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        update.message.reply_text("💰 Please use this command in private chat with the bot for credit details.")
        return
        
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
    # FIXED: Groups में भी काम करे - channel verification skip करें
    chat_type = update.message.chat.type
    in_group = chat_type in ['group', 'supergroup']
    
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
        
    # Groups में channel verification skip करें
    if not in_group:
        # Private chat में channel verification check करें
        member1 = is_user_member_of(CHANNEL_1, user_id, context.bot)
        member2 = is_user_member_of(CHANNEL_2, user_id, context.bot)
        
        if not (member1 and member2):
            update.message.reply_text("⚠️ Please use /start and verify channel membership first.")
            return
        
        # Private chat में credits check करें
        balance = user_credits.get(user_id, 0)
        if balance <= 0:
            update.message.reply_text(
                f"❌ Not enough credits! Your current balance is {balance}.\n"
                f"💰 Buy credits from {ADMIN_USERNAME} or earn via /referral."
            )
            return
        
        # Private chat में credit deduct करें
        user_credits[user_id] = user_credits.get(user_id, 0) - 1
        save_user_data()

    update.message.reply_text(f"⏳ Searching number {number}...")
    number_lookup(update, context, number, in_group)

def quick_pak_sim_lookup(update: Update, context: CallbackContext):
    # FIXED: Groups में भी काम करे - channel verification skip करें
    chat_type = update.message.chat.type
    in_group = chat_type in ['group', 'supergroup']
    
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
        
    # Groups में channel verification skip करें
    if not in_group:
        # Private chat में channel verification check करें
        member1 = is_user_member_of(CHANNEL_1, user_id, context.bot)
        member2 = is_user_member_of(CHANNEL_2, user_id, context.bot)
        
        if not (member1 and member2):
            update.message.reply_text("⚠️ Please use /start and verify channel membership first.")
            return
        
        # Private chat में credits check करें
        balance = user_credits.get(user_id, 0)
        if balance <= 0:
            update.message.reply_text(
                f"❌ Not enough credits! Your current balance is {balance}.\n"
                f"💰 Buy credits from {ADMIN_USERNAME} or earn via /referral."
            )
            return
        
        # Private chat में credit deduct करें
        user_credits[user_id] = user_credits.get(user_id, 0) - 1
        save_user_data()

    update.message.reply_text(f"⏳ Searching Pakistan SIM {number}...")
    pak_sim_lookup(update, context, number, in_group)

def quick_aadhaar_lookup(update: Update, context: CallbackContext):
    # FIXED: Groups में भी काम करे
    chat_type = update.message.chat.type
    if chat_type in ['group', 'supergroup']:
        update.message.reply_text("🏠 *Aadhaar Lookup*\n\n⏳ This feature is coming soon! Stay tuned for updates.")
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
        
    # Check credits (only in private chat)
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
    # FIXED: Groups में simple message show करे
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

*Note:* For full features and menu, please message me privately.

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

# ... (rest of the callback handlers remain same)

# ================== LOOKUP FUNCTIONS ==================
def number_lookup(update: Update, context: CallbackContext, number: str, in_group=False):
    # FIXED: Groups में credit deduct नहीं करें
    if not in_group:
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
                        # FIXED: Always use custom credits instead of API credits
                        credit_info = "@Bossssss191"  # Your custom credit
                        developer_info = "@darkgp0"   # Your custom developer
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
    
    # FIXED: Always use custom credit information
    response_text += f"*Credits:* {credit_info}\n"
    response_text += f"*Developer:* {developer_info}\n"
    
    return response_text

def pak_sim_lookup(update: Update, context: CallbackContext, number: str, in_group=False):
    # FIXED: Groups में credit deduct नहीं करें
    if not in_group:
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
                    # FIXED: Always use custom credits
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
    # FIXED: Always use custom credits
    response_text += f"\n*Credits:* @Bossssss191\n"
    response_text += f"*Developer:* @darkgp0\n"
    return response_text

# ... (rest of the code remains same for vehicle lookup, admin commands, etc.)

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
