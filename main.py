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



# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === CONFIGURATION ===
API_URL = "https://xwalletbot.shop/number.php"
API_KEY = "MK103020070811"
API_URL_VEHICLE = "https://rc-info-ng.vercel.app/?rc="
API_URL_PAK_SIM = "https://allnetworkdata.com/?number="

BOT_TOKEN = "8257919061:AAFcvvTeInEqTGVNoM3sUzpZerewAgpo9NY"
OWNER_BOT_TOKEN = "7620271547:AAGOHb_1mH16270eUIj56oDdc2pB70MKs2U"
OWNER_CHAT_ID = 7985958385

ADMIN_ID = 7985958385
ADMIN_USERNAME = "@DARKGP0"
LOGO_URL = "https://ibb.co/yc20Z7x1"

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
            user_credits = json.load(f)
            user_credits = {int(k): v for k, v in user_credits.items()}
    else:
        user_credits = {}

    if os.path.exists(REFERRAL_DATA_FILE):
        with open(REFERRAL_DATA_FILE, "r") as f:
            referral_data = json.load(f)
            referral_data = {int(k): int(v) for k, v in referral_data.items()}
    else:
        referral_data = {}

def save_user_data():
    with open(USER_DATA_FILE, "w") as f:
        json.dump(user_credits, f)

def save_referral_data():
    with open(REFERRAL_DATA_FILE, "w") as f:
        json.dump(referral_data, f)

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
    except:
        update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)

# === CALLBACK HANDLER ===
def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    context.user_data.clear()

    if query.data == "number_info":
        context.user_data["lookup_type"] = "Number Lookup"
        query.edit_message_text("📱 Send the phone number you want to search.", parse_mode="Markdown")
    elif query.data == "vehicle_info":
        context.user_data["lookup_type"] = "Vehicle Lookup"
        query.edit_message_text("🚘 Send the vehicle RC number you want to search.", parse_mode="Markdown")
    elif query.data == "pak_sim_info":
        context.user_data["lookup_type"] = "Pakistan SIM Lookup"
        query.edit_message_text("🇵🇰 Send the Pakistan SIM number you want to search.", parse_mode="Markdown")
    elif query.data == "profile":
        balance = user_credits.get(query.from_user.id, 0)
        query.edit_message_text(f"👤 Profile\n🆔 ID: {query.from_user.id}\n🔋 Credits: {balance}", parse_mode="Markdown")
    elif query.data == "referral":
        ref_link = f"https://t.me/{context.bot.username}?start={query.from_user.id}"
        query.edit_message_text(f"🔗 Invite friends & earn free coins!\n👉 {ref_link}")

# === NUMBER LOOKUP FUNCTION ===
def number_lookup(update, context, number):
    user_id = update.effective_user.id
    
    # Deduct credit
    user_credits[user_id] -= 1
    save_user_data()
    
    try:
        # Clean the number
        number = re.sub(r'\D', '', number)
        
        # Make API request
        params = {
            'key': API_KEY,
            'number': number
        }
        
        res = requests.get(API_URL, params=params, timeout=30, verify=False)
        
        if res.status_code == 200:
            try:
                data = res.json()
                
                if data and isinstance(data, list) and len(data) > 0:
                    # Format the response
                    formatted_response = format_number_response(data)
                    update.message.reply_text(formatted_response, parse_mode="Markdown")
                    
                    # Print to console for debugging
                    print_number_results(data)
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
        print(f"\033[94m📍 Address:\033[0m {address}")
        print(f"\033[92m📱 Mobile:\033[0m {mobile}")
        print(f"\033[91m☎️ Alternate:\033[0m {alt}")
        print(f"\033[95m🌍 Circle:\033[0m {circle}")
        print(f"\033[93m🆔 ID Number:\033[0m {id_number}")
        print(f"\033[96m✉️ Email:\033[0m {email}")
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
    except:
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
    except:
        update.message.reply_text("⚠️ Usage: /deductcredits <user_id> <amount>")

def user_credits_cmd(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        balance = user_credits.get(target_id, 0)
        update.message.reply_text(f"👤 User {target_id} has {balance} credits.")
    except:
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
    except:
        update.message.reply_text("⚠️ Usage: /delete <user_id>")

def ban_user(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        banned_users.add(target_id)
        update.message.reply_text(f"⛔ User {target_id} has been banned.")
    except:
        update.message.reply_text("⚠️ Usage: /ban <user_id>")

def unban_user(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        banned_users.discard(target_id)
        update.message.reply_text(f"✅ User {target_id} has been unbanned.")
    except:
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
                except:
                    pass
        update.message.reply_text("✅ Broadcast sent to all active users.")
    except Exception as e:
        update.message.reply_text(f"⚠️ Error: {e}")

# === MAIN ===
def main():
    load_data()
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

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

    print("✅ Bot is running...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
