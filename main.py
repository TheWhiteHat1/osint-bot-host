import logging
import requests
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================== CONFIG ==================
API_URL = "https://seller-ki-mkc.taitanx.workers.dev/?mobile="
BOT_TOKEN = os.getenv("BOT_TOKEN", "8257919061:AAFcvvTeInEqTGVNoM3sUzpZerewAgpo9NY")
ADMIN_ID = 7985958385
ADMIN_USERNAME = "@DARKGP0"

# ================== TEMP STORAGE ==================
user_credits = {}
banned_users = set()

# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== START ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in user_credits:
        user_credits[user_id] = 2

    if user_id in banned_users:
        await update.message.reply_text("🚫 You are banned from using this bot.")
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
        [InlineKeyboardButton("💰 Buy Credits", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")],
    ]
    await update.message.reply_text(
        welcome_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================== HELP ==================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
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
        parse_mode="Markdown",
    )

# ================== CALLBACK ==================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id in banned_users:
        await query.edit_message_text("🚫 You are banned.")
        return

    if query.data == "number_info":
        await query.edit_message_text("📱 Send the *phone number* you want to search.", parse_mode="Markdown")

    elif query.data == "profile":
        balance = user_credits.get(user_id, 0)
        await query.edit_message_text(f"👤 *Profile*\n🆔 ID: `{user_id}`\n🔋 Credits: {balance}", parse_mode="Markdown")

    elif query.data == "referral":
        await query.edit_message_text(f"🔗 Invite friends!\n👉 https://t.me/{context.bot.username}?start={user_id}")

# ================== SEARCH ==================
async def search_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in banned_users:
        await update.message.reply_text("🚫 You are banned.")
        return

    text = update.message.text.strip()
    if text.startswith("/search"):
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("⚠️ Usage: /search <number>")
            return
        number = parts[1]
    else:
        number = text

    if user_id not in user_credits:
        user_credits[user_id] = 2

    if user_credits[user_id] <= 0:
        await update.message.reply_text(
            "❌ No credits left.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("💰 Buy Credits", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")]]
            ),
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

            await update.message.reply_text(final_msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ No data found.")
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")

# ================== ADMIN (shortened for brevity) ==================
async def add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        user_credits[target_id] = user_credits.get(target_id, 0) + amount
        await update.message.reply_text(f"✅ Added {amount} credits to {target_id}. Balance: {user_credits[target_id]}")
    except:
        await update.message.reply_text("⚠️ Usage: /addcredits <user_id> <amount>")

# ================== START BOT ==================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("search", search_number))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_number))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(CommandHandler("addcredits", add_credits))

    print("✅ Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
