# Telegram qBittorrent Downloader Bot

A lightweight Telegram bot built with Python that connects to your local or remote qBittorrent Web UI. Send a magnet link or upload a `.torrent` file directly from Telegram to start downloads immediately.

---

## Features

- 🧲 **Magnet Links**: Automatically extracts and queues magnet links sent in chat.
- 📁 **.torrent File Support**: Download and queue torrent files sent as documents.
- 🔒 **User Authorization**: Restricts bot usage to a specific Telegram user ID.
- ⚡ **Non-Blocking Architecture**: Handles qBittorrent API calls asynchronously via thread pools to ensure uninterrupted bot responsiveness.
- 🔑 **Flexible Environment Configuration**: Automatically loads credentials from local `.env` files, environment variables, or your shell profile (`~/.zshrc`).

---

## Prerequisites

1. **Python 3.10+**
2. **qBittorrent** with Web UI enabled:
   - Open qBittorrent -> **Preferences** -> **Web UI**.
   - Check **Web User Interface (Remote control)**.
   - Set IP/Port (default: `localhost:8080`).
   - Set username & password.

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/telegram-qbittorrent-bot.git
   cd telegram-qbittorrent-bot
   ```

2. **Create a virtual environment (optional but recommended):**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your details:
```env
TELEGRAM_BOT_TOKEN="your_bot_token_from_botfather"
TELEGRAM_USER_ID="your_numeric_telegram_user_id"
QBITTORRENT_HOST="http://localhost:8080"
QBIT_TORRENT_USER="admin"
QBIT_TORRENT_PASS_ADMIN="your_password"
```

> **Tip:** You can also export these directly in your `~/.zshrc` or system environment.

---

## Usage

Start the bot:
```bash
python3 bot.py
```

Then in Telegram:
1. Send `/start` to verify connectivity.
2. Send any magnet link starting with `magnet:?`.
3. Or attach/forward any `.torrent` file.
