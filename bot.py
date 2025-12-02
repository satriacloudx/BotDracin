import os
import logging
import requests
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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
PORT = int(os.environ.get('PORT', 10000))
QRIS_URL = os.environ.get('QRIS_URL', '').strip()

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

# =====================================
# API DRAMABOX
# =====================================
API_BASE = "https://sapi.dramabox.be"
DEFAULT_LANG = "in"

def api_search(keyword: str, lang: str = DEFAULT_LANG):
    """Mencari drama berdasarkan kata kunci"""
    try:
        url = f"{API_BASE}/suggest/{keyword}"
        params = {"lang": lang}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API search error: {e}")
        return None

def api_get_drama(drama_id: str, lang: str = DEFAULT_LANG):
    """Mendapatkan detail drama"""
    try:
        url = f"{API_BASE}/watch/{drama_id}/0"
        params = {"lang": lang, "source": "search_result"}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API get drama error: {e}")
        return None

def api_get_episodes(drama_id: str, lang: str = DEFAULT_LANG):
    """Mendapatkan daftar episode drama"""
    try:
        url = f"{API_BASE}/chapters/{drama_id}"
        params = {"lang": lang}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API get episodes error: {e}")
        return None

def api_get_video(drama_id: str, episode: int, lang: str = DEFAULT_LANG):
    """Mendapatkan video episode"""
    try:
        url = f"{API_BASE}/watch/{drama_id}/{episode}"
        params = {"lang": lang, "source": "search_result"}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API get video error: {e}")
        return None

# =====================================
# FLASK SERVER
# =====================================
app = Flask(__name__)

@app.route('/')
def home():
    return {
        'status': 'online',
        'service': 'Dramabox Telegram Bot'
    }

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# =====================================
# HELPERS
# =====================================
async def safe_edit_or_reply(query, text, reply_markup=None, parse_mode=None):
    """Edit message atau reply jika gagal"""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except BadRequest as e:
        logger.debug(f"edit_message_text failed: {e}")
    except Exception as e:
        logger.debug(f"edit_message_text exception: {e}")

    try:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Failed to reply: {e}")

    try:
        await query.message.delete()
    except Exception:
        pass

def paginate_items(items, page, items_per_page=10):
    """Helper untuk pagination"""
    start = page * items_per_page
    end = start + items_per_page
    return items[start:end], len(items)

# =====================================
# START MENU
# =====================================
def build_start_keyboard(is_admin_user: bool):
    keyboard = [
        [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
        [InlineKeyboardButton("💝 Support Developer", callback_data='support')],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data='admin_panel')])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    kb = build_start_keyboard(is_admin(user_id))
    
    welcome_text = (
        "🎬 *Selamat Datang di DramaBox Bot!*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Bot ini menyediakan akses ke ribuan drama dari DramaBox yang bisa kamu tonton kapan saja!\n\n"
        "🌟 Fitur:\n"
        "• Pencarian drama otomatis\n"
        "• Saran pencarian real-time\n"
        "• Streaming video langsung\n"
        "• Update konten terbaru\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Pilih menu di bawah untuk mulai:"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=kb,
        parse_mode='Markdown'
    )

# =====================================
# CALLBACK BUTTONS
# =====================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # MENU UTAMA
    if query.data == "back":
        kb = build_start_keyboard(is_admin(user_id))
        welcome_text = (
            "🎬 *DramaBox Bot*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Cari dan tonton drama favoritmu!\n\n"
            "Pilih menu:"
        )
        await safe_edit_or_reply(query, welcome_text, reply_markup=kb, parse_mode='Markdown')
        return

    # SEARCH
    if query.data == "search":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]])
        search_text = (
            "🔍 *Pencarian Drama*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Ketik nama drama yang ingin kamu cari:\n\n"
            "Contoh: _cinta_, _revenge_, _CEO_\n\n"
            "Bot akan memberikan saran otomatis! ✨"
        )
        await safe_edit_or_reply(query, search_text, reply_markup=kb, parse_mode='Markdown')
        context.user_data["waiting"] = "search"
        return

    # SUPPORT
    if query.data == "support":
        support_text = (
            "💝 *Support Developer*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Terima kasih telah menggunakan bot ini! 🙏\n\n"
            "Jika kamu merasa bot ini bermanfaat, kamu bisa support developer melalui QRIS di bawah ini:\n\n"
            "Dukungan kamu sangat berarti untuk pengembangan bot yang lebih baik! ✨"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]])
        
        if QRIS_URL:
            try:
                await query.message.reply_photo(
                    photo=QRIS_URL,
                    caption=support_text,
                    reply_markup=kb,
                    parse_mode='Markdown'
                )
                try:
                    await query.message.delete()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Failed to send QRIS: {e}")
                await safe_edit_or_reply(query, support_text + "\n\n_QRIS sedang tidak tersedia_", reply_markup=kb, parse_mode='Markdown')
        else:
            await safe_edit_or_reply(query, support_text + "\n\n_QRIS belum dikonfigurasi_", reply_markup=kb, parse_mode='Markdown')
        return

    # ADMIN PANEL
    if query.data == "admin_panel":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin yang bisa mengakses panel ini.")
            return
        
        admin_text = (
            "⚙️ *Admin Panel*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Bot menggunakan API DramaBox\n"
            "Data drama diambil secara real-time\n\n"
            "Status: ✅ Online"
        )
        keyboard = [
            [InlineKeyboardButton("📊 Test API", callback_data='test_api')],
            [InlineKeyboardButton("« Kembali", callback_data="back")]
        ]
        await safe_edit_or_reply(query, admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # TEST API
    if query.data == "test_api":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return
        
        test_result = api_search("love")
        status = "✅ API Berfungsi" if test_result else "❌ API Error"
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]])
        await safe_edit_or_reply(query, f"📊 *Test API*\n\n{status}", parse_mode='Markdown', reply_markup=kb)
        return

    # PILIH DRAMA
    if query.data.startswith("d_"):
        drama_id = query.data[2:]
        await show_episodes(query, drama_id)
        return

    # EPISODE
    if query.data.startswith("ep_"):
        parts = query.data.split("_")
        if len(parts) == 3:
            _, drama_id, ep_num = parts
            await send_episode(query, drama_id, ep_num, context)
        elif len(parts) == 4 and parts[1] == "page":
            _, _, drama_id, page = parts
            await show_episodes(query, drama_id, int(page))
        return

# =====================================
# SHOW EPISODES
# =====================================
async def show_episodes(query, drama_id, page=0):
    await query.answer("⏳ Memuat episode...")
    
    # Get drama info dan episodes
    drama_info = api_get_drama(drama_id)
    episodes_data = api_get_episodes(drama_id)
    
    if not drama_info or not episodes_data:
        await safe_edit_or_reply(
            query,
            "❌ Gagal memuat data drama.\n\nCoba lagi nanti.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]])
        )
        return
    
    # Parse data
    data = drama_info.get('data', {})
    title = data.get('title', 'Unknown')
    description = data.get('description', '')
    cover = data.get('cover', '')
    
    episodes = episodes_data.get('data', {}).get('chapters', [])
    total_eps = len(episodes)
    
    # Pagination
    page_eps, total = paginate_items(episodes, page, items_per_page=20)
    
    keyboard = []
    row = []
    
    # Build episode buttons (5 per row)
    for ep in page_eps:
        ep_num = ep.get('order', 0)
        ep_title = ep.get('title', f'EP {ep_num}')
        row.append(InlineKeyboardButton(f"EP {ep_num}", callback_data=f"ep_{drama_id}_{ep_num}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"ep_page_{drama_id}_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page+1}/{(total-1)//20 + 1}", callback_data="noop"))
    if (page + 1) * 20 < total:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"ep_page_{drama_id}_{page+1}"))
    
    keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔍 Cari Drama Lain", callback_data="search")])
    keyboard.append([InlineKeyboardButton("« Menu Utama", callback_data="back")])
    kb = InlineKeyboardMarkup(keyboard)
    
    # Truncate description
    desc_short = description[:200] + "..." if len(description) > 200 else description
    
    text = (
        f"🎬 *{title}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📺 Total Episode: {total_eps}\n"
        f"📄 Halaman: {page + 1}/{(total-1)//20 + 1}\n\n"
        f"📖 _{desc_short}_\n\n"
        f"Pilih episode untuk ditonton:"
    )
    
    if cover:
        try:
            await query.message.reply_photo(
                photo=cover,
                caption=text,
                reply_markup=kb,
                parse_mode="Markdown"
            )
            try:
                await query.message.delete()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"reply_photo failed: {e}")
            await safe_edit_or_reply(query, text, reply_markup=kb, parse_mode="Markdown")
    else:
        await safe_edit_or_reply(query, text, reply_markup=kb, parse_mode="Markdown")

# =====================================
# SEND EPISODE
# =====================================
async def send_episode(query, drama_id, ep_num, context):
    await query.answer("⏳ Memuat video...")
    
    # Get video URL
    video_data = api_get_video(drama_id, int(ep_num))
    
    if not video_data:
        await safe_edit_or_reply(
            query,
            "❌ Gagal memuat video.\n\nCoba lagi nanti.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data=f"d_{drama_id}")]])
        )
        return
    
    data = video_data.get('data', {})
    title = data.get('title', 'Unknown')
    video_url = data.get('video_url', '')
    cover = data.get('cover', '')
    
    if not video_url:
        await safe_edit_or_reply(
            query,
            "❌ Video tidak tersedia untuk episode ini.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data=f"d_{drama_id}")]])
        )
        return
    
    caption = (
        f"🎬 *{title}*\n"
        f"📺 Episode {ep_num}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Selamat menonton! 🍿"
    )
    
    # Navigation buttons
    keyboard = [
        [InlineKeyboardButton(f"▶️ Episode {int(ep_num)+1}", callback_data=f"ep_{drama_id}_{int(ep_num)+1}")],
        [InlineKeyboardButton("📺 Daftar Episode", callback_data=f"d_{drama_id}")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="back")]
    ]
    kb = InlineKeyboardMarkup(keyboard)
    
    try:
        # Kirim video langsung ke Telegram
        await query.message.reply_video(
            video=video_url,
            caption=caption,
            parse_mode='Markdown',
            supports_streaming=True,
            thumb=cover if cover else None
        )
        
        # Kirim navigation buttons terpisah
        await query.message.reply_text(
            "━━━━━━━━━━━━━━━━━━━━\n*Navigasi:*",
            reply_markup=kb,
            parse_mode='Markdown'
        )
        
        try:
            await query.message.delete()
        except Exception:
            pass
            
    except Exception as e:
        logger.error(f"reply_video failed: {e}")
        # Fallback ke link jika gagal kirim video
        fallback_caption = (
            f"🎬 *{title}*\n"
            f"📺 Episode {ep_num}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Tidak dapat mengirim video langsung.\n\n"
            f"🔗 Tonton di: [Klik di sini]({video_url})\n\n"
            f"Selamat menonton! 🍿"
        )
        fallback_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔗 Tonton Episode {ep_num}", url=video_url)],
            [InlineKeyboardButton(f"▶️ Episode {int(ep_num)+1}", callback_data=f"ep_{drama_id}_{int(ep_num)+1}")],
            [InlineKeyboardButton("📺 Daftar Episode", callback_data=f"d_{drama_id}")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="back")]
        ])
        await safe_edit_or_reply(query, fallback_caption, reply_markup=fallback_kb, parse_mode='Markdown')

# =====================================
# USER MESSAGE HANDLER
# =====================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    
    if not msg or not msg.text:
        return
    
    # SEARCH MODE
    if context.user_data.get("waiting") == "search":
        keyword = msg.text.strip()
        
        if not keyword:
            await msg.reply_text("❌ Masukkan kata kunci pencarian.")
            return
        
        # Search using API
        search_results = api_search(keyword)
        
        if not search_results or not search_results.get('data'):
            await msg.reply_text(
                f"❌ *Tidak Ditemukan*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Drama dengan kata kunci *\"{keyword}\"* tidak ditemukan.\n\n"
                f"Coba kata kunci lain!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Cari Lagi", callback_data="search")],
                    [InlineKeyboardButton("« Kembali", callback_data="back")]
                ]),
                parse_mode='Markdown'
            )
            context.user_data["waiting"] = None
            return
        
        # Parse results
        results = search_results.get('data', [])[:10]  # Limit to 10
        
        keyboard = []
        for item in results:
            drama_id = item.get('id', '')
            title = item.get('title', 'Unknown')
            if drama_id:
                keyboard.append([InlineKeyboardButton(
                    f"🎬 {title}",
                    callback_data=f"d_{drama_id}"
                )])
        
        keyboard.append([InlineKeyboardButton("🔍 Cari Lagi", callback_data="search")])
        keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])
        
        result_text = (
            f"🔍 *Hasil Pencarian*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Ditemukan {len(results)} drama untuk *\"{keyword}\"*\n\n"
            f"Pilih drama:"
        )
        
        await msg.reply_text(
            result_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
        context.user_data["waiting"] = None
        return

# =====================================
# SET BOT COMMANDS
# =====================================
async def post_init(application: Application):
    """Set bot commands after initialization"""
    commands = [
        BotCommand("start", "Mulai bot dan tampilkan menu utama")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands set successfully")

# =====================================
# MAIN
# =====================================
def main():
    Thread(target=run_flask, daemon=True).start()
    
    app_bot = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot berjalan dengan API DramaBox...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
