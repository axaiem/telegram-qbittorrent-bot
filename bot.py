import os
import sys
import fcntl
import tempfile
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

import signal
import time

# Single instance lock mechanism
_lock_file = None

def acquire_instance_lock():
    """Ensures only one bot instance runs by terminating any previously running instance."""
    global _lock_file
    lock_file_path = os.path.join(tempfile.gettempdir(), "telegram_qbittorrent_bot.lock")

    for attempt in range(5):
        try:
            # Open file in r+ mode if it exists, or create it if not
            if not os.path.exists(lock_file_path):
                _lock_file = open(lock_file_path, "w+")
            else:
                _lock_file = open(lock_file_path, "r+")

            # Try to acquire non-blocking lock
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Successfully locked, write current PID
            _lock_file.seek(0)
            _lock_file.truncate()
            _lock_file.write(str(os.getpid()))
            _lock_file.flush()
            return

        except (IOError, BlockingIOError):
            # Another process holds the lock
            try:
                with open(lock_file_path, "r") as f:
                    content = f.read().strip()
                if content.isdigit():
                    old_pid = int(content)
                    if old_pid != os.getpid():
                        logger.warning(
                            f"Existing bot instance found (PID: {old_pid}). Terminating it to take over..."
                        )
                        print(f"⚠️ Terminating existing bot instance (PID: {old_pid})...")
                        os.kill(old_pid, signal.SIGTERM)
                        # Wait briefly for process to exit and release lock
                        time.sleep(1.0)
                        # If still alive after SIGTERM, send SIGKILL
                        try:
                            os.kill(old_pid, 0)
                            os.kill(old_pid, signal.SIGKILL)
                            time.sleep(0.5)
                        except OSError:
                            pass
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.debug(f"Error while terminating old process: {e}")
                time.sleep(0.5)

    print("\n❌ Error: Could not acquire bot instance lock after terminating previous process.")
    sys.exit(1)

def main():
    acquire_instance_lock()

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