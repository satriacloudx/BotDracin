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
    logger.info(f"Admin users: {ADMIN_USER_IDS}")

# Parse database channel
DATABASE_CHANNEL_ID = None
if DATABASE_CHANNEL:
    try:
        clean = DATABASE_CHANNEL.replace(' ', '').replace('"', '').replace("'", '')
        DATABASE_CHANNEL_ID = int(clean)
        logger.info(f"Database channel: {DATABASE_CHANNEL_ID}")
    except ValueError:
        logger.warning(f"DATABASE_CHANNEL format salah: {DATABASE_CHANNEL}")

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
    """Load semua drama dari channel"""
    global drama_database
    
    if not DATABASE_CHANNEL_ID:
        logger.warning("DATABASE_CHANNEL tidak diset")
        return
    
    try:
        drama_database = {}
        message_count = 0
        
        # Scan semua message di channel
        async for message in bot.get_chat_history(DATABASE_CHANNEL_ID, limit=1000):
            message_count += 1
            
            # Skip jika bukan video
            if not message.video:
                continue
            
            # Parse caption: #drama_id Judul Drama - Episode X
            if not message.caption or not message.caption.startswith('#'):
                continue
            
            try:
                caption = message.caption
                parts = caption.split(' ', 1)
                drama_id = parts[0][1:]  # Hilangkan #
                
                if len(parts) < 2 or ' - Episode ' not in parts[1]:
                    continue
                
                title_ep = parts[1].split(' - Episode ')
                drama_title = title_ep[0].strip()
                episode_num = title_ep[1].strip()
                
                # Simpan ke database
                if drama_id not in drama_database:
                    drama_database[drama_id] = {
                        'title': drama_title,
                        'episodes': {}
                    }
                
                drama_database[drama_id]['episodes'][episode_num] = {
                    'file_id': message.video.file_id,
                    'message_id': message.message_id
                }
                
                # Cek thumbnail dari message sebelumnya
                # (jika ada foto sebelum video dengan caption yang sama drama_id)
                
            except Exception as e:
                logger.error(f"Error parsing message: {e}")
                continue
        
        logger.info(f"Database loaded: {len(drama_database)} drama from {message_count} messages")
        
        # Log detail
        for drama_id, info in drama_database.items():
            logger.info(f"  - {info['title']}: {len(info['episodes'])} episodes")
        
    except Exception as e:
        logger.error(f"Error loading database: {e}")

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
        "Database tersimpan di channel Telegram!\n\n"
        "Silakan pilih menu:"
    )
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reload database dari channel"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ Hanya admin yang bisa reload database")
        return
    
    msg = await update.message.reply_text("🔄 Memuat ulang database dari channel...")
    
    await load_database_from_channel(context.bot)
    
    total_ep = sum(len(d['episodes']) for d in drama_database.values())
    
    await msg.edit_text(
        f"✅ Database berhasil dimuat!\n\n"
        f"📊 Total Drama: {len(drama_database)}\n"
        f"📺 Total Episode: {total_ep}"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🔧 *Status Bot*\n\n"
    text += "✅ BOT_TOKEN: OK\n"
    
    if ADMIN_USER_IDS:
        text += f"✅ ADMIN_IDS: {len(ADMIN_USER_IDS)} admin\n"
    else:
        text += "⚠️ ADMIN_IDS: Mode testing (semua bisa upload)\n"
    
    if DATABASE_CHANNEL_ID:
        text += f"✅ DATABASE_CHANNEL: `{DATABASE_CHANNEL_ID}`\n"
        
        # Cek akses channel
        try:
            chat = await context.bot.get_chat(DATABASE_CHANNEL_ID)
            text += f"✅ Channel Name: {chat.title}\n"
        except Exception as e:
            text += f"❌ Error akses channel: {str(e)[:50]}\n"
    else:
        text += "❌ DATABASE_CHANNEL: Tidak diset!\n"
    
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
            "🔍 Ketik nama drama yang ingin dicari:\n\nContoh: Love O2O"
        )
        context.user_data['waiting_for'] = 'search'
        
    elif query.data == 'list':
        if not drama_database:
            await query.edit_message_text(
                "📺 Belum ada drama tersedia.\n\n"
                "Admin dapat upload ke channel database."
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
            await query.edit_message_text("❌ Hanya admin yang bisa upload")
            return
        
        if not DATABASE_CHANNEL_ID:
            await query.edit_message_text(
                "❌ DATABASE_CHANNEL belum diset!\n\n"
                "Hubungi owner bot untuk setup."
            )
            return
        
        # Get channel info
        try:
            chat = await context.bot.get_chat(DATABASE_CHANNEL_ID)
            channel_link = f"@{chat.username}" if chat.username else "Channel Private"
        except:
            channel_link = "Channel"
        
        await query.edit_message_text(
            f"📤 *Cara Upload Drama:*\n\n"
            f"1. Buka channel: {channel_link}\n"
            f"   ID: `{DATABASE_CHANNEL_ID}`\n\n"
            f"2. (Opsional) Kirim foto thumbnail dengan caption:\n"
            f"   `#drama_id Nama Drama`\n\n"
            f"3. Kirim video episode dengan caption:\n"
            f"   `#drama_id Nama Drama - Episode X`\n\n"
            f"*Contoh:*\n"
            f"Thumbnail: `#LOO Love O2O`\n"
            f"Episode: `#LOO Love O2O - Episode 1`\n\n"
            f"4. Setelah upload, ketik /reload di bot untuk refresh database",
            parse_mode='Markdown'
        )
        
    elif query.data.startswith('drama_'):
        drama_id = query.data.replace('drama_', '')
        await show_episodes(query, drama_id, context)
        
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

async def show_episodes(query, drama_id, context):
    if drama_id not in drama_database:
        await query.edit_message_text("❌ Drama tidak ditemukan")
        return
    
    drama = drama_database[drama_id]
    episodes = drama['episodes']
    
    text = f"🎬 *{drama['title']}*\n\n📊 Total: {len(episodes)} episode\n\nPilih episode:"
    
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
    
    # Cek apakah ada thumbnail di channel
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
    
    # Forward video dari channel
    try:
        await context.bot.copy_message(
            chat_id=query.message.chat_id,
            from_chat_id=DATABASE_CHANNEL_ID,
            message_id=episode['message_id']
        )
    except:
        # Fallback: kirim ulang dengan file_id
        await query.message.reply_video(
            video=episode['file_id'],
            caption=f"🎬 *{drama['title']}*\n📺 Episode {ep_num}",
            parse_mode='Markdown'
        )
    
    # Keyboard next episode
    keyboard = []
    next_ep = str(int(ep_num) + 1)
    if next_ep in drama['episodes']:
        keyboard.append([
            InlineKeyboardButton(f"▶️ Episode {next_ep}", callback_data=f"ep_{drama_id}_{next_ep}")
        ])
    keyboard.append([
        InlineKeyboardButton("📺 Daftar Episode", callback_data=f"drama_{drama_id}")
    ])
    
    await query.message.reply_text(
        "Pilih episode selanjutnya:",
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
            await update.message.reply_text(
                f"❌ Drama '{update.message.text}' tidak ditemukan.\n\n"
                "Coba kata kunci lain atau lihat daftar lengkap."
            )
        else:
            keyboard = [
                [InlineKeyboardButton(title, callback_data=f"drama_{did}")]
                for did, title in results
            ]
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data='back')])
            await update.message.reply_text(
                f"🔍 Hasil pencarian '{update.message.text}':",
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
        
        # Load database dari channel saat startup
        logger.info("Loading database from channel...")
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(load_database_from_channel(application.bot))
        
        # Handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("reload", reload))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        ))
        application.add_error_handler(error_handler)
        
        logger.info("Bot started successfully!")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        raise

if __name__ == '__main__':
    main()
