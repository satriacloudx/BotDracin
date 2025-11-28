import os
import logging
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# =====================================
# LOGGING
# =====================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

# =====================================
# ENVIRONMENT
# =====================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()
ADMIN_IDS = os.environ.get('ADMIN_IDS', '').strip()
DATABASE_CHANNEL = os.environ.get('DATABASE_CHANNEL', '').strip()
PORT = int(os.environ.get('PORT', 10000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN tidak boleh kosong!")

# ADMIN
ADMIN_USER_IDS = set()
if ADMIN_IDS:
    for uid in ADMIN_IDS.split(','):
        try:
            ADMIN_USER_IDS.add(int(uid.strip()))
        except:
            pass

def is_admin(user_id: int) -> bool:
    if ADMIN_USER_IDS:
        return user_id in ADMIN_USER_IDS
    return False

# CHANNEL DB
DATABASE_CHANNEL_ID = None
if DATABASE_CHANNEL:
    try:
        clean = DATABASE_CHANNEL.replace(" ", '').replace('"', '').replace("'", '')
        DATABASE_CHANNEL_ID = int(clean)
    except:
        logger.warning("DATABASE_CHANNEL format salah")

# MEMORY DB
drama_database = {}

# =====================================
# FLASK SERVER
# =====================================
app = Flask(__name__)

@app.route('/')
def home():
    return {
        'status': 'online',
        'dramas': len(drama_database)
    }

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# =====================================
# START MENU (AUTO ADMIN FILTER)
# =====================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    keyboard = [
        [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
        [InlineKeyboardButton("📺 Daftar Drama", callback_data='list')]
    ]

    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("➕ Upload (Admin)", callback_data='upload')])
        keyboard.append([InlineKeyboardButton("🔄 Reload DB (Admin)", callback_data='reload')])

    await update.message.reply_text(
        "🎬 *Selamat datang!*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# =====================================
# INDEX FORWARD SYSTEM
# =====================================
async def index_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id

    if not is_admin(user_id):
        await msg.reply_text("❌ Hanya admin yang boleh index.")
        return

    origin = msg.forward_origin

    if not origin or not origin.chat:
        await msg.reply_text("❌ Ini bukan pesan forward channel.")
        return

    if origin.chat.id != DATABASE_CHANNEL_ID:
        await msg.reply_text("❌ Pesan bukan dari database channel.")
        return

    success = await parse_and_index_message(msg, context)

    if success:
        await msg.reply_text("✅ Berhasil diindex.")
    else:
        await msg.reply_text("❌ Format caption salah.")

async def parse_and_index_message(message, context):
    global drama_database

    try:
        caption = message.caption or ""

        # VIDEO (EPISODE)
        if message.video:
            if not caption.startswith("#") or " - Episode " not in caption:
                return False

            parts = caption.split(" ", 1)
            drama_id = parts[0][1:]

            title_ep = parts[1].split(" - Episode ")
            title = title_ep[0].strip()
            ep = title_ep[1].strip()

            if drama_id not in drama_database:
                drama_database[drama_id] = {"title": title, "episodes": {}}

            drama_database[drama_id]["episodes"][ep] = {
                "file_id": message.video.file_id
            }

            return True

        # PHOTO (THUMBNAIL)
        if message.photo:
            if not caption.startswith("#"):
                return False

            parts = caption.split(" ", 1)
            drama_id = parts[0][1:]
            title = parts[1].strip()

            if drama_id not in drama_database:
                drama_database[drama_id] = {"title": title, "episodes": {}}

            drama_database[drama_id]["thumbnail"] = message.photo[-1].file_id
            drama_database[drama_id]["title"] = title

            return True

        return False

    except Exception as e:
        logger.error(e)
        return False

# =====================================
# CALLBACK BUTTONS
# =====================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # ============================
    # MENU UTAMA (BACK)
    # ============================
    if query.data == "back":
        keyboard = [
            [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
            [InlineKeyboardButton("📺 Daftar Drama", callback_data='list')]
        ]

        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("➕ Upload (Admin)", callback_data='upload')])
            keyboard.append([InlineKeyboardButton("🔄 Reload DB (Admin)", callback_data='reload')])

        await query.edit_message_text("🎬 Menu Utama", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # ============================
    # SEARCH
    # ============================
    if query.data == "search":
        await query.edit_message_text("🔍 Ketik nama drama:")
        context.user_data["waiting"] = "search"
        return

    # ============================
    # LIST DRAMA
    # ============================
    if query.data == "list":
        if not drama_database:
            await query.edit_message_text("📭 Belum ada drama.")
            return

        keyboard = [
            [InlineKeyboardButton(info["title"], callback_data=f"d_{did}")]
            for did, info in drama_database.items()
        ]
        keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])

        await query.edit_message_text("📺 Pilih drama:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # ============================
    # UPLOAD & RELOAD (ADMIN)
    # ============================
    if query.data == "upload":
        if not is_admin(user_id):
            await query.edit_message_text("❌ Hanya admin")
            return

        await query.edit_message_text(
            "📤 *Cara Upload:*\n\n"
            "Thumbnail:\n`#ID JudulDrama`\n\n"
            "Episode:\n`#ID JudulDrama - Episode X`\n\n"
            "Forward ke bot.",
            parse_mode="Markdown"
        )
        return

    if query.data == "reload":
        if not is_admin(user_id):
            await query.edit_message_text("❌ Hanya admin")
            return

        await query.edit_message_text("🔄 Reload DB tidak diperlukan (gunakan forward).")
        return

    # ============================
    # PILIH DRAMA
    # ============================
    if query.data.startswith("d_"):
        did = query.data[2:]
        await show_episodes(query, did)
        return

    # ============================
    # EPISODE
    # ============================
    if query.data.startswith("ep_"):
        _, did, ep = query.data.split("_")
        await send_episode(query, did, ep, context)
        return

# =====================================
# SHOW EPISODES
# =====================================
async def show_episodes(query, did):
    if did not in drama_database:
        await query.edit_message_text("❌ Drama tidak ditemukan.")
        return

    info = drama_database[did]
    eps = info["episodes"]

    keyboard = []
    row = []
    for ep in sorted(eps.keys(), key=lambda x: int(x)):
        row.append(InlineKeyboardButton(f"EP {ep}", callback_data=f"ep_{did}_{ep}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("« Kembali", callback_data="list")])

    text = f"🎬 *{info['title']}*\n📺 {len(eps)} Episode"
    thumb = info.get("thumbnail")

    if thumb:
        await query.message.reply_photo(
            photo=thumb,
            caption=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        await query.message.delete()
    else:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# =====================================
# SEND EPISODE
# =====================================
async def send_episode(query, did, ep, context):
    info = drama_database[did]
    episode = info["episodes"][ep]

    await query.message.reply_video(
        episode["file_id"],
        caption=f"🎬 *{info['title']}* — EP {ep}",
        parse_mode="Markdown"
    )

    # NEXT BUTTON
    next_ep = str(int(ep) + 1)
    keyboard = []

    if next_ep in info["episodes"]:
        keyboard.append([InlineKeyboardButton(f"▶️ EP {next_ep}", callback_data=f"ep_{did}_{next_ep}")])

    keyboard.append([InlineKeyboardButton("📺 Episode List", callback_data=f"d_{did}")])

    await query.message.reply_text("Navigasi:", reply_markup=InlineKeyboardMarkup(keyboard))

# =====================================
# USER MESSAGE HANDLER
# =====================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    # FORWARD → INDEX
    if msg.forward_origin and msg.forward_origin.chat:
        await index_message(update, context)
        return

    # SEARCH MODE
    if context.user_data.get("waiting") == "search":
        query = msg.text.lower()
        results = [
            (did, info["title"])
            for did, info in drama_database.items()
            if query in info["title"].lower()
        ]

        if not results:
            await msg.reply_text("❌ Tidak ditemukan.")
        else:
            keyboard = [
                [InlineKeyboardButton(title, callback_data=f"d_{did}")]
                for did, title in results
            ]
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])

            await msg.reply_text("🔍 Hasil:", reply_markup=InlineKeyboardMarkup(keyboard))

        context.user_data["waiting"] = None


# =====================================
# MAIN
# =====================================
def main():
    Thread(target=run_flask, daemon=True).start()

    app_bot = Application.builder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("Bot berjalan...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
