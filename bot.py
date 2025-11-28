import os
import logging
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
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
# HELPERS: SAFE EDIT / REPLY
# =====================================
async def safe_edit_or_reply(query, text, reply_markup=None, parse_mode=None):
    """
    Try to edit the message text. If the original message is media (no text),
    fallback to sending a new text message and try to delete the old message.
    """
    try:
        # Try edit (works only when original message is a text message)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except BadRequest as e:
        # Common reason: "There is no text in the message to edit"
        logger.debug(f"edit_message_text failed: {e}; will fallback to reply_text")
    except Exception as e:
        # Other exceptions: we still fallback
        logger.debug(f"edit_message_text exception: {e}; fallback to reply_text")

    # Fallback: send a new message (reply) and delete original if possible
    try:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Failed to reply with fallback message: {e}")

    # try delete original (best-effort)
    try:
        await query.message.delete()
    except Exception:
        # ignore delete errors
        pass


# =====================================
# START MENU (AUTO ADMIN FILTER) - buttons larger (one per row)
# =====================================
def build_start_keyboard(is_admin_user: bool):
    keyboard = [
        [InlineKeyboardButton("🔍  CARI DRAMA", callback_data='search')],
        [InlineKeyboardButton("📺  DAFTAR DRAMA", callback_data='list')],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("➕  UPLOAD (ADMIN)", callback_data='upload')])
        keyboard.append([InlineKeyboardButton("🔄  RELOAD DB (ADMIN)", callback_data='reload')])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    kb = build_start_keyboard(is_admin(user_id))
    await update.message.reply_text(
        "🎬 *Selamat datang di Bot Drama Cina!*\n\n"
        "Pilih menu:",
        reply_markup=kb,
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

    if DATABASE_CHANNEL_ID and origin.chat.id != DATABASE_CHANNEL_ID:
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

            logger.info(f"Indexed: {drama_id} - {title} EP {ep}")
            return True

        # PHOTO (THUMBNAIL)
        if message.photo:
            if not caption.startswith("#"):
                return False

            parts = caption.split(" ", 1)
            drama_id = parts[0][1:]
            title = parts[1].strip() if len(parts) > 1 else "Unknown"

            if drama_id not in drama_database:
                drama_database[drama_id] = {"title": title, "episodes": {}}

            drama_database[drama_id]["thumbnail"] = message.photo[-1].file_id
            drama_database[drama_id]["title"] = title

            logger.info(f"Indexed thumbnail: {drama_id} - {title}")
            return True

        return False

    except Exception as e:
        logger.error(f"parse_and_index_message error: {e}")
        return False


# =====================================
# CALLBACK BUTTONS
# =====================================
def build_list_keyboard():
    # default placeholder when building manually
    return InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]])

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # ============================
    # MENU UTAMA (BACK)
    # ============================
    if query.data == "back":
        kb = build_start_keyboard(is_admin(user_id))
        await safe_edit_or_reply(query, "🎬 Menu Utama", reply_markup=kb)
        return

    # ============================
    # SEARCH
    # ============================
    if query.data == "search":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]])
        await safe_edit_or_reply(query, "🔍 Ketik nama drama:", reply_markup=kb)
        context.user_data["waiting"] = "search"
        return

    # ============================
    # LIST DRAMA
    # ============================
    if query.data == "list":
        if not drama_database:
            await safe_edit_or_reply(query, "📭 Belum ada drama.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]]))
            return

        keyboard = []
        # one big button per drama (larger)
        for did, info in drama_database.items():
            title = info.get("title", did)
            keyboard.append([InlineKeyboardButton(f"{title}", callback_data=f"d_{did}")])

        keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])
        kb = InlineKeyboardMarkup(keyboard)

        await safe_edit_or_reply(query, "📺 Pilih drama:", reply_markup=kb)
        return

    # ============================
    # UPLOAD & RELOAD (ADMIN)
    # ============================
    if query.data == "upload":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return

        text = (
            "📤 *Cara Upload:*\n\n"
            "Thumbnail:\n`#ID JudulDrama`\n\n"
            "Episode:\n`#ID JudulDrama - Episode X`\n\n"
            "Forward ke bot."
        )
        await safe_edit_or_reply(query, text, parse_mode="Markdown")
        return

    if query.data == "reload":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return

        await safe_edit_or_reply(query, "🔄 Reload DB tidak diperlukan (gunakan forward).")
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
        _, did, ep = query.data.split("_", 2)
        await send_episode(query, did, ep, context)
        return


# =====================================
# SHOW EPISODES
# =====================================
async def show_episodes(query, did):
    if did not in drama_database:
        await safe_edit_or_reply(query, "❌ Drama tidak ditemukan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]]))
        return

    info = drama_database[did]
    eps = info.get("episodes", {})

    keyboard = []
    row = []
    # build episode buttons, one per button, but show up to 4 per row for compactness
    for ep in sorted(eps.keys(), key=lambda x: int(x) if x.isdigit() else x):
        # make each EP button slightly bigger by label
        row.append(InlineKeyboardButton(f"EP {ep}", callback_data=f"ep_{did}_{ep}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("« Kembali", callback_data="list")])
    kb = InlineKeyboardMarkup(keyboard)

    text = f"🎬 *{info.get('title', did)}*\n📺 {len(eps)} Episode"
    thumb = info.get("thumbnail")

    if thumb:
        # send a photo message with keyboard (reply) and delete the old message that had the button
        try:
            await query.message.reply_photo(photo=thumb, caption=text, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"reply_photo failed: {e}")
            # fallback to text
            await safe_edit_or_reply(query, text, reply_markup=kb, parse_mode="Markdown")
        # try delete original (best-effort)
        try:
            await query.message.delete()
        except Exception:
            pass
    else:
        await safe_edit_or_reply(query, text, reply_markup=kb, parse_mode="Markdown")


# =====================================
# SEND EPISODE
# =====================================
async def send_episode(query, did, ep, context):
    info = drama_database.get(did)
    if not info or "episodes" not in info or ep not in info["episodes"]:
        await safe_edit_or_reply(query, "❌ Episode tidak ditemukan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data=f"d_{did}")]]))
        return

    episode = info["episodes"][ep]

    try:
        await query.message.reply_video(episode["file_id"], caption=f"🎬 *{info.get('title',did)}* — EP {ep}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"reply_video failed: {e}")
        await safe_edit_or_reply(query, "❌ Gagal mengirim video.")

    # NEXT / LIST buttons
    next_ep = str(int(ep) + 1) if ep.isdigit() else None
    keyboard = []
    if next_ep and next_ep in info["episodes"]:
        keyboard.append([InlineKeyboardButton(f"▶️ EP {next_ep}", callback_data=f"ep_{did}_{next_ep}")])
    keyboard.append([InlineKeyboardButton("📺 Daftar Episode", callback_data=f"d_{did}")])
    kb = InlineKeyboardMarkup(keyboard)

    try:
        await query.message.reply_text("Navigasi:", reply_markup=kb)
    except Exception as e:
        logger.error(f"reply_text navigation failed: {e}")


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
        text = (msg.text or "").strip()
        if not text:
            await msg.reply_text("❌ Masukkan nama drama.")
            return

        query_lower = text.lower()
        results = [
            (did, info["title"])
            for did, info in drama_database.items()
            if query_lower in info.get("title", "").lower()
        ]

        if not results:
            await msg.reply_text("❌ Tidak ditemukan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]]))
        else:
            keyboard = [[InlineKeyboardButton(title, callback_data=f"d_{did}")] for did, title in results]
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])
            await msg.reply_text("🔍 Hasil:", reply_markup=InlineKeyboardMarkup(keyboard))

        context.user_data["waiting"] = None
        return

    # default fallback
    # optional: ignore other messages or guide user
    # await msg.reply_text("Ketik /start untuk memulai.")


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
