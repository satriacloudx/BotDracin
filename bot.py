import os
import logging
import asyncio
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

# Setup logging - matikan log httpx
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Matikan log httpx dan telegram yang spam
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

# Fix untuk Python 3.13
if hasattr(asyncio, 'set_event_loop_policy'):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except:
        pass

# Database struktur: channel_id untuk menyimpan video & thumbnail
ADMIN_CHANNEL = os.environ.get('ADMIN_CHANNEL', '').strip()
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()
ADMIN_IDS = os.environ.get('ADMIN_IDS', '').strip()  # Comma separated user IDs
PORT = int(os.environ.get('PORT', 10000))

# Validasi environment variables
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN tidak boleh kosong!")

# Konversi ADMIN_CHANNEL ke integer jika ada
ADMIN_CHANNEL_ID = None
if ADMIN_CHANNEL:
    try:
        # Hilangkan semua karakter non-digit kecuali minus di depan
        clean_channel = ADMIN_CHANNEL.replace(' ', '').replace('"', '').replace("'", '')
        ADMIN_CHANNEL_ID = int(clean_channel)
        logger.info(f"Admin channel ID: {ADMIN_CHANNEL_ID}")
    except ValueError:
        logger.warning(f"ADMIN_CHANNEL format salah: {ADMIN_CHANNEL}")

# Parse admin user IDs
ADMIN_USER_IDS = set()
if ADMIN_IDS:
    for uid in ADMIN_IDS.split(','):
        try:
            ADMIN_USER_IDS.add(int(uid.strip()))
        except ValueError:
            pass
    logger.info(f"Admin users: {ADMIN_USER_IDS}")

# In-memory cache untuk film (akan diisi dari channel)
drama_database = {}

# Flask app untuk health check
app = Flask(__name__)

@app.route('/')
def home():
    return {
        'status': 'online',
        'bot': 'Drama China Telegram Bot',
        'drama_count': len(drama_database),
        'message': 'Bot is running!'
    }, 200

@app.route('/health')
def health():
    return {'status': 'healthy'}, 200

@app.route('/ping')
def ping():
    return {'ping': 'pong'}, 200

def run_flask():
    """Jalankan Flask server di thread terpisah"""
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

def is_admin(user_id: int) -> bool:
    """Cek apakah user adalah admin"""
    # Jika ADMIN_IDS diset, cek di situ
    if ADMIN_USER_IDS:
        return user_id in ADMIN_USER_IDS
    # Jika tidak ada ADMIN_IDS, semua user bisa upload (untuk testing)
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler command /start"""
    keyboard = [
        [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
        [InlineKeyboardButton("📺 Daftar Drama", callback_data='list')],
        [InlineKeyboardButton("➕ Upload Drama (Admin)", callback_data='upload')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "🎬 *Selamat Datang di Bot Drama Cina!*\n\n"
        "Fitur yang tersedia:\n"
        "• Cari drama favorit\n"
        "• Tonton langsung di Telegram\n"
        "• Pilih episode yang diinginkan\n\n"
        "Silakan pilih menu di bawah:"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler command /status - cek konfigurasi bot"""
    status_text = "🔧 *Status Bot*\n\n"
    
    # Cek BOT_TOKEN
    if BOT_TOKEN:
        status_text += "✅ BOT_TOKEN: OK\n"
    else:
        status_text += "❌ BOT_TOKEN: KOSONG\n"
    
    # Cek ADMIN_CHANNEL (opsional)
    if ADMIN_CHANNEL_ID:
        status_text += f"✅ ADMIN_CHANNEL: `{ADMIN_CHANNEL_ID}`\n"
    else:
        status_text += "⚠️ ADMIN_CHANNEL: Tidak diset (opsional)\n"
    
    # Cek ADMIN_IDS
    if ADMIN_USER_IDS:
        status_text += f"✅ ADMIN_IDS: {len(ADMIN_USER_IDS)} admin\n"
    else:
        status_text += "⚠️ ADMIN_IDS: Tidak diset (semua user bisa upload)\n"
    
    # Cek user admin atau tidak
    user_id = update.message.from_user.id
    if is_admin(user_id):
        status_text += f"✅ Anda adalah admin (ID: `{user_id}`)\n"
    else:
        status_text += f"❌ Anda bukan admin (ID: `{user_id}`)\n"
    
    # Drama count
    status_text += f"\n📊 Total Drama: {len(drama_database)}\n"
    
    total_episodes = sum(len(d['episodes']) for d in drama_database.values())
    status_text += f"📺 Total Episode: {total_episodes}\n"
    
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler command /debug - info untuk troubleshooting"""
    debug_text = "🐛 *Debug Info*\n\n"
    debug_text += f"Your User ID: `{update.message.from_user.id}`\n"
    debug_text += f"Your Username: @{update.message.from_user.username or 'N/A'}\n"
    debug_text += f"Your Name: {update.message.from_user.first_name}\n\n"
    
    debug_text += "*Environment Variables:*\n"
    debug_text += f"ADMIN_CHANNEL raw: `{ADMIN_CHANNEL or 'NOT SET'}`\n"
    debug_text += f"ADMIN_CHANNEL_ID: `{ADMIN_CHANNEL_ID or 'NOT SET'}`\n"
    debug_text += f"ADMIN_IDS: `{ADMIN_IDS or 'NOT SET'}`\n"
    debug_text += f"ADMIN_USER_IDS: `{ADMIN_USER_IDS or 'NOT SET'}`\n\n"
    
    debug_text += "*Admin Status:*\n"
    if is_admin(update.message.from_user.id):
        debug_text += "✅ Anda adalah admin\n"
    else:
        debug_text += "❌ Anda bukan admin\n"
    
    await update.message.reply_text(debug_text, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk inline keyboard"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'search':
        await query.edit_message_text(
            "🔍 Ketik nama drama yang ingin dicari:\n\n"
            "Contoh: Love O2O"
        )
        context.user_data['waiting_for'] = 'search'
        
    elif query.data == 'list':
        if not drama_database:
            await query.edit_message_text(
                "📺 Belum ada drama yang tersedia.\n\n"
                "Hubungi admin untuk menambahkan drama."
            )
            return
        
        drama_list = "📺 *Daftar Drama Tersedia:*\n\n"
        keyboard = []
        
        for drama_id, drama_info in drama_database.items():
            drama_list += f"• {drama_info['title']}\n"
            keyboard.append([
                InlineKeyboardButton(
                    drama_info['title'],
                    callback_data=f"drama_{drama_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("« Kembali", callback_data='back_to_menu')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            drama_list,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    elif query.data == 'upload':
        # Cek apakah user adalah admin
        user_id = query.from_user.id
        
        if not is_admin(user_id):
            await query.edit_message_text(
                "❌ Hanya admin yang dapat mengupload drama.\n\n"
                "Hubungi owner bot untuk mendapatkan akses admin."
            )
            return
        
        await query.edit_message_text(
            "📤 *Cara Upload Drama:*\n\n"
            "1. Kirim thumbnail drama (foto)\n"
            "2. Kirim video episode dengan caption format:\n"
            "   `#drama_id Judul Drama - Episode X`\n\n"
            "Contoh:\n"
            "`#LOO Love O2O - Episode 1`\n\n"
            "Drama ID harus unik tanpa spasi!",
            parse_mode='Markdown'
        )
        
    elif query.data.startswith('drama_'):
        drama_id = query.data.replace('drama_', '')
        await show_drama_episodes(query, drama_id)
        
    elif query.data.startswith('ep_'):
        parts = query.data.split('_')
        drama_id = parts[1]
        episode_num = parts[2]
        await send_episode(query, drama_id, episode_num, context)
        
    elif query.data == 'back_to_menu':
        keyboard = [
            [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
            [InlineKeyboardButton("📺 Daftar Drama", callback_data='list')],
            [InlineKeyboardButton("➕ Upload Drama (Admin)", callback_data='upload')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎬 Menu Utama\n\nSilakan pilih:",
            reply_markup=reply_markup
        )

async def show_drama_episodes(query, drama_id):
    """Tampilkan daftar episode drama"""
    if drama_id not in drama_database:
        await query.edit_message_text("❌ Drama tidak ditemukan.")
        return
    
    drama = drama_database[drama_id]
    episodes = drama['episodes']
    
    text = f"🎬 *{drama['title']}*\n\n"
    text += f"📊 Total Episode: {len(episodes)}\n\n"
    text += "Pilih episode yang ingin ditonton:"
    
    keyboard = []
    row = []
    
    for ep_num in sorted(episodes.keys(), key=int):
        row.append(InlineKeyboardButton(
            f"EP {ep_num}",
            callback_data=f"ep_{drama_id}_{ep_num}"
        ))
        
        if len(row) == 4:  # 4 tombol per baris
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("« Kembali", callback_data='list')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Kirim dengan thumbnail jika ada
    if 'thumbnail_file_id' in drama:
        await query.message.reply_photo(
            photo=drama['thumbnail_file_id'],
            caption=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        await query.message.delete()
    else:
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def send_episode(query, drama_id, episode_num, context):
    """Kirim video episode"""
    drama = drama_database[drama_id]
    episode = drama['episodes'][episode_num]
    
    caption = f"🎬 *{drama['title']}*\n📺 Episode {episode_num}"
    
    await query.message.reply_video(
        video=episode['file_id'],
        caption=caption,
        parse_mode='Markdown'
    )
    
    # Keyboard untuk episode berikutnya
    next_ep = str(int(episode_num) + 1)
    keyboard = []
    
    if next_ep in drama['episodes']:
        keyboard.append([
            InlineKeyboardButton(
                f"▶️ Episode {next_ep}",
                callback_data=f"ep_{drama_id}_{next_ep}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("📺 Daftar Episode", callback_data=f"drama_{drama_id}")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(
        "Pilih episode selanjutnya:",
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk pesan teks dan media"""
    user_data = context.user_data
    
    # Handle pencarian drama
    if user_data.get('waiting_for') == 'search':
        search_query = update.message.text.lower()
        results = []
        
        for drama_id, drama_info in drama_database.items():
            if search_query in drama_info['title'].lower():
                results.append((drama_id, drama_info['title']))
        
        if not results:
            await update.message.reply_text(
                f"❌ Drama '{update.message.text}' tidak ditemukan.\n\n"
                "Coba kata kunci lain atau lihat daftar lengkap."
            )
        else:
            keyboard = []
            for drama_id, title in results:
                keyboard.append([
                    InlineKeyboardButton(title, callback_data=f"drama_{drama_id}")
                ])
            
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data='back_to_menu')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🔍 Hasil pencarian '{update.message.text}':",
                reply_markup=reply_markup
            )
        
        user_data['waiting_for'] = None
        return
    
    # Handle upload thumbnail (untuk admin)
    if update.message.photo:
        user_id = update.message.from_user.id
        
        if is_admin(user_id):
            photo = update.message.photo[-1]
            user_data['thumbnail_file_id'] = photo.file_id
            await update.message.reply_text(
                "✅ Thumbnail tersimpan!\n\n"
                "Sekarang kirim video dengan format caption:\n"
                "`#drama_id Judul Drama - Episode X`",
                parse_mode='Markdown'
            )
            return
    
    # Handle upload video episode (untuk admin)
    if update.message.video and update.message.caption:
        user_id = update.message.from_user.id
        
        if is_admin(user_id):
            await process_video_upload(update, context)
            return

async def process_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proses upload video episode"""
    caption = update.message.caption
    
    # Parse caption: #drama_id Judul Drama - Episode X
    if not caption.startswith('#'):
        await update.message.reply_text("❌ Format caption salah!")
        return
    
    parts = caption.split(' ', 1)
    drama_id = parts[0][1:]  # Hilangkan #
    
    if len(parts) < 2 or ' - Episode ' not in parts[1]:
        await update.message.reply_text("❌ Format caption salah!")
        return
    
    title_and_ep = parts[1].split(' - Episode ')
    drama_title = title_and_ep[0]
    episode_num = title_and_ep[1].strip()
    
    # Simpan ke database
    if drama_id not in drama_database:
        drama_database[drama_id] = {
            'title': drama_title,
            'episodes': {}
        }
        
        # Tambahkan thumbnail jika ada
        if 'thumbnail_file_id' in context.user_data:
            drama_database[drama_id]['thumbnail_file_id'] = context.user_data['thumbnail_file_id']
            del context.user_data['thumbnail_file_id']
    
    drama_database[drama_id]['episodes'][episode_num] = {
        'file_id': update.message.video.file_id
    }
    
    await update.message.reply_text(
        f"✅ Berhasil menambahkan:\n"
        f"🎬 {drama_title}\n"
        f"📺 Episode {episode_num}"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk error"""
    logger.error(f"Error: {context.error}")

def main():
    """Main function"""
    try:
        # Start Flask server di thread terpisah
        logger.info(f"Starting HTTP server on port {PORT}...")
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Buat aplikasi dengan konfigurasi khusus untuk Python 3.13
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .connect_timeout(30)
            .read_timeout(30)
            .write_timeout(30)
            .build()
        )
        
        # Register handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("debug", debug))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND | filters.PHOTO | filters.VIDEO,
            handle_message
        ))
        application.add_error_handler(error_handler)
        
        # Jalankan bot dengan polling
        logger.info("Bot started successfully!")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise

if __name__ == '__main__':
    main()
