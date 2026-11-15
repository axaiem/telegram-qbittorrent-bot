import asyncio
import logging
from qbittorrentapi import Client
from src.config import QBITTORRENT_HOST, QBITTORRENT_USER, QBITTORRENT_PASS

logger = logging.getLogger(__name__)

qbt_client = Client(host=QBITTORRENT_HOST, username=QBITTORRENT_USER, password=QBITTORRENT_PASS)

def ensure_qbt_login() -> bool:
    """Ensure connection to qBittorrent Web UI."""
    try:
        if not qbt_client.is_logged_in:
            qbt_client.auth_log_in()
        return True
    except Exception:
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

async def get_torrents_info(
    status_filter: str | None = None,
    sort: str | None = "added_on",
    reverse: bool = True,
    torrent_hashes: str | list[str] | None = None,
) -> list:
    """Retrieve list of torrents from qBittorrent."""
    if not ensure_qbt_login():
        raise ConnectionError("Could not connect to qBittorrent Web UI. Please ensure it is running.")
    return await asyncio.to_thread(
        qbt_client.torrents_info,
        status_filter=status_filter,
        sort=sort,
        reverse=reverse,
        torrent_hashes=torrent_hashes,
    )

async def get_torrent_info(torrent_hash: str):
    """Retrieve single torrent information by hash."""
    if not ensure_qbt_login():
        raise ConnectionError("Could not connect to qBittorrent Web UI. Please ensure it is running.")
    torrents = await asyncio.to_thread(
        qbt_client.torrents_info,
        torrent_hashes=torrent_hash,
    )
    return torrents[0] if torrents else None

async def get_torrent_by_short_hash(short_hash: str):
    """Look up a torrent by the leading prefix of its info_hash."""
    torrents = await get_torrents_info(sort="added_on", reverse=True)
    target = short_hash.lower()
    for t in torrents:
        if t.hash.lower().startswith(target):
            return t
    return None

async def pause_torrents(torrent_hashes: str | list[str] = "all") -> None:
    """Pause/stop one or more torrents (or 'all')."""
    if not ensure_qbt_login():
        raise ConnectionError("Could not connect to qBittorrent Web UI. Please ensure it is running.")
    await asyncio.to_thread(qbt_client.torrents_pause, torrent_hashes=torrent_hashes)

async def resume_torrents(torrent_hashes: str | list[str] = "all") -> None:
    """Resume/start one or more torrents (or 'all')."""
    if not ensure_qbt_login():
        raise ConnectionError("Could not connect to qBittorrent Web UI. Please ensure it is running.")
    await asyncio.to_thread(qbt_client.torrents_resume, torrent_hashes=torrent_hashes)

async def delete_torrents(torrent_hashes: str | list[str], delete_files: bool = False) -> None:
    """Delete one or more torrents, optionally removing files."""
    if not ensure_qbt_login():
        raise ConnectionError("Could not connect to qBittorrent Web UI. Please ensure it is running.")
    await asyncio.to_thread(
        qbt_client.torrents_delete,
        delete_files=delete_files,
        torrent_hashes=torrent_hashes,
    )

async def get_transfer_info():
    """Retrieve global transfer info (speeds, connection status, etc.)."""
    if not ensure_qbt_login():
        return None
    try:
        return await asyncio.to_thread(qbt_client.transfer_info)
    except Exception as e:
        logger.warning(f"Failed to get transfer info: {e}")
        return None
