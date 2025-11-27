import os
import logging
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

# Database struktur: channel_id untuk menyimpan video & thumbnail
ADMIN_CHANNEL = os.environ.get('ADMIN_CHANNEL')  # Channel untuk database
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# In-memory cache untuk film (akan diisi dari channel)
drama_database = {}

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
        chat_member = await context.bot.get_chat_member(ADMIN_CHANNEL, user_id)
        
        if chat_member.status not in ['creator', 'administrator']:
            await query.edit_message_text("❌ Hanya admin yang dapat mengupload drama.")
            return
        
        await query.edit_message_text(
            "📤 *Cara Upload Drama:*\n\n"
            "1. Kirim thumbnail drama\n"
            "2. Kirim video episode dengan caption format:\n"
            "   `#drama_id Judul Drama - Episode X`\n\n"
            "Contoh: `#LOO Love O2O - Episode 1`"
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
        try:
            chat_member = await context.bot.get_chat_member(ADMIN_CHANNEL, user_id)
            if chat_member.status in ['creator', 'administrator']:
                photo = update.message.photo[-1]
                user_data['thumbnail_file_id'] = photo.file_id
                await update.message.reply_text(
                    "✅ Thumbnail tersimpan!\n\n"
                    "Sekarang kirim video dengan format caption:\n"
                    "`#drama_id Judul Drama - Episode X`"
                )
        except:
            pass
    
    # Handle upload video episode (untuk admin)
    if update.message.video and update.message.caption:
        user_id = update.message.from_user.id
        try:
            chat_member = await context.bot.get_chat_member(ADMIN_CHANNEL, user_id)
            if chat_member.status in ['creator', 'administrator']:
                await process_video_upload(update, context)
        except:
            pass

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
    # Buat aplikasi
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND | filters.PHOTO | filters.VIDEO,
        handle_message
    ))
    application.add_error_handler(error_handler)
    
    # Jalankan bot
    logger.info("Bot started...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
