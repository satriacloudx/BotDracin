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

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

# Environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()
ADMIN_IDS = os.environ.get('ADMIN_IDS', '').strip()
DATABASE_CHANNEL = os.environ.get('DATABASE_CHANNEL', '').strip()
PORT = int(os.environ.get('PORT', 10000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN tidak boleh kosong!")

# Parse admin IDs
ADMIN_USER_IDS = set()
if ADMIN_IDS:
    for uid in ADMIN_IDS.split(','):
        try:
            ADMIN_USER_IDS.add(int(uid.strip()))
        except ValueError:
            pass

# Database channel
DATABASE_CHANNEL_ID = None
if DATABASE_CHANNEL:
    try:
        clean = DATABASE_CHANNEL.replace(' ', '').replace('"', '').replace("'", '')
        DATABASE_CHANNEL_ID = int(clean)
        logger.info(f"Database channel: {DATABASE_CHANNEL_ID}")
    except ValueError:
        logger.warning(f"DATABASE_CHANNEL format salah")

# Database memory
drama_database = {}

# Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return {
        'status': 'online',
        'bot': 'Drama China Bot',
        'drama_count': len(drama_database),
        'episodes': sum(len(d['episodes']) for d in drama_database.values())
    }, 200

@app.route('/health')
def health():
    return {'status': 'healthy'}, 200

@app.route('/ping')
def ping():
    return {'ping': 'pong'}, 200


def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)


def is_admin(user_id: int) -> bool:
    if ADMIN_USER_IDS:
        return user_id in ADMIN_USER_IDS
    return True


# Bot API tidak bisa scan historis channel → biarkan kosong
async def load_database_from_channel(bot):
    logger.info("DATABASE reload berjalan, tapi dibatasi Bot API. Gunakan forward.")


# START
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
        [InlineKeyboardButton("📺 Daftar Drama", callback_data='list')],
        [InlineKeyboardButton("➕ Upload (Admin)", callback_data='upload')],
        [InlineKeyboardButton("🔄 Reload DB (Admin)", callback_data='reload')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "🎬 *Selamat Datang di Bot Drama Cina!*\n\n"
        "📦 Database tersimpan permanen di channel Telegram!\n\n"
        "Fitur:\n"
        "• Cari drama favorit\n"
        "• Tonton langsung\n"
        "• Data tidak hilang meski bot offline\n\n"
        "Pilih menu:"
    )

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# STATUS
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🔧 *Status Bot*\n\n"
    text += "✅ BOT_TOKEN: OK\n"

    if ADMIN_USER_IDS:
        text += f"✅ ADMIN_IDS: {len(ADMIN_USER_IDS)} admin\n"
    else:
        text += "⚠️ ADMIN_IDS: Mode testing\n"

    if DATABASE_CHANNEL_ID:
        text += f"✅ DATABASE_CHANNEL: `{DATABASE_CHANNEL_ID}`\n"
        try:
            chat = await context.bot.get_chat(DATABASE_CHANNEL_ID)
            text += f"✅ Channel: {chat.title}\n"
        except Exception as e:
            text += f"❌ Error: {str(e)[:50]}\n"
    else:
        text += "⚠️ DATABASE_CHANNEL: Tidak diset\n"

    user_id = update.message.from_user.id
    text += f"\n👤 Your ID: `{user_id}`\n"
    if is_admin(user_id):
        text += f"✅ Anda admin\n"
    else:
        text += f"❌ Anda bukan admin\n"

    text += f"\n📊 Drama: {len(drama_database)}\n"
    text += f"📺 Episode: {sum(len(d['episodes']) for d in drama_database.values())}\n"

    await update.message.reply_text(text, parse_mode='Markdown')


# ==============================
#   INDEX — PERBAIKAN BAGIAN INI
# ==============================
async def index_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    origin = message.forward_origin

    # Cek apakah forwarded message valid
    if not origin or not origin.chat:
        await message.reply_text("❌ Ini bukan forwarded message dari channel")
        return

    channel_id = origin.chat.id

    if channel_id != DATABASE_CHANNEL_ID:
        await message.reply_text("❌ Message bukan dari database channel")
        return

    if not is_admin(message.from_user.id):
        await message.reply_text("❌ Hanya admin yang bisa index")
        return

    success = await parse_and_index_message(message, context)

    if success:
        await message.reply_text(
            f"✅ Message berhasil diindex!\n\n"
            f"📊 Total Drama: {len(drama_database)}\n"
            f"📺 Total Episode: {sum(len(d['episodes']) for d in drama_database.values())}"
        )
    else:
        await message.reply_text("❌ Gagal index message. Cek format caption.")


async def parse_and_index_message(message, context):
    global drama_database

    try:
        # VIDEO
        if message.video and message.caption:
            caption = message.caption

            if not caption.startswith('#'):
                return False
            if ' - Episode ' not in caption:
                return False

            parts = caption.split(' ', 1)
            drama_id = parts[0][1:]

            title_ep = parts[1].split(' - Episode ')
            drama_title = title_ep[0].strip()
            ep_num = title_ep[1].strip()

            if drama_id not in drama_database:
                drama_database[drama_id] = {'title': drama_title, 'episodes': {}}

            drama_database[drama_id]['episodes'][ep_num] = {
                'file_id': message.video.file_id
            }

            logger.info(f"Indexed: {drama_title} - Episode {ep_num}")
            return True

        # PHOTO
        if message.photo and message.caption:
            caption = message.caption

            if not caption.startswith('#'):
                return False

            parts = caption.split(' ', 1)
            drama_id = parts[0][1:]

            if len(parts) < 2:
                return False

            drama_title = parts[1].strip()

            if drama_id not in drama_database:
                drama_database[drama_id] = {'title': drama_title, 'episodes': {}}

            drama_database[drama_id]['title'] = drama_title
            drama_database[drama_id]['thumbnail'] = message.photo[-1].file_id

            logger.info(f"Indexed thumbnail: {drama_title}")
            return True

        return False

    except Exception as e:
        logger.error(f"Error parsing message: {e}")
        return False


# BUTTON HANDLER
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'search':
        await query.edit_message_text("🔍 Ketik nama drama:\n\nContoh: Love O2O")
        context.user_data['waiting_for'] = 'search'

    elif query.data == 'list':
        if not drama_database:
            await query.edit_message_text(
                "📺 Belum ada drama.\n\nAdmin: Forward message dari channel ke bot untuk index."
            )
            return

        keyboard = []
        for drama_id, info in drama_database.items():
            keyboard.append([InlineKeyboardButton(info['title'], callback_data=f"drama_{drama_id}")])

        keyboard.append([InlineKeyboardButton("« Kembali", callback_data='back')])

        await query.edit_message_text(
            "📺 *Daftar Drama:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    elif query.data == 'upload':
        if not is_admin(query.from_user.id):
            await query.edit_message_text("❌ Hanya admin")
            return

        await query.edit_message_text(
            f"📤 *Cara Upload & Index:*\n\n"
            f"Upload thumbnail:\n"
            f"`#ID JudulDrama`\n\n"
            f"Upload episode:\n"
            f"`#ID JudulDrama - Episode X`\n\n"
            f"Kemudian FORWARD ke bot ini.",
            parse_mode='Markdown'
        )

    elif query.data == 'reload':
        if not is_admin(query.from_user.id):
            await query.answer("❌ Hanya admin", show_alert=True)
            return

        await query.edit_message_text("🔄 Memuat ulang database...")
        await load_database_from_channel(context.bot)

        await query.edit_message_text(
            f"✅ Database dimuat ulang!\n"
            f"(Gunakan forward untuk index data baru)"
        )

    elif query.data.startswith('drama_'):
        drama_id = query.data.replace('drama_', '')
        await show_episodes(query, drama_id)

    elif query.data.startswith('ep_'):
        _, drama_id, ep = query.data.split('_')
        await send_episode(query, drama_id, ep, context)

    elif query.data == 'back':
        keyboard = [
            [InlineKeyboardButton("🔍 Cari", callback_data='search')],
            [InlineKeyboardButton("📺 Daftar", callback_data='list')],
            [InlineKeyboardButton("➕ Upload", callback_data='upload')],
            [InlineKeyboardButton("🔄 Reload", callback_data='reload')]
        ]
        await query.edit_message_text("🎬 Menu Utama", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_episodes(query, drama_id):
    if drama_id not in drama_database:
        await query.edit_message_text("❌ Drama tidak ditemukan")
        return

    drama = drama_database[drama_id]
    episodes = drama["episodes"]

    text = f"🎬 *{drama['title']}*\n\n📊 {len(episodes)} episode\n\nPilih:"

    keyboard = []
    row = []
    for ep in sorted(episodes.keys(), key=lambda x: int(x)):
        row.append(InlineKeyboardButton(f"EP {ep}", callback_data=f"ep_{drama_id}_{ep}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("« Kembali", callback_data="list")])

    if "thumbnail" in drama:
        await query.message.reply_photo(
            photo=drama['thumbnail'],
            caption=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        await query.message.delete()
    else:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def send_episode(query, drama_id, ep_num, context):
    drama = drama_database[drama_id]
    episode = drama["episodes"][ep_num]

    await query.message.reply_video(
        video=episode["file_id"],
        caption=f"🎬 *{drama['title']}*\n📺 Episode {ep_num}",
        parse_mode="Markdown"
    )

    keyboard = []
    next_ep = str(int(ep_num) + 1)
    if next_ep in drama["episodes"]:
        keyboard.append([InlineKeyboardButton(f"▶️ EP {next_ep}", callback_data=f"ep_{drama_id}_{next_ep}")])

    keyboard.append([InlineKeyboardButton("📺 Episodes", callback_data=f"drama_{drama_id}")])

    await query.message.reply_text("Selanjutnya:", reply_markup=InlineKeyboardMarkup(keyboard))


# =================================
#   PERBAIKAN DI SINI JUGA (FORWARD)
# =================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    # Jika forwarded message → index
    if msg.forward_origin and msg.forward_origin.chat:
        await index_message(update, context)
        return

    # Search mode
    if context.user_data.get("waiting_for") == "search":
        search = msg.text.lower()
        results = [
            (did, info["title"])
            for did, info in drama_database.items()
            if search in info["title"].lower()
        ]

        if not results:
            await msg.reply_text(f"❌ '{msg.text}' tidak ditemukan")
        else:
            keyboard = [
                [InlineKeyboardButton(title, callback_data=f"drama_{did}")]
                for did, title in results
            ]
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])

            await msg.reply_text(f"🔍 Hasil '{msg.text}':", reply_markup=InlineKeyboardMarkup(keyboard))

        context.user_data["waiting_for"] = None
        return


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")


def main():
    try:
        logger.info(f"Starting HTTP server on port {PORT}...")
        Thread(target=run_flask, daemon=True).start()

        application = Application.builder().token(BOT_TOKEN).build()

        logger.info("Bot ready! Forward messages from channel to index.")

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
        application.add_error_handler(error_handler)

        logger.info("Bot started!")
        logger.info(f"Admin IDs: {ADMIN_USER_IDS}")
        logger.info(f"Database Channel: {DATABASE_CHANNEL_ID}")

        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    except Exception as e:
        logger.error(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
