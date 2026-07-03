"""Testy deduplikacji i pamięci tematów (kryterium akceptacji: drugi run
tego samego dnia nie analizuje ponownie tych samych filmów)."""

import os

import pytest


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIEF_DB", str(tmp_path / "test.db"))
    # przeładowanie DB_PATH po zmianie env
    from src import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _add(conn, vid="abc123"):
    from src import db
    return db.add_video(
        conn, video_id=vid, channel_id="UCx", channel_name="Testowy",
        title="Film testowy", published_at="2026-07-03T05:00:00+00:00", duration_s=600,
    )


def test_dedup_drugi_insert_odrzucony(conn):
    assert _add(conn) is True
    assert _add(conn) is False  # ten sam video_id → nie analizujemy ponownie


def test_status_flow(conn):
    from src import db
    _add(conn)
    db.save_transcript(conn, "abc123", "pl", generated=True, text="[00:00] cześć")
    db.save_extract(conn, "abc123", {"tezy": ["x"]}, model="claude-haiku-4-5-20251001")
    assert conn.execute("SELECT status FROM videos WHERE video_id='abc123'").fetchone()[0] == "analyzed"
    # film 'analyzed' nie wraca do kolejki nowych
    assert db.videos_by_status(conn, "new") == []


def test_pamiec_tematow_dopasowanie_po_tickerze(conn):
    from src import db
    tid = db.save_topic(
        conn, date="2026-07-02", title="Halving a cena BTC", teaser="t",
        keywords=["halving", "podaż"], tickers=["BTC"], card={},
    )
    hit = db.find_related_topic(conn, keywords=["cena"], tickers=["btc"], before_date="2026-07-03")
    assert hit and hit["id"] == tid


def test_pamiec_tematow_brak_dopasowania(conn):
    from src import db
    db.save_topic(conn, date="2026-07-02", title="ETH ETF", teaser="t",
                  keywords=["etf", "ethereum"], tickers=["ETH"], card={})
    assert db.find_related_topic(conn, keywords=["stopy"], tickers=["DXY"], before_date="2026-07-03") is None
