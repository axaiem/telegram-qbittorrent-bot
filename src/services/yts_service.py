import logging
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional
import httpx
from src.config import YTS_BASE_URL

logger = logging.getLogger(__name__)

TRACKERS = [
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80",
    "udp://tracker.coppersurfer.tk:6969",
    "udp://glotorrents.pw:6969/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://torrent.gresille.org:80/announce",
    "udp://p4p.arenabg.com:1337",
    "udp://tracker.leechers-paradise.org:6969",
]

@dataclass
class TorrentOption:
    quality: str
    type: str
    size: str
    hash: str
    seeds: int
    peers: int

@dataclass
class MovieResult:
    id: int
    title: str
    year: int
    rating: float
    summary: str
    torrents: List[TorrentOption]

def build_magnet_uri(info_hash: str, movie_title: str) -> str:
    """Construct a magnet URI from info_hash, display title, and standard trackers."""
    encoded_title = urllib.parse.quote_plus(movie_title)
    trackers_str = "".join(f"&tr={urllib.parse.quote_plus(tracker)}" for tracker in TRACKERS)
    return f"magnet:?xt=urn:btih:{info_hash}&dn={encoded_title}{trackers_str}"

def _format_size(size_bytes: int) -> str:
    """Format bytes into readable size string."""
    try:
        size = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"
    except Exception:
        return "N/A"

async def _search_apibay_fallback(query: str, limit: int = 5) -> List[MovieResult]:
    """Fallback search using APIBay when YTS is blocked or unreachable."""
    url = "https://apibay.org/q.php"
    params = {"q": query}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            items = resp.json()

        if not items or items[0].get("name") == "No results returned":
            return []

        results: List[MovieResult] = []
        for item in items[:limit]:
            info_hash = item.get("info_hash", "")
            if not info_hash:
                continue

            raw_size = int(item.get("size", 0)) if str(item.get("size", "")).isdigit() else 0
            size_str = _format_size(raw_size)
            seeds = int(item.get("seeders", 0)) if str(item.get("seeders", "")).isdigit() else 0
            peers = int(item.get("leechers", 0)) if str(item.get("leechers", "")).isdigit() else 0
            name = item.get("name", "Torrent")

            # Single torrent option per release
            torrent_opt = TorrentOption(
                quality=f"{seeds} seeds",
                type="",
                size=size_str,
                hash=info_hash,
                seeds=seeds,
                peers=peers,
            )

            results.append(
                MovieResult(
                    id=int(item.get("id", 0)) if str(item.get("id", "")).isdigit() else 0,
                    title=name,
                    year=0,
                    rating=0.0,
                    summary=f"Seeds: {seeds} | Leechers: {peers} | Size: {size_str}",
                    torrents=[torrent_opt],
                )
            )

        return results
    except Exception as e:
        logger.error(f"Fallback search (APIBay) also failed: {e}")
        return []

async def search_movies(query: str, limit: int = 5) -> List[MovieResult]:
    """Search movies using YTS API, with automatic fallback to APIBay if YTS fails/times out."""
    endpoint = f"{YTS_BASE_URL}/api/v2/list_movies.json"
    params = {
        "query_term": query,
        "limit": limit,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True, headers=headers) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") == "ok":
            movie_data = data.get("data", {}).get("movies", [])
            if movie_data:
                results: List[MovieResult] = []
                for item in movie_data[:limit]:
                    torrents: List[TorrentOption] = []
                    for t in item.get("torrents", []):
                        torrents.append(
                            TorrentOption(
                                quality=t.get("quality", "Unknown"),
                                type=t.get("type", ""),
                                size=t.get("size", "N/A"),
                                hash=t.get("hash", ""),
                                seeds=t.get("seeds", 0),
                                peers=t.get("peers", 0),
                            )
                        )

                    results.append(
                        MovieResult(
                            id=item.get("id", 0),
                            title=item.get("title_long") or item.get("title", "Unknown"),
                            year=item.get("year", 0),
                            rating=float(item.get("rating", 0.0)),
                            summary=item.get("summary", ""),
                            torrents=torrents,
                        )
                    )
                return results
    except Exception as e:
        logger.warning(f"YTS API failed ({e}), falling back to APIBay search index...")

    # Fallback to APIBay
    return await _search_apibay_fallback(query, limit=limit)
