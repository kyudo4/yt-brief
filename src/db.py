"""SQLite: filmy, transkrypcje, wyciągi, tematy i ich historia.

Baza jest commitowana do repo (data/brief.db) — patrz README, sekcja "Dlaczego
baza w repo". Wszystkie zapisy idą przez ten moduł.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("BRIEF_DB", Path(__file__).parent.parent / "data" / "brief.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    url              TEXT PRIMARY KEY,   -- url/handle z channels.json (klucz cache)
    channel_id       TEXT NOT NULL,
    uploads_playlist TEXT NOT NULL,
    resolved_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    video_id     TEXT PRIMARY KEY,
    channel_id   TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    title        TEXT NOT NULL,
    published_at TEXT NOT NULL,           -- ISO 8601 UTC
    duration_s   INTEGER NOT NULL,
    url          TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new',
                 -- new | transcribed | analyzed | no_transcript | error
    error        TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
    video_id   TEXT PRIMARY KEY REFERENCES videos(video_id),
    lang       TEXT NOT NULL,             -- np. 'pl', 'en'
    generated  INTEGER NOT NULL,          -- 1 = napisy auto-generowane
    text       TEXT NOT NULL,             -- pełny tekst z timestampami [mm:ss]
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extracts (
    video_id   TEXT PRIMARY KEY REFERENCES videos(video_id),
    data       TEXT NOT NULL,             -- JSON: tezy, sentyment, tickery, cytaty...
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,             -- YYYY-MM-DD (dzień briefu)
    title      TEXT NOT NULL,
    teaser     TEXT NOT NULL,             -- jedno zdanie do Telegrama
    keywords   TEXT NOT NULL,             -- JSON list[str], lowercase
    tickers    TEXT NOT NULL,             -- JSON list[str], uppercase
    card       TEXT NOT NULL,             -- JSON pełnej karty tematu
    parent_id  INTEGER REFERENCES topics(id),  -- temat z poprzednich dni (tryb "aktualizacja")
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topics_date ON topics(date);

CREATE TABLE IF NOT EXISTS topic_videos (
    topic_id INTEGER NOT NULL REFERENCES topics(id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    PRIMARY KEY (topic_id, video_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --- cache kanałów ---

def get_channel_cache(conn, url: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM channels WHERE url = ?", (url,)).fetchone()


def save_channel_cache(conn, url: str, channel_id: str, uploads_playlist: str):
    conn.execute(
        "INSERT OR REPLACE INTO channels (url, channel_id, uploads_playlist, resolved_at) VALUES (?, ?, ?, ?)",
        (url, channel_id, uploads_playlist, _now()),
    )
    conn.commit()


# --- filmy ---

def video_seen(conn, video_id: str) -> bool:
    """Deduplikacja: True jeśli film był już kiedykolwiek zarejestrowany."""
    return conn.execute("SELECT 1 FROM videos WHERE video_id = ?", (video_id,)).fetchone() is not None


def add_video(conn, *, video_id, channel_id, channel_name, title, published_at, duration_s) -> bool:
    """Rejestruje nowy film. Zwraca False, jeśli już był w bazie (nic nie nadpisuje)."""
    if video_seen(conn, video_id):
        return False
    conn.execute(
        "INSERT INTO videos (video_id, channel_id, channel_name, title, published_at, duration_s, url, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (video_id, channel_id, channel_name, title, published_at, duration_s,
         f"https://www.youtube.com/watch?v={video_id}", _now()),
    )
    conn.commit()
    return True


def set_video_status(conn, video_id: str, status: str, error: str | None = None):
    conn.execute("UPDATE videos SET status = ?, error = ? WHERE video_id = ?", (status, error, video_id))
    conn.commit()


def videos_by_status(conn, status: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM videos WHERE status = ? ORDER BY published_at", (status,)).fetchall()


# --- transkrypcje ---

def save_transcript(conn, video_id: str, lang: str, generated: bool, text: str):
    conn.execute(
        "INSERT OR REPLACE INTO transcripts (video_id, lang, generated, text, created_at) VALUES (?, ?, ?, ?, ?)",
        (video_id, lang, int(generated), text, _now()),
    )
    set_video_status(conn, video_id, "transcribed")


def get_transcript(conn, video_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()


# --- wyciągi ---

def save_extract(conn, video_id: str, data: dict, model: str):
    conn.execute(
        "INSERT OR REPLACE INTO extracts (video_id, data, model, created_at) VALUES (?, ?, ?, ?)",
        (video_id, json.dumps(data, ensure_ascii=False), model, _now()),
    )
    set_video_status(conn, video_id, "analyzed")


def extracts_for_date(conn, date: str) -> list[dict]:
    """Wyciągi z filmów opublikowanych w oknie briefu (ostatnie 24h przed datą)."""
    rows = conn.execute(
        """SELECT e.video_id, e.data, v.channel_name, v.title, v.url, v.published_at
           FROM extracts e JOIN videos v USING (video_id)
           WHERE v.status = 'analyzed' AND date(v.published_at) >= date(?, '-1 day')
           ORDER BY v.published_at""",
        (date,),
    ).fetchall()
    return [dict(r, data=json.loads(r["data"])) for r in rows]


# --- tematy ---

def save_topic(conn, *, date, title, teaser, keywords, tickers, card, parent_id=None, video_ids=()) -> int:
    cur = conn.execute(
        "INSERT INTO topics (date, title, teaser, keywords, tickers, card, parent_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (date, title, teaser,
         json.dumps([k.lower() for k in keywords], ensure_ascii=False),
         json.dumps([t.upper() for t in tickers], ensure_ascii=False),
         json.dumps(card, ensure_ascii=False), parent_id, _now()),
    )
    for vid in video_ids:
        conn.execute("INSERT OR IGNORE INTO topic_videos (topic_id, video_id) VALUES (?, ?)", (cur.lastrowid, vid))
    conn.commit()
    return cur.lastrowid


def update_topic_card(conn, topic_id: int, card: dict):
    conn.execute("UPDATE topics SET card = ? WHERE id = ?",
                 (json.dumps(card, ensure_ascii=False), topic_id))
    conn.commit()


def topics_for_date(conn, date: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM topics WHERE date = ? ORDER BY id", (date,)).fetchall()
    return [_topic_row(r) for r in rows]


def find_related_topic(conn, keywords: list[str], tickers: list[str], before_date: str, days_back: int = 7) -> dict | None:
    """Pamięć tematów: najlepiej pasujący temat z ostatnich `days_back` dni.

    Dopasowanie po części wspólnej słów kluczowych i tickerów; wygrywa temat
    z największą liczbą trafień (min. 2 trafienia albo 1 wspólny ticker).
    """
    kw = {k.lower() for k in keywords}
    tk = {t.upper() for t in tickers}
    rows = conn.execute(
        "SELECT * FROM topics WHERE date < ? AND date >= date(?, ?) ORDER BY date DESC",
        (before_date, before_date, f"-{days_back} days"),
    ).fetchall()
    best, best_score = None, 0
    for r in rows:
        kw_hits = len(kw & set(json.loads(r["keywords"])))
        tk_hits = len(tk & set(json.loads(r["tickers"])))
        score = kw_hits + 2 * tk_hits
        if (kw_hits + tk_hits >= 2 or tk_hits >= 1) and score > best_score:
            best, best_score = r, score
    return _topic_row(best) if best else None


def _topic_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for field in ("keywords", "tickers", "card"):
        d[field] = json.loads(d[field])
    return d
