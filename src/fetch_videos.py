"""Pobieranie nowych filmów przez YouTube Data API v3.

Filtr: tylko filmy dłuższe niż 5 minut (odcina też wszystkie Shorts).
Okno: ostatnie WINDOW_HOURS godzin — deduplikacja w db łapie zakładki między runami.

Koszt kwoty (10 000 jednostek/dzień): ~3 jednostki na kanał i run.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

from . import db

CHANNELS_FILE = Path(__file__).parent.parent / "channels.json"
WINDOW_HOURS = 168         # ostatni tydzień; dedup w bazie i tak analizuje tylko nowe
MIN_DURATION_S = 300       # filmy <= 5 min odpadają
MAX_RESULTS_PER_CHANNEL = 25   # tydzień aktywnego kanału; playlistItems.list = 1 jednostka bez względu na liczbę

_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_duration(iso: str) -> int:
    """ISO 8601 (PT1H2M3S) -> sekundy. Nietypowe wartości (np. P0D dla live) -> 0."""
    m = _DURATION_RE.fullmatch(iso or "")
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def passes_filter(duration_s: int) -> bool:
    """True tylko dla filmów dłuższych niż 5 minut (Shorts nigdy nie przechodzą)."""
    return duration_s > MIN_DURATION_S


def load_channels() -> list[dict]:
    return json.loads(CHANNELS_FILE.read_text())["channels"]


def _yt():
    load_dotenv()
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise SystemExit("Brak YOUTUBE_API_KEY — uzupełnij .env (instrukcja w README).")
    return build("youtube", "v3", developerKey=key, cache_discovery=False)


def _handle_from_url(url: str) -> str | None:
    m = re.search(r"youtube\.com/@([\w.\-]+)", url or "")
    return m.group(1) if m else None


def resolve_channel(yt, conn, entry: dict) -> tuple[str, str]:
    """channels.json entry -> (channel_id, uploads_playlist_id), z cache w db."""
    cache_key = entry.get("channel_id") or entry["url"]
    cached = db.get_channel_cache(conn, cache_key)
    if cached:
        return cached["channel_id"], cached["uploads_playlist"]

    if entry.get("channel_id"):
        resp = yt.channels().list(part="contentDetails", id=entry["channel_id"]).execute()
    else:
        handle = _handle_from_url(entry["url"])
        if not handle:
            raise ValueError(f"Nie umiem wyciągnąć handle z url: {entry['url']}")
        resp = yt.channels().list(part="contentDetails", forHandle=handle).execute()

    items = resp.get("items", [])
    if not items:
        raise LookupError(f"Kanał nie znaleziony: {entry['name']} ({cache_key})")
    channel_id = items[0]["id"]
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    db.save_channel_cache(conn, cache_key, channel_id, uploads)
    return channel_id, uploads


def fetch_new(conn, window_hours: int = WINDOW_HOURS) -> list[dict]:
    """Rejestruje w db nowe filmy >5 min ze wszystkich kanałów. Zwraca dodane."""
    yt = _yt()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    added: list[dict] = []

    for entry in load_channels():
        try:
            channel_id, uploads = resolve_channel(yt, conn, entry)
        except (LookupError, ValueError) as e:
            print(f"  ! pomijam kanał: {e}")
            continue

        items = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads, maxResults=MAX_RESULTS_PER_CHANNEL
        ).execute().get("items", [])

        fresh_ids = [
            it["contentDetails"]["videoId"]
            for it in items
            if datetime.fromisoformat(
                it["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00")
            ) >= cutoff
        ]
        fresh_ids = [vid for vid in fresh_ids if not db.video_seen(conn, vid)]
        if not fresh_ids:
            continue

        details = yt.videos().list(
            part="snippet,contentDetails", id=",".join(fresh_ids)
        ).execute().get("items", [])

        for v in details:
            duration_s = parse_duration(v["contentDetails"]["duration"])
            if not passes_filter(duration_s):
                print(f"  - odfiltrowany ({duration_s}s): {v['snippet']['title'][:60]}")
                continue
            video = dict(
                video_id=v["id"],
                channel_id=channel_id,
                channel_name=entry["name"],
                title=v["snippet"]["title"],
                published_at=v["snippet"]["publishedAt"],
                duration_s=duration_s,
            )
            if db.add_video(conn, **video):
                added.append(video)
                print(f"  + [{entry['name']}] {video['title'][:70]} ({duration_s // 60} min)")

    return added


if __name__ == "__main__":
    conn = db.connect()
    new = fetch_new(conn)
    print(f"\nNowych filmów: {len(new)}")
