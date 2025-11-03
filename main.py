from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
import requests
import logging

# ================== CONFIG ==================
API_URL = "https://seller-ki-mkc.taitanx.workers.dev/?mobile="
BOT_TOKEN = "8257919061:AAFcvvTeInEqTGVNoM3sUzpZerewAgpo9NY"
ADMIN_ID = 7985958385
ADMIN_USERNAME = "@DARKGP0"

# ================== TEMP STORAGE ==================
user_credits = {}
banned_users = set()

# ================== LOGGING ==================
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== START COMMAND ==================
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    if user_id not in user_credits:
        user_credits[user_id] = 2

    if user_id in banned_users:
        update.message.reply_text("🚫 You are banned from using this bot.")
        return

    welcome_text = (
        "👋 *Welcome to DARK GP System*\n\n"
        "🔍 *OSINT Info Bot* — Get Number Details in Seconds 📱\n\n"
        "💰 *Credits System:*\n"
        "• 1 search = 1 credit\n"
        f"🔋 Your Credits: {user_credits[user_id]}\n\n"
        f"☎️ Support: {ADMIN_USERNAME}\n\n"
        "⚠️ Use this service lawfully."
    )

    keyboard = [
        [InlineKeyboardButton("📱 Number Lookup", callback_data="number_info")],
        [InlineKeyboardButton("📂 Profile", callback_data="profile")],
        [InlineKeyboardButton("🔗 Referral", callback_data="referral")],
        [InlineKeyboardButton("💰 Buy Credits", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")]
    ]
    update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ================== HELP ==================
def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📖 *Commands:*\n"
        "/start - Start bot\n"
        "/help - Show help\n"
        "/search <number> - Lookup number\n"
        "/credits - Show balance\n\n"
        "👨‍💻 *Admin Only:*\n"
        "/addcredits <id> <amt>\n"
        "/deductcredits <id> <amt>\n"
        "/usercredits <id>\n"
        "/ban <id>\n"
        "/unban <id>\n"
        "/broadcast <msg>",
        parse_mode="Markdown"
    )

# ================== CALLBACK ==================
def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    if user_id in banned_users:
        query.edit_message_text("🚫 You are banned.")
        return

    if query.data == "number_info":
        query.edit_message_text("📱 Send the *phone number* you want to search.", parse_mode="Markdown")

    elif query.data == "profile":
        balance = user_credits.get(user_id, 0)
        query.edit_message_text(f"👤 *Profile*\n🆔 ID: `{user_id}`\n🔋 Credits: {balance}", parse_mode="Markdown")

    elif query.data == "referral":
        query.edit_message_text(f"🔗 Invite friends!\n👉 https://t.me/{context.bot.username}?start={user_id}")

# ================== SEARCH ==================
def search_number(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id in banned_users:
        update.message.reply_text("🚫 You are banned.")
        return

    text = update.message.text.strip()
    if text.startswith("/search"):
        parts = text.split()
        if len(parts) < 2:
            update.message.reply_text("⚠️ Usage: /search <number>")
            return
        number = parts[1]
    else:
        number = text

    if user_id not in user_credits:
        user_credits[user_id] = 2

    if user_credits[user_id] <= 0:
        update.message.reply_text(
            "❌ No credits left.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Buy Credits", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")]])
        )
        return

    try:
        res = requests.get(API_URL + number, timeout=10)
        data = res.json()

        records = data.get("data", [])
        if isinstance(records, list) and len(records) > 0:
            results = []
            for idx, info in enumerate(records, 1):
                name = info.get("name", "N/A").strip()
                father = info.get("fname", info.get("father_name", "N/A")).strip()
                address = info.get("address", "N/A").replace("!", ", ").strip()
                mobile = info.get("mobile", "N/A")
                alt = info.get("alt", info.get("alt_mobile", "N/A"))
                circle = info.get("circle", "N/A").strip()
                id_number = info.get("id", info.get("id_number", "N/A"))
                email = info.get("email", "N/A").strip() or "N/A"

                msg = (
                    f"✅ *Result {idx}*\n\n"
                    f"👤 *Name:* {name}\n"
                    f"👨‍👦 *Father:* {father}\n"
                    f"📍 *Address:* {address}\n"
                    f"📱 *Mobile:* {mobile}\n"
                    f"☎️ *Alternate:* {alt}\n"
                    f"🌍 *Circle:* {circle}\n"
                    f"🆔 *ID Number:* {id_number}\n"
                    f"✉️ *Email:* {email}\n"
                )
                results.append(msg)

            user_credits[user_id] -= 1
            credit = "@govind"
            developer = "@darkgp0"

            final_msg = "\n\n".join(results)
            final_msg += f"\n\n🔋 *Remaining credits:* {user_credits[user_id]}"
            final_msg += f"\n\n🧑‍💻 Credit: {credit}\n👨‍💻 Developer: {developer}"

            update.message.reply_text(final_msg, parse_mode="Markdown")
        else:
            update.message.reply_text("⚠️ No data found.")

    except Exception as e:
        logger.error(f"Error in API: {e}")
        update.message.reply_text(f"⚠️ Error: {e}")

# ================== ADMIN COMMANDS ==================
def add_credits(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        user_credits[target_id] = user_credits.get(target_id, 0) + amount
        update.message.reply_text(f"✅ Added {amount} credits to {target_id}. Balance: {user_credits[target_id]}")
    except:
        update.message.reply_text("⚠️ Usage: /addcredits <user_id> <amount>")

def deduct_credits(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        user_credits[target_id] = max(0, user_credits.get(target_id, 0) - amount)
        update.message.reply_text(f"✅ Deducted {amount} credits from {target_id}. Balance: {user_credits[target_id]}")
    except:
        update.message.reply_text("⚠️ Usage: /deductcredits <user_id> <amount>")

def user_credits_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        balance = user_credits.get(target_id, 0)
        banned = "🚫 BANNED" if target_id in banned_users else "✅ Active"
        update.message.reply_text(f"👤 User {target_id}\n🔋 Credits: {balance}\nStatus: {banned}")
    except:
        update.message.reply_text("⚠️ Usage: /usercredits <user_id>")

# ================== BAN/UNBAN/BROADCAST ==================
def ban_user(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        banned_users.add(target_id)
        update.message.reply_text(f"⛔ User {target_id} banned.")
    except:
        update.message.reply_text("⚠️ Usage: /ban <user_id>")

def unban_user(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        banned_users.discard(target_id)
        update.message.reply_text(f"✅ User {target_id} unbanned.")
    except:
        update.message.reply_text("⚠️ Usage: /unban <user_id>")

def broadcast(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Not authorized.")
        return
    try:
        message = " ".join(context.args)
        if not message:
            update.message.reply_text("⚠️ Usage: /broadcast <msg>")
            return
        for uid in user_credits.keys():
            if uid not in banned_users:
                try:
                    context.bot.send_message(chat_id=uid, text=f"📢 Broadcast:\n\n{message}")
                except:
                    pass
        update.message.reply_text("✅ Broadcast sent.")
    except Exception as e:
        update.message.reply_text(f"❌ Error: {e}")

# ================== START BOT ==================
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("search", search_number))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, search_number))
    dp.add_handler(CallbackQueryHandler(handle_callback))
    dp.add_handler(CommandHandler("addcredits", add_credits))
    dp.add_handler(CommandHandler("deductcredits", deduct_credits))
    dp.add_handler(CommandHandler("usercredits", user_credits_cmd))
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CommandHandler("unban", unban_user))
    dp.add_handler(CommandHandler("broadcast", broadcast))

    print("✅ Bot is running...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()