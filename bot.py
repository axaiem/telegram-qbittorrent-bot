"""Entrypoint for Telegram qBittorrent Bot."""
import sys
import logging
from telegram import request
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from src.config import TELEGRAM_BOT_TOKEN
from src.services.qbittorrent_service import ensure_qbt_login
from src.handlers.telegram_handlers import (
    start_handler,
    search_movie_handler,
    torrent_selection_callback,
    message_handler,
    document_handler,
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print(
            "\n❌ Error: TELEGRAM_BOT_TOKEN is missing or not set!\n"
            "Please ensure it is defined in a .env file or exported in ~/.zshrc:\n"
            '  export TELEGRAM_BOT_TOKEN="your_bot_token"\n'
            '  export TELEGRAM_USER_ID="your_telegram_id"\n'
        )
        sys.exit(1)

    # Pre-check qBittorrent connection
    ensure_qbt_login()

    # Network timeout configuration
    t_request = request.HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
    )

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).request(t_request).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", start_handler))
    app.add_handler(CommandHandler("search", search_movie_handler))
    app.add_handler(CommandHandler("movie", search_movie_handler))
    app.add_handler(CallbackQueryHandler(torrent_selection_callback, pattern=r"^dl:"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()