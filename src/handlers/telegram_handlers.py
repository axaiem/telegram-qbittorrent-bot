import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.config import ALLOWED_USER_ID
from src.services.yts_service import search_movies, build_magnet_uri
from src.services.qbittorrent_service import add_magnet, add_torrent_file

logger = logging.getLogger(__name__)

# Cache for callback data to avoid Telegram 64-byte callback_data limits
# Key: token_id (str), Value: dict(hash=..., title=...)
_TORRENT_CHOICE_CACHE = {}
_CACHE_MAX_SIZE = 500

def _cache_torrent_choice(info_hash: str, movie_title: str) -> str:
    """Stores torrent details under a short key for telegram callback buttons."""
    if len(_TORRENT_CHOICE_CACHE) > _CACHE_MAX_SIZE:
        _TORRENT_CHOICE_CACHE.clear()
    
    key = str(len(_TORRENT_CHOICE_CACHE) + 1)
    _TORRENT_CHOICE_CACHE[key] = {
        "hash": info_hash,
        "title": movie_title,
    }
    return key

def _get_cached_torrent_choice(key: str):
    return _TORRENT_CHOICE_CACHE.get(key)

async def is_authorized(update: Update) -> bool:
    """Check if the update originates from the configured authorized user."""
    user = update.effective_user
    return bool(user and user.id == ALLOWED_USER_ID)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not await is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    help_text = (
        "🎬 *Telegram qBittorrent & Movie Bot*\n\n"
        "Here is what you can do:\n"
        "• `/search <movie name>` — Search for movies and select a download option (up to 5 options)\n"
        "• Send a `magnet:?` link directly to queue it\n"
        "• Send a `.torrent` file to upload it"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def search_movie_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /search <query> or /movie <query> command."""
    if not await is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Please specify a movie title.\nExample: `/search Inception`", parse_mode="Markdown")
        return

    query = " ".join(context.args).strip()
    status_msg = await update.message.reply_text(f"🔍 Searching movies for *{query}*...", parse_mode="Markdown")

    try:
        movies = await search_movies(query, limit=5)
    except Exception as e:
        logger.error(f"Error fetching movie search results: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Failed to search for movies: {e}")
        return

    if not movies:
        await status_msg.edit_text(f"No movies found matching '*{query}*'.", parse_mode="Markdown")
        return

    # Delete or edit the searching status message
    await status_msg.delete()

    # Send options for up to 5 movies
    for movie in movies[:5]:
        keyboard = []
        if movie.torrents:
            row = []
            for torrent in movie.torrents:
                label = f"{torrent.quality} ({torrent.size})"
                cache_key = _cache_torrent_choice(torrent.hash, f"{movie.title} [{torrent.quality}]")
                row.append(
                    InlineKeyboardButton(
                        text=f"⬇️ {label}",
                        callback_data=f"dl:{cache_key}"
                    )
                )
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        caption_lines = [f"🎬 *{movie.title}*"]
        if movie.year:
            caption_lines[0] += f" ({movie.year})"
        if movie.rating > 0.0:
            caption_lines.append(f"⭐ Rating: {movie.rating}/10")
        if movie.summary:
            caption_lines.append(f"📝 {movie.summary[:150]}")
        if not keyboard:
            caption_lines.append("⚠️ _No torrent links available for this title._")

        caption = "\n".join(caption_lines)

        try:
            await update.message.reply_text(
                caption,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception:
            # Fallback to plain text if title contains unescaped markdown characters
            await update.message.reply_text(
                caption.replace("*", "").replace("_", ""),
                reply_markup=reply_markup
            )

async def torrent_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback button clicks when user selects a torrent option."""
    query = update.callback_query
    await query.answer()

    if not await is_authorized(update):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Unauthorized access.")
        return

    data = query.data or ""
    if not data.startswith("dl:"):
        return

    cache_key = data.split(":", 1)[1]
    choice = _get_cached_torrent_choice(cache_key)
    if not choice:
        await query.message.reply_text("⚠️ This download option expired. Please run the search again.")
        return

    info_hash = choice["hash"]
    title = choice["title"]
    magnet_link = build_magnet_uri(info_hash, title)

    try:
        res = await add_magnet(magnet_link)
        if res == "Ok.":
            await query.message.reply_text(f"✅ Added to qBittorrent queue:\n*{title}*", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"⚠️ Response from qBittorrent: {res}")
    except Exception as e:
        logger.error(f"Failed to add magnet link from search: {e}", exc_info=True)
        await query.message.reply_text(f"❌ Error adding torrent to qBittorrent: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages (e.g. raw magnet links)."""
    if not await is_authorized(update):
        return

    text = update.message.text
    if text and text.startswith("magnet:?"):
        try:
            res = await add_magnet(text)
            if res == "Ok.":
                await update.message.reply_text("✅ Magnet link added to qBittorrent download queue!")
            else:
                await update.message.reply_text(f"⚠️ Response from qBittorrent: {res}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding magnet link: {e}")

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded documents (.torrent files)."""
    if not await is_authorized(update):
        return

    doc = update.message.document
    if doc and doc.file_name and doc.file_name.endswith(".torrent"):
        try:
            file = await context.bot.get_file(doc.file_id)
            file_bytes = await file.download_as_bytearray()
            res = await add_torrent_file(bytes(file_bytes))
            if res == "Ok.":
                await update.message.reply_text("✅ .torrent file uploaded and added to downloads!")
            else:
                await update.message.reply_text(f"⚠️ Response from qBittorrent: {res}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding .torrent file: {e}")
