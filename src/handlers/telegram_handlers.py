import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.config import ALLOWED_USER_ID
from src.services.yts_service import search_movies, build_magnet_uri
from src.services.qbittorrent_service import (
    add_magnet,
    add_torrent_file,
    get_torrents_info,
    get_torrent_info,
    get_torrent_by_short_hash,
    pause_torrents,
    resume_torrents,
    delete_torrents,
    get_transfer_info,
)

logger = logging.getLogger(__name__)

# Cache for callback data to avoid Telegram 64-byte callback_data limits
# Key: token_id (str), Value: dict(hash=..., title=...)
_TORRENT_CHOICE_CACHE = {}
_CACHE_MAX_SIZE = 500

STATE_MAP = {
    "downloading": ("⬇️ Downloading", False),
    "stalledDL": ("⏳ Stalled (DL)", False),
    "metaDL": ("🔍 Fetching Metadata", False),
    "forcedMetaDL": ("🔍 Fetching Metadata [F]", False),
    "queuedDL": ("💤 Queued (DL)", False),
    "pausedDL": ("⏸️ Paused (DL)", True),
    "stoppedDL": ("⏸️ Stopped (DL)", True),
    "forcedDL": ("⬇️ Downloading [F]", False),
    "uploading": ("⬆️ Seeding", False),
    "stalledUP": ("⏳ Stalled (UP)", False),
    "queuedUP": ("💤 Queued (UP)", False),
    "pausedUP": ("⏸️ Paused (UP)", True),
    "stoppedUP": ("⏸️ Stopped (UP)", True),
    "forcedUP": ("⬆️ Seeding [F]", False),
    "checkingDL": ("🔄 Checking (DL)", False),
    "checkingUP": ("🔄 Checking (UP)", False),
    "checkingResumeData": ("🔄 Checking Resume Data", False),
    "moving": ("🚚 Moving", False),
    "error": ("❌ Error", True),
    "missingFiles": ("⚠️ Missing Files", True),
    "allocating": ("💾 Allocating", False),
}

PAGE_SIZE = 5

def format_bytes(size: int | float | None) -> str:
    """Format bytes into human-readable units."""
    if size is None or size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    val = float(size)
    for unit in units:
        if val < 1024.0 or unit == units[-1]:
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} PB"

def format_speed(bytes_per_sec: int | float | None) -> str:
    """Format byte transfer speeds."""
    return f"{format_bytes(bytes_per_sec)}/s"

def format_eta(seconds: int | None) -> str:
    """Format ETA seconds into human-readable string."""
    if seconds is None or seconds < 0 or seconds >= 8640000:
        return "∞"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d > 0:
        return f"{d}d {h}h"
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def format_progress_bar(progress: float | None, length: int = 8) -> str:
    """Render a text-based progress bar."""
    if progress is None:
        progress = 0.0
    clamped = max(0.0, min(1.0, float(progress)))
    filled = int(round(clamped * length))
    return "▰" * filled + "▱" * (length - filled)

def format_state(state: str | None) -> tuple[str, bool]:
    """Returns human-readable state label and a boolean indicating if it is paused/stopped."""
    if not state:
        return ("Unknown", False)
    if state in STATE_MAP:
        return STATE_MAP[state]
    is_paused = "pause" in state.lower() or "stop" in state.lower()
    return (state.capitalize(), is_paused)

def escape_md(text: str) -> str:
    """Escape Markdown special characters to prevent Telegram formatting errors."""
    if not text:
        return ""
    for ch in ("*", "_", "`", "[", "]"):
        text = text.replace(ch, f"\\{ch}")
    return text

async def safe_reply_message(message, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """Reply with Markdown formatting with automatic plain-text fallback."""
    try:
        return await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception:
        plain_text = text.replace("*", "").replace("`", "").replace("_", "")
        return await message.reply_text(plain_text, reply_markup=reply_markup)

async def safe_edit_message(query, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """Edit message in-place with automatic plain-text fallback and ignoring unchanged errors."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        if "Message is not modified" in str(e):
            return
        try:
            plain_text = text.replace("*", "").replace("`", "").replace("_", "")
            await query.edit_message_text(plain_text, reply_markup=reply_markup)
        except Exception as inner_e:
            if "Message is not modified" in str(inner_e):
                return
            logger.error(f"Error editing message: {inner_e}")

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

def build_torrents_list_message(
    torrents: list,
    page: int = 1,
    page_size: int = PAGE_SIZE,
    transfer_info=None
) -> tuple[str, InlineKeyboardMarkup]:
    """Builds the paginated status overview and inline keyboard."""
    total_torrents = len(torrents)
    if total_torrents == 0:
        lines = [
            "📊 *qBittorrent Status*",
            "• *Connection*: Active",
        ]
        if transfer_info:
            dl_spd = format_speed(getattr(transfer_info, "dl_info_speed", 0))
            up_spd = format_speed(getattr(transfer_info, "up_info_speed", 0))
            lines.append(f"• *DL Speed*: {dl_spd} | *UP Speed*: {up_spd}")
        lines.append("\n_No torrents found in your qBittorrent queue._")
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="qbt:l:1")]])
        return "\n".join(lines), markup

    total_pages = max(1, (total_torrents + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    end_idx = min(start_idx + page_size, total_torrents)
    page_torrents = torrents[start_idx:end_idx]

    header_lines = [f"📊 *qBittorrent Status* (Page {page}/{total_pages} • {total_torrents} total)"]
    if transfer_info:
        dl_spd = format_speed(getattr(transfer_info, "dl_info_speed", 0))
        up_spd = format_speed(getattr(transfer_info, "up_info_speed", 0))
        header_lines.append(f"⚡ *DL*: {dl_spd} | *UP*: {up_spd}")
    header_lines.append("")

    items = []
    keyboard = []

    for i, t in enumerate(page_torrents, start=start_idx + 1):
        state_label, _ = format_state(t.state)
        pct = round(t.progress * 100, 1)
        bar = format_progress_bar(t.progress)
        size_str = format_bytes(t.total_size if t.total_size > 0 else t.size)
        dled_str = format_bytes(t.downloaded)
        dl_spd = format_speed(t.dlspeed)
        eta_str = format_eta(t.eta)

        name_display = escape_md(t.name[:60] + "..." if len(t.name) > 60 else t.name)
        items.append(
            f"{i}️⃣ *{name_display}*\n"
            f"   └ {state_label} • {pct}% `{bar}`\n"
            f"   └ 💾 {dled_str}/{size_str} • ⚡ {dl_spd} • ⏱ {eta_str}"
        )

        short_hash = t.hash[:12]
        btn_name = t.name[:24] + "..." if len(t.name) > 24 else t.name
        btn_text = f"{i}️⃣ {btn_name} ({int(pct)}%)"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"qbt:v:{short_hash}")])

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"qbt:l:{page - 1}"))
        else:
            nav_row.append(InlineKeyboardButton("▪️", callback_data="qbt:noop"))

        nav_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="qbt:noop"))

        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"qbt:l:{page + 1}"))
        else:
            nav_row.append(InlineKeyboardButton("▪️", callback_data="qbt:noop"))

        keyboard.append(nav_row)

    keyboard.append([
        InlineKeyboardButton("⏸️ Pause All", callback_data="qbt:pa"),
        InlineKeyboardButton("▶️ Resume All", callback_data="qbt:ra"),
        InlineKeyboardButton("🔄 Refresh", callback_data=f"qbt:l:{page}"),
    ])

    text = "\n".join(header_lines) + "\n\n".join(items)
    return text, InlineKeyboardMarkup(keyboard)

def build_torrent_detail_message(torrent) -> tuple[str, InlineKeyboardMarkup]:
    """Builds detailed view for a single torrent with interactive action buttons."""
    state_label, is_paused = format_state(torrent.state)
    pct = round(torrent.progress * 100, 1)
    bar = format_progress_bar(torrent.progress, length=10)
    size_str = format_bytes(torrent.total_size if torrent.total_size > 0 else torrent.size)
    dled_str = format_bytes(torrent.downloaded)
    upled_str = format_bytes(torrent.uploaded)
    dl_spd = format_speed(torrent.dlspeed)
    up_spd = format_speed(torrent.upspeed)
    eta_str = format_eta(torrent.eta)

    try:
        added_str = datetime.fromtimestamp(torrent.added_on).strftime("%Y-%m-%d %H:%M")
    except Exception:
        added_str = "N/A"

    name_esc = escape_md(torrent.name)
    path_esc = escape_md(getattr(torrent, "save_path", "Default"))

    text = (
        f"🎬 *{name_esc}*\n\n"
        f"• *Status*: {state_label}\n"
        f"• *Progress*: {pct}% `{bar}`\n"
        f"• *Downloaded*: {dled_str} of {size_str}\n"
        f"• *Uploaded*: {upled_str}\n"
        f"• *Download Speed*: {dl_spd}\n"
        f"• *Upload Speed*: {up_spd}\n"
        f"• *Seeds*: {torrent.num_seeds} ({torrent.num_complete} in swarm)\n"
        f"• *Peers*: {torrent.num_leechs} ({torrent.num_incomplete} in swarm)\n"
        f"• *Ratio*: {torrent.ratio:.2f}\n"
        f"• *ETA*: {eta_str}\n"
        f"• *Added*: {added_str}\n"
        f"• *Save Path*: `{path_esc}`"
    )

    short_hash = torrent.hash[:12]
    control_btn = (
        InlineKeyboardButton("▶️ Resume / Start", callback_data=f"qbt:r:{short_hash}")
        if is_paused
        else InlineKeyboardButton("⏸️ Pause / Stop", callback_data=f"qbt:p:{short_hash}")
    )

    keyboard = [
        [control_btn, InlineKeyboardButton("🔄 Refresh", callback_data=f"qbt:v:{short_hash}")],
        [InlineKeyboardButton("🗑️ Discard / Delete", callback_data=f"qbt:da:{short_hash}")],
        [InlineKeyboardButton("⬅️ Back to List", callback_data="qbt:l:1")],
    ]

    return text, InlineKeyboardMarkup(keyboard)

def build_delete_confirm_message(torrent) -> tuple[str, InlineKeyboardMarkup]:
    """Builds deletion confirmation prompt."""
    short_hash = torrent.hash[:12]
    name_esc = escape_md(torrent.name)
    text = (
        "⚠️ *Discard / Delete Torrent*\n\n"
        f"Are you sure you want to delete this torrent?\n"
        f"*{name_esc}*\n\n"
        "Choose an option:\n"
        "• *Remove Torrent Only*: Removes the torrent from qBittorrent, keeping downloaded files on disk.\n"
        "• *Delete with Files*: Removes the torrent and permanently deletes all downloaded files from storage."
    )
    keyboard = [
        [
            InlineKeyboardButton("🗑️ Remove Torrent Only", callback_data=f"qbt:dk:{short_hash}"),
            InlineKeyboardButton("🔥 Delete with Files", callback_data=f"qbt:df:{short_hash}"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"qbt:v:{short_hash}")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not await is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    help_text = (
        "🎬 *Telegram qBittorrent & Movie Bot*\n\n"
        "Here is what you can do:\n"
        "• `/search <movie name>` — Search for movies and select a download option\n"
        "• `/status` or `/torrents` — View active torrents, speeds, progress, and interact (pause, resume, discard/delete)\n"
        "• `/pause_all` — Pause all active torrents\n"
        "• `/resume_all` — Resume all torrents\n"
        "• Send a `magnet:?` link directly to queue it\n"
        "• Send a `.torrent` file to upload it"
    )
    await safe_reply_message(update.message, help_text)

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status, /torrents, or /list command."""
    if not await is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    # Check for optional filter argument (e.g. /status dl, /status paused)
    status_filter = None
    if context.args:
        raw_arg = context.args[0].lower()
        if raw_arg in ("dl", "downloading"):
            status_filter = "downloading"
        elif raw_arg in ("paused", "stopped"):
            status_filter = "paused"
        elif raw_arg in ("seeding", "uploading", "completed"):
            status_filter = "completed"
        elif raw_arg in ("active",):
            status_filter = "active"

    try:
        torrents = await get_torrents_info(status_filter=status_filter)
        transfer_info = await get_transfer_info()
    except Exception as e:
        logger.error(f"Failed to fetch qBittorrent status: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Could not connect to qBittorrent Web UI: {e}\n"
            "Please ensure qBittorrent is running and Web UI is enabled."
        )
        return

    text, markup = build_torrents_list_message(torrents, page=1, transfer_info=transfer_info)
    await safe_reply_message(update.message, text, reply_markup=markup)

async def pause_all_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pause_all command."""
    if not await is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    try:
        await pause_torrents("all")
        await update.message.reply_text("⏸️ All torrents have been paused.")
    except Exception as e:
        logger.error(f"Failed to pause all torrents: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Failed to pause torrents: {e}")

async def resume_all_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume_all command."""
    if not await is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    try:
        await resume_torrents("all")
        await update.message.reply_text("▶️ All torrents have been resumed.")
    except Exception as e:
        logger.error(f"Failed to resume all torrents: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Failed to resume torrents: {e}")

async def qbt_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries for qBittorrent status and management."""
    query = update.callback_query
    if not await is_authorized(update):
        await query.answer("Unauthorized access.", show_alert=True)
        return

    data = query.data or ""
    if not data.startswith("qbt:"):
        await query.answer()
        return

    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "noop":
        await query.answer()
        return

    try:
        if action == "l":
            # List view pagination
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            torrents = await get_torrents_info()
            transfer_info = await get_transfer_info()
            text, markup = build_torrents_list_message(torrents, page=page, transfer_info=transfer_info)
            await safe_edit_message(query, text, markup)
            await query.answer()

        elif action == "pa":
            # Pause all
            await pause_torrents("all")
            await query.answer("⏸️ Paused all torrents.")
            torrents = await get_torrents_info()
            transfer_info = await get_transfer_info()
            text, markup = build_torrents_list_message(torrents, page=1, transfer_info=transfer_info)
            await safe_edit_message(query, text, markup)

        elif action == "ra":
            # Resume all
            await resume_torrents("all")
            await query.answer("▶️ Resumed all torrents.")
            torrents = await get_torrents_info()
            transfer_info = await get_transfer_info()
            text, markup = build_torrents_list_message(torrents, page=1, transfer_info=transfer_info)
            await safe_edit_message(query, text, markup)

        elif action == "v":
            # View single torrent details
            short_hash = parts[2] if len(parts) > 2 else ""
            torrent = await get_torrent_by_short_hash(short_hash)
            if not torrent:
                await query.answer("⚠️ Torrent not found or already removed.", show_alert=True)
                torrents = await get_torrents_info()
                text, markup = build_torrents_list_message(torrents, page=1)
                await safe_edit_message(query, text, markup)
                return

            text, markup = build_torrent_detail_message(torrent)
            await safe_edit_message(query, text, markup)
            await query.answer()

        elif action == "p":
            # Pause single torrent
            short_hash = parts[2] if len(parts) > 2 else ""
            torrent = await get_torrent_by_short_hash(short_hash)
            if not torrent:
                await query.answer("⚠️ Torrent not found.", show_alert=True)
                return
            await pause_torrents(torrent.hash)
            await query.answer("⏸️ Torrent paused.")
            updated = await get_torrent_by_short_hash(short_hash)
            if updated:
                text, markup = build_torrent_detail_message(updated)
                await safe_edit_message(query, text, markup)

        elif action == "r":
            # Resume single torrent
            short_hash = parts[2] if len(parts) > 2 else ""
            torrent = await get_torrent_by_short_hash(short_hash)
            if not torrent:
                await query.answer("⚠️ Torrent not found.", show_alert=True)
                return
            await resume_torrents(torrent.hash)
            await query.answer("▶️ Torrent resumed.")
            updated = await get_torrent_by_short_hash(short_hash)
            if updated:
                text, markup = build_torrent_detail_message(updated)
                await safe_edit_message(query, text, markup)

        elif action == "da":
            # Discard ask confirmation
            short_hash = parts[2] if len(parts) > 2 else ""
            torrent = await get_torrent_by_short_hash(short_hash)
            if not torrent:
                await query.answer("⚠️ Torrent not found.", show_alert=True)
                return
            text, markup = build_delete_confirm_message(torrent)
            await safe_edit_message(query, text, markup)
            await query.answer()

        elif action == "dk":
            # Discard keeping files
            short_hash = parts[2] if len(parts) > 2 else ""
            torrent = await get_torrent_by_short_hash(short_hash)
            if not torrent:
                await query.answer("⚠️ Torrent not found or already removed.")
            else:
                await delete_torrents(torrent.hash, delete_files=False)
                await query.answer("🗑️ Torrent removed (files kept on disk).", show_alert=True)

            torrents = await get_torrents_info()
            transfer_info = await get_transfer_info()
            text, markup = build_torrents_list_message(torrents, page=1, transfer_info=transfer_info)
            await safe_edit_message(query, text, markup)

        elif action == "df":
            # Discard and delete files
            short_hash = parts[2] if len(parts) > 2 else ""
            torrent = await get_torrent_by_short_hash(short_hash)
            if not torrent:
                await query.answer("⚠️ Torrent not found or already removed.")
            else:
                await delete_torrents(torrent.hash, delete_files=True)
                await query.answer("🔥 Torrent and files permanently deleted.", show_alert=True)

            torrents = await get_torrents_info()
            transfer_info = await get_transfer_info()
            text, markup = build_torrents_list_message(torrents, page=1, transfer_info=transfer_info)
            await safe_edit_message(query, text, markup)

        else:
            await query.answer()

    except Exception as e:
        logger.error(f"Error handling qbt action '{action}': {e}", exc_info=True)
        await query.answer(f"❌ Error: {e}", show_alert=True)

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

    # Delete searching status message
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
