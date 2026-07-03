"""Transkrypcje przez youtube-transcript-api (>=1.0).

Priorytet: ręczne PL -> auto PL -> ręczne EN -> auto EN -> cokolwiek jest.
Film bez żadnych napisów dostaje status 'no_transcript' i jest logowany.

Tekst zapisujemy w blokach ~60 s z markerem [mm:ss] na początku bloku —
dzięki temu Haiku może cytować z timestampem, a linki z kart prowadzą
do właściwego momentu filmu (&t=...s).
"""

from __future__ import annotations

from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

from . import db

LANGS = ["pl", "en"]
BLOCK_S = 60


def _pick(transcript_list):
    """Najlepsza dostępna ścieżka napisów wg priorytetu."""
    for finder in (transcript_list.find_manually_created_transcript,
                   transcript_list.find_generated_transcript):
        for lang in LANGS:
            try:
                return finder([lang])
            except NoTranscriptFound:
                continue
    # ostatnia deska: pierwsza jakakolwiek ścieżka
    for t in transcript_list:
        return t
    return None


def format_snippets(snippets) -> str:
    """Snippety -> bloki ~60 s: '[mm:ss] tekst tekst...'"""
    blocks: list[str] = []
    current: list[str] = []
    block_start = 0.0
    for s in snippets:
        text = s.text.replace("\n", " ").strip()
        if not text:
            continue
        if not current:
            block_start = s.start
        current.append(text)
        if s.start - block_start >= BLOCK_S:
            blocks.append(_stamp(block_start) + " " + " ".join(current))
            current = []
    if current:
        blocks.append(_stamp(block_start) + " " + " ".join(current))
    return "\n".join(blocks)


def _stamp(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"[{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}]"
    return f"[{s // 60:02d}:{s % 60:02d}]"


def fetch_one(video_id: str) -> tuple[str, bool, str] | None:
    """(lang, generated, text) albo None gdy brak napisów."""
    api = YouTubeTranscriptApi()
    try:
        transcript = _pick(api.list(video_id))
    except (TranscriptsDisabled, VideoUnavailable):
        return None
    if transcript is None:
        return None
    fetched = transcript.fetch()
    return transcript.language_code, transcript.is_generated, format_snippets(fetched)


def fetch_pending(conn) -> dict:
    """Ściąga napisy dla wszystkich filmów o statusie 'new'."""
    stats = {"ok": 0, "no_transcript": 0, "error": 0}
    for v in db.videos_by_status(conn, "new"):
        vid = v["video_id"]
        try:
            result = fetch_one(vid)
        except Exception as e:  # sieć, blokady IP itp. — nie wywalaj całego runu
            print(f"  ! błąd transkrypcji {vid}: {type(e).__name__}: {e}")
            db.set_video_status(conn, vid, "error", f"transcript: {e}")
            stats["error"] += 1
            continue
        if result is None:
            print(f"  - brak napisów: [{v['channel_name']}] {v['title'][:60]}")
            db.set_video_status(conn, vid, "no_transcript")
            stats["no_transcript"] += 1
            continue
        lang, generated, text = result
        db.save_transcript(conn, vid, lang, generated, text)
        kind = "auto" if generated else "ręczne"
        print(f"  + napisy {lang} ({kind}), {len(text)} zn.: {v['title'][:55]}")
        stats["ok"] += 1
    return stats


if __name__ == "__main__":
    conn = db.connect()
    print(fetch_pending(conn))
