import os
import sys
import asyncio
import logging
from telegram import Update, request
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from qbittorrentapi import Client

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv

# Load variables from local .env (if present) and ~/.zshrc
load_dotenv()  # looks for .env in current directory
load_dotenv(os.path.expanduser("~/.zshrc"), verbose=False)

# Configuration (read from .env / ~/.zshrc or environment)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QBITTORRENT_HOST = os.getenv("QBITTORRENT_HOST", "http://localhost:8080")
QBITTORRENT_USER = os.getenv("QBIT_TORRENT_USER", os.getenv("QBITTORRENT_USER", "admin"))
QBITTORRENT_PASS = os.getenv("QBIT_TORRENT_PASS_ADMIN", os.getenv("QBITTORRENT_PASS", ""))

allowed_user_id_raw = os.getenv("TELEGRAM_USER_ID", os.getenv("ALLOWED_USER_ID", "0"))
ALLOWED_USER_ID = int(allowed_user_id_raw) if allowed_user_id_raw and allowed_user_id_raw.isdigit() else 0

# Initialize qBittorrent client
qbt_client = Client(host=QBITTORRENT_HOST, username=QBITTORRENT_USER, password=QBITTORRENT_PASS)

def ensure_qbt_login():
    """Ensure connection to qBittorrent Web UI."""
    try:
        qbt_client.auth_log_in()
        return True
    except Exception as e:
        logger.warning(f"Could not connect to qBittorrent: {e}")
        return False

# Initial login check
ensure_qbt_login()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("Unauthorized access.")
        return
    await update.message.reply_text("Send me a magnet link or a .torrent file to start downloading!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    text = update.message.text
    if text and text.startswith("magnet:?"):
        ensure_qbt_login()
        try:
            # Run blocking qBittorrent API calls in a separate thread to keep bot responsive
            res = await asyncio.to_thread(qbt_client.torrents_add, urls=text)
            if res == "Ok.":
                await update.message.reply_text("✅ Magnet link added to qBittorrent download queue!")
            else:
                await update.message.reply_text(f"⚠️ Response from qBittorrent: {res}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding magnet link: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    doc = update.message.document
    if doc and doc.file_name and doc.file_name.endswith(".torrent"):
        ensure_qbt_login()
        try:
            file = await context.bot.get_file(doc.file_id)
            file_bytes = await file.download_as_bytearray()
            res = await asyncio.to_thread(
                qbt_client.torrents_add, torrent_files=bytes(file_bytes)
            )
            if res == "Ok.":
                await update.message.reply_text("✅ .torrent file uploaded and added to downloads!")
            else:
                await update.message.reply_text(f"⚠️ Response from qBittorrent: {res}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding .torrent file: {e}")

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print(
            "\n❌ Error: TELEGRAM_BOT_TOKEN is missing or not set!\n"
            "Please ensure it is defined in a .env file or exported in ~/.zshrc:\n"
            '  export TELEGRAM_BOT_TOKEN="your_bot_token"\n'
            '  export TELEGRAM_USER_ID="your_telegram_id"\n'
        )
        sys.exit(1)

    # Increase network timeouts to prevent premature TimedOut errors
    t_request = request.HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
    )

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).request(t_request).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Bot is running...")
    app.run_polling()