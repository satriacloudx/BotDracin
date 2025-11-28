import os
import logging
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
DATABASE_CHANNEL = os.environ.get('DATABASE_CHANNEL', '').strip()
PORT = int(os.environ.get('PORT', 10000))
QRIS_URL = os.environ.get('QRIS_URL', '').strip()  # URL foto QRIS

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
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except BadRequest as e:
        logger.debug(f"edit_message_text failed: {e}; will fallback to reply_text")
    except Exception as e:
        logger.debug(f"edit_message_text exception: {e}; fallback to reply_text")

    try:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Failed to reply with fallback message: {e}")

    try:
        await query.message.delete()
    except Exception:
        pass


# =====================================
# START MENU (AUTO ADMIN FILTER)
# =====================================
def build_start_keyboard(is_admin_user: bool):
    keyboard = [
        [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
        [InlineKeyboardButton("📺 Daftar Drama", callback_data='list')],
        [InlineKeyboardButton("💝 Support Developer", callback_data='support')],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data='admin_panel')])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    kb = build_start_keyboard(is_admin(user_id))
    
    welcome_text = (
        "🎬 *Selamat Datang di Bot Drama Cina!*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Bot ini menyediakan koleksi drama Cina lengkap yang bisa kamu tonton kapan saja!\n\n"
        f"📊 *Total Drama:* {len(drama_database)}\n"
        f"🎥 *Total Episode:* {sum(len(d.get('episodes', {})) for d in drama_database.values())}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Pilih menu di bawah untuk mulai:"
    )
    
    await update.message.reply_text(
        welcome_text,
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

    result = await parse_and_index_message(msg, context)

    if result:
        # result berisi info detail tentang apa yang diindex
        await msg.reply_text(result)
    else:
        await msg.reply_text("❌ *Format Caption Salah*\n\n━━━━━━━━━━━━━━━━━━━━\nPastikan format sesuai:\n\n📸 Thumbnail: `#ID JudulDrama`\n🎥 Episode: `#ID JudulDrama - Episode X`", parse_mode='Markdown')


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

            # Check if drama exists
            is_new_drama = drama_id not in drama_database
            
            if is_new_drama:
                drama_database[drama_id] = {"title": title, "episodes": {}}

            # Check if episode already exists
            is_update = ep in drama_database[drama_id]["episodes"]
            
            drama_database[drama_id]["episodes"][ep] = {
                "file_id": message.video.file_id
            }

            # Get video info
            video = message.video
            duration = f"{video.duration // 60}:{video.duration % 60:02d}" if video.duration else "N/A"
            file_size = f"{video.file_size / (1024*1024):.2f} MB" if video.file_size else "N/A"
            
            total_eps = len(drama_database[drama_id]["episodes"])
            
            logger.info(f"Indexed: {drama_id} - {title} EP {ep}")
            
            # Detailed response
            response = (
                f"✅ *Berhasil Diindex!*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📹 *Tipe:* Episode Video\n"
                f"🎬 *Drama:* {title}\n"
                f"🆔 *ID:* #{drama_id}\n"
                f"📺 *Episode:* {ep}\n"
                f"⏱ *Durasi:* {duration}\n"
                f"💾 *Ukuran:* {file_size}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
            
            if is_new_drama:
                response += f"🆕 Drama baru ditambahkan!\n"
            elif is_update:
                response += f"🔄 Episode diperbarui!\n"
            else:
                response += f"➕ Episode baru ditambahkan!\n"
                
            response += f"📊 Total episode sekarang: *{total_eps} EP*"
            
            return response

        # PHOTO (THUMBNAIL)
        if message.photo:
            if not caption.startswith("#"):
                return False

            parts = caption.split(" ", 1)
            drama_id = parts[0][1:]
            title = parts[1].strip() if len(parts) > 1 else "Unknown"

            # Check if drama exists
            is_new_drama = drama_id not in drama_database
            has_old_thumbnail = not is_new_drama and "thumbnail" in drama_database[drama_id]
            
            if is_new_drama:
                drama_database[drama_id] = {"title": title, "episodes": {}}

            drama_database[drama_id]["thumbnail"] = message.photo[-1].file_id
            drama_database[drama_id]["title"] = title

            # Get photo info
            photo = message.photo[-1]
            resolution = f"{photo.width}x{photo.height}"
            file_size = f"{photo.file_size / 1024:.2f} KB" if photo.file_size else "N/A"
            
            total_eps = len(drama_database[drama_id].get("episodes", {}))
            
            logger.info(f"Indexed thumbnail: {drama_id} - {title}")
            
            # Detailed response
            response = (
                f"✅ *Berhasil Diindex!*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🖼 *Tipe:* Thumbnail Drama\n"
                f"🎬 *Drama:* {title}\n"
                f"🆔 *ID:* #{drama_id}\n"
                f"📐 *Resolusi:* {resolution}\n"
                f"💾 *Ukuran:* {file_size}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
            
            if is_new_drama:
                response += f"🆕 Drama baru dibuat!\n"
            elif has_old_thumbnail:
                response += f"🔄 Thumbnail diperbarui!\n"
            else:
                response += f"➕ Thumbnail ditambahkan!\n"
                
            response += f"📊 Total episode: *{total_eps} EP*"
            
            return response

        return False

    except Exception as e:
        logger.error(f"parse_and_index_message error: {e}")
        return False


# =====================================
# PAGINATION HELPER
# =====================================
def paginate_items(items, page, items_per_page=10):
    """Helper untuk pagination"""
    start = page * items_per_page
    end = start + items_per_page
    return items[start:end], len(items)


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
        kb = build_start_keyboard(is_admin(user_id))
        welcome_text = (
            "🎬 *Bot Drama Cina*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total Drama: {len(drama_database)}\n"
            f"🎥 Total Episode: {sum(len(d.get('episodes', {})) for d in drama_database.values())}\n\n"
            "Pilih menu:"
        )
        await safe_edit_or_reply(query, welcome_text, reply_markup=kb, parse_mode='Markdown')
        return

    # ============================
    # SEARCH
    # ============================
    if query.data == "search":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]])
        search_text = (
            "🔍 *Pencarian Drama*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Ketik nama drama yang ingin kamu cari:\n\n"
            "Contoh: _Love Between Fairy_"
        )
        await safe_edit_or_reply(query, search_text, reply_markup=kb, parse_mode='Markdown')
        context.user_data["waiting"] = "search"
        return

    # ============================
    # SUPPORT
    # ============================
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

    # ============================
    # ADMIN PANEL
    # ============================
    if query.data == "admin_panel":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin yang bisa mengakses panel ini.")
            return
        
        admin_text = (
            "⚙️ *Admin Panel*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total Drama: {len(drama_database)}\n"
            f"🎥 Total Episode: {sum(len(d.get('episodes', {})) for d in drama_database.values())}\n\n"
            "Pilih aksi:"
        )
        keyboard = [
            [InlineKeyboardButton("➕ Upload Drama", callback_data='upload')],
            [InlineKeyboardButton("🔄 Reload Database", callback_data='reload')],
            [InlineKeyboardButton("📋 Statistik", callback_data='stats')],
            [InlineKeyboardButton("« Kembali", callback_data="back")]
        ]
        await safe_edit_or_reply(query, admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ============================
    # LIST DRAMA (dengan pagination)
    # ============================
    if query.data.startswith("list"):
        page = 0
        if "_" in query.data:
            page = int(query.data.split("_")[1])
        
        if not drama_database:
            await safe_edit_or_reply(
                query, 
                "📭 *Belum Ada Drama*\n\n━━━━━━━━━━━━━━━━━━━━\nDatabase masih kosong.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]]),
                parse_mode='Markdown'
            )
            return

        # Sort drama by title
        sorted_dramas = sorted(drama_database.items(), key=lambda x: x[1].get("title", ""))
        page_items, total = paginate_items(sorted_dramas, page, items_per_page=8)
        
        keyboard = []
        for did, info in page_items:
            title = info.get("title", did)
            ep_count = len(info.get("episodes", {}))
            keyboard.append([InlineKeyboardButton(
                f"🎬 {title} ({ep_count} EP)", 
                callback_data=f"d_{did}"
            )])

        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"list_{page-1}"))
        if (page + 1) * 8 < total:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"list_{page+1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])
        kb = InlineKeyboardMarkup(keyboard)

        list_text = (
            f"📺 *Daftar Drama* (Halaman {page + 1})\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Menampilkan {len(page_items)} dari {total} drama\n\n"
            f"Pilih drama untuk melihat episode:"
        )

        await safe_edit_or_reply(query, list_text, reply_markup=kb, parse_mode='Markdown')
        return

    # ============================
    # UPLOAD & RELOAD & STATS (ADMIN)
    # ============================
    if query.data == "upload":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return

        text = (
            "📤 *Panduan Upload Drama*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Format Thumbnail:*\n"
            "`#ID JudulDrama`\n\n"
            "*Format Episode:*\n"
            "`#ID JudulDrama - Episode X`\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Contoh:*\n"
            "• Thumbnail: `#LBFD Love Between Fairy and Devil`\n"
            "• Episode: `#LBFD Love Between Fairy and Devil - Episode 1`\n\n"
            "Forward pesan dari channel ke bot ini untuk mengindex."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]])
        await safe_edit_or_reply(query, text, parse_mode="Markdown", reply_markup=kb)
        return

    if query.data == "reload":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]])
        await safe_edit_or_reply(
            query, 
            "🔄 *Reload Database*\n\n━━━━━━━━━━━━━━━━━━━━\nReload tidak diperlukan.\nGunakan sistem forward untuk indexing otomatis.", 
            parse_mode='Markdown',
            reply_markup=kb
        )
        return

    if query.data == "stats":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return

        total_eps = sum(len(d.get('episodes', {})) for d in drama_database.values())
        dramas_with_thumb = sum(1 for d in drama_database.values() if 'thumbnail' in d)
        
        stats_text = (
            "📋 *Statistik Database*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📺 Total Drama: {len(drama_database)}\n"
            f"🎥 Total Episode: {total_eps}\n"
            f"🖼 Drama dengan Thumbnail: {dramas_with_thumb}\n"
            f"📊 Rata-rata EP/Drama: {total_eps // len(drama_database) if drama_database else 0}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Top 5 Drama (Episode Terbanyak):*\n"
        )
        
        # Top 5 drama
        top_dramas = sorted(
            drama_database.items(), 
            key=lambda x: len(x[1].get('episodes', {})), 
            reverse=True
        )[:5]
        
        for i, (did, info) in enumerate(top_dramas, 1):
            stats_text += f"{i}. {info.get('title', did)} - {len(info.get('episodes', {}))} EP\n"
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]])
        await safe_edit_or_reply(query, stats_text, parse_mode='Markdown', reply_markup=kb)
        return

    # ============================
    # PILIH DRAMA
    # ============================
    if query.data.startswith("d_"):
        did = query.data[2:]
        await show_episodes(query, did)
        return

    # ============================
    # EPISODE (dengan pagination)
    # ============================
    if query.data.startswith("ep_"):
        parts = query.data.split("_")
        if len(parts) == 3:
            _, did, ep = parts
            await send_episode(query, did, ep, context)
        elif len(parts) == 4 and parts[1] == "page":
            # Format: ep_page_DID_PAGE
            _, _, did, page = parts
            await show_episodes(query, did, int(page))
        return


# =====================================
# SHOW EPISODES (dengan pagination)
# =====================================
async def show_episodes(query, did, page=0):
    if did not in drama_database:
        await safe_edit_or_reply(
            query, 
            "❌ Drama tidak ditemukan.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Daftar Drama", callback_data="list")]])
        )
        return

    info = drama_database[did]
    eps = info.get("episodes", {})
    
    # Sort episodes
    sorted_eps = sorted(eps.keys(), key=lambda x: int(x) if x.isdigit() else x)
    
    # Pagination (20 episode per halaman)
    page_eps, total = paginate_items(sorted_eps, page, items_per_page=20)

    keyboard = []
    row = []
    
    # Build episode buttons (5 per row)
    for ep in page_eps:
        row.append(InlineKeyboardButton(f"EP {ep}", callback_data=f"ep_{did}_{ep}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"ep_page_{did}_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page+1}/{(total-1)//20 + 1}", callback_data="noop"))
    if (page + 1) * 20 < total:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"ep_page_{did}_{page+1}"))
    
    keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("« Daftar Drama", callback_data="list")])
    kb = InlineKeyboardMarkup(keyboard)

    text = (
        f"🎬 *{info.get('title', did)}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📺 Total Episode: {len(eps)}\n"
        f"📄 Halaman: {page + 1}/{(total-1)//20 + 1}\n\n"
        f"Pilih episode untuk ditonton:"
    )
    
    thumb = info.get("thumbnail")

    if thumb:
        try:
            await query.message.reply_photo(
                photo=thumb, 
                caption=text, 
                reply_markup=kb, 
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"reply_photo failed: {e}")
            await safe_edit_or_reply(query, text, reply_markup=kb, parse_mode="Markdown")
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
        await safe_edit_or_reply(
            query, 
            "❌ Episode tidak ditemukan.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data=f"d_{did}")]])
        )
        return

    episode = info["episodes"][ep]

    caption = (
        f"🎬 *{info.get('title',did)}*\n"
        f"📺 Episode {ep}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Selamat menonton! 🍿"
    )

    try:
        await query.message.reply_video(
            episode["file_id"], 
            caption=caption, 
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"reply_video failed: {e}")
        await safe_edit_or_reply(query, "❌ Gagal mengirim video.")

    # Navigation buttons
    next_ep = str(int(ep) + 1) if ep.isdigit() else None
    keyboard = []
    
    if next_ep and next_ep in info["episodes"]:
        keyboard.append([InlineKeyboardButton(f"▶️ Episode {next_ep}", callback_data=f"ep_{did}_{next_ep}")])
    
    keyboard.append([InlineKeyboardButton("📺 Daftar Episode", callback_data=f"d_{did}")])
    keyboard.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="back")])
    kb = InlineKeyboardMarkup(keyboard)

    try:
        await query.message.reply_text("━━━━━━━━━━━━━━━━━━━━\n*Navigasi:*", reply_markup=kb, parse_mode='Markdown')
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
            search_text = (
                "❌ *Tidak Ditemukan*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Drama dengan kata kunci *\"{text}\"* tidak ditemukan.\n\n"
                f"Coba kata kunci lain atau lihat daftar lengkap."
            )
            await msg.reply_text(
                search_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📺 Lihat Semua Drama", callback_data="list")],
                    [InlineKeyboardButton("« Kembali", callback_data="back")]
                ]),
                parse_mode='Markdown'
            )
        else:
            keyboard = []
            for did, title in results:
                ep_count = len(drama_database[did].get("episodes", {}))
                keyboard.append([InlineKeyboardButton(
                    f"🎬 {title} ({ep_count} EP)", 
                    callback_data=f"d_{did}"
                )])
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])
            
            result_text = (
                f"🔍 *Hasil Pencarian*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Ditemukan {len(results)} drama dengan kata kunci *\"{text}\"*:\n\n"
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
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("Bot berjalan...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
