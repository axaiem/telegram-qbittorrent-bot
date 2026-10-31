import asyncio
import logging
from qbittorrentapi import Client
from src.config import QBITTORRENT_HOST, QBITTORRENT_USER, QBITTORRENT_PASS

logger = logging.getLogger(__name__)

qbt_client = Client(host=QBITTORRENT_HOST, username=QBITTORRENT_USER, password=QBITTORRENT_PASS)

def ensure_qbt_login() -> bool:
    """Ensure connection to qBittorrent Web UI."""
    try:
        qbt_client.auth_log_in()
        return True
    except Exception as e:
        logger.warning(f"Could not connect to qBittorrent: {e}")
        return False

async def add_magnet(magnet_link: str) -> str:
    """Add a magnet link to qBittorrent asynchronously."""
    ensure_qbt_login()
    return await asyncio.to_thread(qbt_client.torrents_add, urls=magnet_link)

async def add_torrent_file(torrent_bytes: bytes) -> str:
    """Add a torrent file by bytes to qBittorrent asynchronously."""
    ensure_qbt_login()
    return await asyncio.to_thread(qbt_client.torrents_add, torrent_files=torrent_bytes)
