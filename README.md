# Telegram qBittorrent Downloader Bot

A lightweight Telegram bot built with Python that connects to your local or remote qBittorrent Web UI. Send a magnet link or upload a `.torrent` file directly from Telegram to start downloads immediately.

---

## Features

- 📊 **Torrent Status & Control**: View all active or queued torrents via `/status`, `/torrents`, or `/list` with progress bars, speeds, sizes, and ETAs.
- ⏯️ **Interactive Management**: Pause, resume, and discard/delete torrents directly from Telegram inline buttons without typing hashes or commands.
- 🗑️ **Safe Deletion Options**: Choose between removing the torrent metadata from the client while preserving downloaded files or permanently deleting files from disk.
- ⏸️ **Bulk Controls**: Pause or resume all torrents simultaneously with `/pause_all`, `/resume_all`, or list view inline buttons.
- 🔍 **Movie Search (YTS)**: Search for movies via `/search <name>` or `/movie <name>`, view up to 5 results with details, and tap a quality option button to queue the magnet link directly.
- 🧲 **Magnet Links**: Automatically extracts and queues magnet links sent in chat.
- 📁 **.torrent File Support**: Download and queue torrent files sent as documents.
- 🔒 **User Authorization**: Restricts bot usage to a specific Telegram user ID.
- ⚡ **Non-Blocking Architecture**: Handles qBittorrent and HTTP search API calls asynchronously to ensure uninterrupted bot responsiveness.
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
   git clone https://github.com/axaiem/telegram-qbittorrent-bot.git
   cd telegram-qbittorrent-bot
   ```

2. **Install and sync dependencies with `uv` (Recommended):**
   ```bash
   uv sync
   ```

   *(Alternative with traditional `venv` and `pip`:)*
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
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

Start the bot with `uv`:
```bash
uv run python bot.py
```

*(Or within an activated virtual environment: `python3 bot.py`)*

Then in Telegram:
1. Send `/start` to verify connectivity and see available commands.
2. Check your torrents with `/status` or `/torrents` to view progress bars, speeds, and interact (pause, resume, discard/delete).
3. Search movies with `/search <title>` (e.g. `/search Inception`) and click any quality button (`720p`, `1080p`, etc.) to queue it.
4. Send any magnet link starting with `magnet:?`.
5. Or attach/forward any `.torrent` file.
6. Use `/pause_all` or `/resume_all` for quick bulk control.
