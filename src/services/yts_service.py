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

async def search_movies(query: str, limit: int = 5) -> List[MovieResult]:
    """Search movies using the YTS API with a limit of results (max 5)."""
    endpoint = f"{YTS_BASE_URL}/api/v2/list_movies.json"
    params = {
        "query_term": query,
        "limit": limit,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
        response = await client.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()

    if data.get("status") != "ok":
        logger.warning(f"YTS API returned non-ok status: {data.get('status_message')}")
        return []

    movie_data = data.get("data", {}).get("movies", [])
    if not movie_data:
        return []

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
