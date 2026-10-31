import os
from dotenv import load_dotenv

# Load variables from local .env (if present) and ~/.zshrc
load_dotenv()
load_dotenv(os.path.expanduser("~/.zshrc"), verbose=False)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QBITTORRENT_HOST = os.getenv("QBITTORRENT_HOST", "http://localhost:8080")
QBITTORRENT_USER = os.getenv("QBIT_TORRENT_USER", os.getenv("QBITTORRENT_USER", "admin"))
QBITTORRENT_PASS = os.getenv("QBIT_TORRENT_PASS_ADMIN", os.getenv("QBITTORRENT_PASS", ""))

allowed_user_id_raw = os.getenv("TELEGRAM_USER_ID", os.getenv("ALLOWED_USER_ID", "0"))
ALLOWED_USER_ID = int(allowed_user_id_raw) if allowed_user_id_raw and allowed_user_id_raw.isdigit() else 0

# YTS API Configuration (can be overridden via environment variables for mirrors/proxies)
YTS_BASE_URL = os.getenv("YTS_BASE_URL", "https://yts.mx").rstrip("/")
