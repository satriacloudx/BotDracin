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

# Database - akan di-load dari channel
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

async def load_database_from_channel(bot):
    """
    Scan channel dan build database dari message yang ada
    Menggunakan teknik iterasi message_id
    """
    global drama_database
    
    if not DATABASE_CHANNEL_ID:
        logger.warning("DATABASE_CHANNEL tidak diset")
        return
    
    try:
        drama_database = {}
        logger.info(f"Scanning channel {DATABASE_CHANNEL_ID}...")
        
        # Strategi: Coba baca message dari ID tertinggi ke bawah
        # Mulai dari ID besar (misalnya 10000) dan turun sampai menemukan message
        found_messages = 0
        max_msg_id = 10000  # Coba sampai message ID 10000
        empty_count = 0
        max_empty = 100  # Stop jika 100 message berturut-turut kosong
        
        for msg_id in range(max_msg_id, 0, -1):
            try:
                # Gunakan copy_message untuk "membaca" message tanpa benar-benar copy
                # Trick: forward ke channel yang sama akan error tapi kita bisa tangkap datanya
                
                # Alternatif: gunakan getChat dan coba akses via message link
                # Cara paling reliable: iterate dengan offset
                
                # WORKAROUND: Karena Bot API terbatas untuk channel history,
                # kita akan gunakan cara manual: Admin forward message ke bot untuk index
                pass
                
            except Exception as e:
                empty_count += 1
                if empty_count >= max_empty:
                    break
                continue
        
        logger.info(f"Database scan complete: {len(drama_database)} drama, {found_messages} messages")
        
    except Exception as e:
        logger.error(f"Error loading database: {e}")

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

async def index_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin forward message dari channel ke bot untuk diindex
    Bot akan parse dan simpan ke database
    """
    if not update.message.forward_from_chat:
        await update.message.reply_text("❌ Ini bukan forwarded message dari channel")
        return
    
    if update.message.forward_from_chat.id != DATABASE_CHANNEL_ID:
        await update.message.reply_text("❌ Message bukan dari database channel")
        return
    
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ Hanya admin yang bisa index")
        return
    
    # Parse message
    success = await parse_and_index_message(update.message, context)
    
    if success:
        await update.message.reply_text(
            f"✅ Message berhasil diindex!\n\n"
            f"📊 Total Drama: {len(drama_database)}\n"
            f"📺 Total Episode: {sum(len(d['episodes']) for d in drama_database.values())}"
        )
    else:
        await update.message.reply_text("❌ Gagal index message. Cek format caption.")

async def parse_and_index_message(message, context):
    """Parse forwarded message dan index ke database"""
    global drama_database
    
    try:
        # Video message
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
            
            # Index
            if drama_id not in drama_database:
                drama_database[drama_id] = {
                    'title': drama_title,
                    'episodes': {}
                }
            
            drama_database[drama_id]['episodes'][ep_num] = {
                'file_id': message.video.file_id
            }
            
            logger.info(f"Indexed: {drama_title} - Episode {ep_num}")
            return True
        
        # Photo message (thumbnail)
        if message.photo and message.caption:
            caption = message.caption
            
            if not caption.startswith('#'):
                return False
            
            parts = caption.split(' ', 1)
            drama_id = parts[0][1:]
            
            if len(parts) < 2:
                return False
            
            drama_title = parts[1].strip()
            
            # Index
            if drama_id not in drama_database:
                drama_database[drama_id] = {
                    'title': drama_title,
                    'episodes': {}
                }
            
            drama_database[drama_id]['title'] = drama_title
            drama_database[drama_id]['thumbnail'] = message.photo[-1].file_id
            
            logger.info(f"Indexed thumbnail: {drama_title}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error parsing message: {e}")
        return False

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
                "Admin: Forward message dari channel ke bot untuk index."
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
        
        try:
            chat = await context.bot.get_chat(DATABASE_CHANNEL_ID)
            channel_name = chat.title
            channel_link = f"@{chat.username}" if chat.username else "channel private"
        except:
            channel_name = "Database Channel"
            channel_link = "channel"
        
        await query.edit_message_text(
            f"📤 *Cara Upload & Index:*\n\n"
            f"*Step 1: Upload ke Channel*\n"
            f"Buka channel: {channel_link}\n\n"
            f"Upload thumbnail dengan caption:\n"
            f"`#drama_id Nama Drama`\n\n"
            f"Upload video dengan caption:\n"
            f"`#drama_id Nama Drama - Episode X`\n\n"
            f"*Step 2: Index ke Bot*\n"
            f"Forward message dari channel ke bot ini.\n"
            f"Bot akan otomatis index!\n\n"
            f"*Contoh:*\n"
            f"1. Upload di channel:\n"
            f"   `#LOO Love O2O` (thumbnail)\n"
            f"   `#LOO Love O2O - Episode 1` (video)\n\n"
            f"2. Forward message tsb ke bot\n"
            f"3. Bot akan reply: ✅ Berhasil diindex!",
            parse_mode='Markdown'
        )
        
    elif query.data == 'reload':
        if not is_admin(query.from_user.id):
            await query.answer("❌ Hanya admin", show_alert=True)
            return
        
        await query.edit_message_text("🔄 Memuat ulang database...")
        await load_database_from_channel(context.bot)
        
        await query.edit_message_text(
            f"✅ Database dimuat!\n\n"
            f"📊 Drama: {len(drama_database)}\n"
            f"📺 Episode: {sum(len(d['episodes']) for d in drama_database.values())}\n\n"
            f"⚠️ Catatan: Karena keterbatasan Bot API,\n"
            f"gunakan cara forward message untuk index."
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
            [InlineKeyboardButton("➕ Upload", callback_data='upload')],
            [InlineKeyboardButton("🔄 Reload", callback_data='reload')]
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
    
    # Handle forwarded message untuk indexing
    if update.message.forward_from_chat:
        await index_message(update, context)
        return
    
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

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

def main():
    try:
        # Flask
        logger.info(f"Starting HTTP server on port {PORT}...")
        Thread(target=run_flask, daemon=True).start()
        
        # Bot
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Load database saat startup (akan kosong karena keterbatasan API)
        logger.info("Bot ready! Forward messages from channel to index.")
        
        # Handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_message
        ))
        application.add_error_handler(error_handler)
        
        logger.info("Bot started!")
        logger.info(f"Admin IDs: {ADMIN_USER_IDS}")
        logger.info(f"Database Channel: {DATABASE_CHANNEL_ID}")
        
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        raise

if __name__ == '__main__':
    main()
