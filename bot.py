import os
import logging
import json
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

# Matikan log spam
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

# Parse database channel
DATABASE_CHANNEL_ID = None
if DATABASE_CHANNEL:
    try:
        clean = DATABASE_CHANNEL.replace(' ', '').replace('"', '').replace("'", '')
        DATABASE_CHANNEL_ID = int(clean)
        logger.info(f"Database channel: {DATABASE_CHANNEL_ID}")
    except ValueError:
        logger.warning(f"DATABASE_CHANNEL format salah")

# Database
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
        [InlineKeyboardButton("📺 Daftar Drama", callback_data='list')],
        [InlineKeyboardButton("➕ Upload (Admin)", callback_data='upload')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "🎬 *Selamat Datang di Bot Drama Cina!*\n\n"
        "Fitur:\n"
        "• Cari drama favorit\n"
        "• Tonton langsung di Telegram\n"
        "• Pilih episode\n\n"
        "📦 Database tersimpan di channel!\n\n"
        "Silakan pilih menu:"
    )
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

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
    if is_admin(user_id):
        text += f"✅ Anda admin (ID: `{user_id}`)\n"
    else:
        text += f"❌ Anda bukan admin\n"
    
    text += f"\n📊 Drama: {len(drama_database)}\n"
    text += f"📺 Episode: {sum(len(d['episodes']) for d in drama_database.values())}\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'search':
        await query.edit_message_text(
            "🔍 Ketik nama drama:\n\nContoh: Love O2O"
        )
        context.user_data['waiting_for'] = 'search'
        
    elif query.data == 'list':
        if not drama_database:
            await query.edit_message_text(
                "📺 Belum ada drama.\n\n"
                "Admin dapat upload drama."
            )
            return
        
        keyboard = []
        for drama_id, info in drama_database.items():
            keyboard.append([
                InlineKeyboardButton(info['title'], callback_data=f"drama_{drama_id}")
            ])
        
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
        
        if not DATABASE_CHANNEL_ID:
            await query.edit_message_text("❌ DATABASE_CHANNEL belum diset")
            return
        
        await query.edit_message_text(
            "📤 *Cara Upload:*\n\n"
            "1. Kirim foto thumbnail dengan caption:\n"
            "   `#drama_id Nama Drama`\n\n"
            "2. Kirim video episode dengan caption:\n"
            "   `#drama_id Nama Drama - Episode X`\n\n"
            "*Contoh:*\n"
            "Thumbnail: `#LOO Love O2O`\n"
            "Episode 1: `#LOO Love O2O - Episode 1`\n"
            "Episode 2: `#LOO Love O2O - Episode 2`\n\n"
            "Bot akan otomatis simpan ke channel database!",
            parse_mode='Markdown'
        )
        
    elif query.data.startswith('drama_'):
        drama_id = query.data.replace('drama_', '')
        await show_episodes(query, drama_id)
        
    elif query.data.startswith('ep_'):
        parts = query.data.split('_')
        await send_episode(query, parts[1], parts[2], context)
        
    elif query.data == 'back':
        keyboard = [
            [InlineKeyboardButton("🔍 Cari", callback_data='search')],
            [InlineKeyboardButton("📺 Daftar", callback_data='list')],
            [InlineKeyboardButton("➕ Upload", callback_data='upload')]
        ]
        await query.edit_message_text(
            "🎬 Menu Utama",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def show_episodes(query, drama_id):
    if drama_id not in drama_database:
        await query.edit_message_text("❌ Drama tidak ditemukan")
        return
    
    drama = drama_database[drama_id]
    episodes = drama['episodes']
    
    text = f"🎬 *{drama['title']}*\n\n📊 {len(episodes)} episode\n\nPilih:"
    
    keyboard = []
    row = []
    for ep in sorted(episodes.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        row.append(InlineKeyboardButton(f"EP {ep}", callback_data=f"ep_{drama_id}_{ep}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("« Kembali", callback_data='list')])
    
    if 'thumbnail' in drama:
        await query.message.reply_photo(
            photo=drama['thumbnail'],
            caption=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        await query.message.delete()
    else:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def send_episode(query, drama_id, ep_num, context):
    drama = drama_database[drama_id]
    episode = drama['episodes'][ep_num]
    
    await query.message.reply_video(
        video=episode['file_id'],
        caption=f"🎬 *{drama['title']}*\n📺 Episode {ep_num}",
        parse_mode='Markdown'
    )
    
    keyboard = []
    next_ep = str(int(ep_num) + 1)
    if next_ep in drama['episodes']:
        keyboard.append([
            InlineKeyboardButton(f"▶️ EP {next_ep}", callback_data=f"ep_{drama_id}_{next_ep}")
        ])
    keyboard.append([
        InlineKeyboardButton("📺 Episodes", callback_data=f"drama_{drama_id}")
    ])
    
    await query.message.reply_text(
        "Selanjutnya:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    
    # Search
    if user_data.get('waiting_for') == 'search':
        search = update.message.text.lower()
        results = [
            (did, info['title']) 
            for did, info in drama_database.items() 
            if search in info['title'].lower()
        ]
        
        if not results:
            await update.message.reply_text(f"❌ '{update.message.text}' tidak ditemukan")
        else:
            keyboard = [
                [InlineKeyboardButton(title, callback_data=f"drama_{did}")]
                for did, title in results
            ]
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data='back')])
            await update.message.reply_text(
                f"🔍 Hasil '{update.message.text}':",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        user_data['waiting_for'] = None
        return
    
    # Upload thumbnail
    if update.message.photo and is_admin(update.message.from_user.id):
        if not update.message.caption or not update.message.caption.startswith('#'):
            await update.message.reply_text("❌ Kirim foto dengan caption: `#drama_id Nama Drama`", parse_mode='Markdown')
            return
        
        await process_thumbnail_upload(update, context)
        return
    
    # Upload video
    if update.message.video and update.message.caption and is_admin(update.message.from_user.id):
        if not update.message.caption.startswith('#'):
            await update.message.reply_text("❌ Format salah!")
            return
        
        await process_video_upload(update, context)
        return

async def process_thumbnail_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proses upload thumbnail"""
    caption = update.message.caption
    parts = caption.split(' ', 1)
    drama_id = parts[0][1:]  # Hilangkan #
    
    if len(parts) < 2:
        await update.message.reply_text("❌ Format: `#drama_id Nama Drama`", parse_mode='Markdown')
        return
    
    drama_title = parts[1].strip()
    photo = update.message.photo[-1]
    
    # Forward ke channel
    if DATABASE_CHANNEL_ID:
        try:
            fwd_msg = await update.message.forward(DATABASE_CHANNEL_ID)
            logger.info(f"Thumbnail forwarded to channel (msg_id: {fwd_msg.message_id})")
        except Exception as e:
            logger.error(f"Error forwarding thumbnail: {e}")
    
    # Simpan ke database
    if drama_id not in drama_database:
        drama_database[drama_id] = {'title': drama_title, 'episodes': {}}
    
    drama_database[drama_id]['title'] = drama_title
    drama_database[drama_id]['thumbnail'] = photo.file_id
    
    await update.message.reply_text(
        f"✅ Thumbnail tersimpan!\n"
        f"🎬 {drama_title}\n\n"
        f"Sekarang kirim video episode dengan caption:\n"
        f"`#drama_id Nama Drama - Episode X`",
        parse_mode='Markdown'
    )

async def process_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proses upload video episode"""
    caption = update.message.caption
    
    if ' - Episode ' not in caption:
        await update.message.reply_text("❌ Format: `#drama_id Nama - Episode X`", parse_mode='Markdown')
        return
    
    parts = caption.split(' ', 1)
    drama_id = parts[0][1:]
    
    title_ep = parts[1].split(' - Episode ')
    drama_title = title_ep[0].strip()
    ep_num = title_ep[1].strip()
    
    # Forward ke channel database
    channel_msg_id = None
    if DATABASE_CHANNEL_ID:
        try:
            fwd_msg = await update.message.forward(DATABASE_CHANNEL_ID)
            channel_msg_id = fwd_msg.message_id
            logger.info(f"Video forwarded to channel (msg_id: {channel_msg_id})")
        except Exception as e:
            logger.error(f"Error forwarding video: {e}")
    
    # Simpan ke database
    if drama_id not in drama_database:
        drama_database[drama_id] = {'title': drama_title, 'episodes': {}}
    
    drama_database[drama_id]['title'] = drama_title
    drama_database[drama_id]['episodes'][ep_num] = {
        'file_id': update.message.video.file_id,
        'channel_msg_id': channel_msg_id
    }
    
    total_eps = len(drama_database[drama_id]['episodes'])
    
    await update.message.reply_text(
        f"✅ Berhasil!\n\n"
        f"🎬 {drama_title}\n"
        f"📺 Episode {ep_num}\n"
        f"📊 Total: {total_eps} episode\n\n"
        f"💾 Tersimpan di channel database!"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

def main():
    try:
        # Flask
        logger.info(f"Starting HTTP server on port {PORT}...")
        Thread(target=run_flask, daemon=True).start()
        
        # Bot
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND | filters.PHOTO | filters.VIDEO,
            handle_message
        ))
        application.add_error_handler(error_handler)
        
        logger.info("Bot started successfully!")
        logger.info(f"Admin IDs: {ADMIN_USER_IDS}")
        logger.info(f"Database Channel: {DATABASE_CHANNEL_ID}")
        
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        raise

if __name__ == '__main__':
    main()
