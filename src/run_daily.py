"""Pełny dzienny obieg: python -m src.run_daily

Etapy dochodzą w kolejnych krokach budowy — każdy podpinany tutaj.
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import analyze, build_site, db, drafts, fetch_videos, market_data, notify, topics, transcripts


def main() -> int:
    today = datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%Y-%m-%d")
    print(f"yt-brief — obieg dzienny {today}")

    conn = db.connect()
    print(f"[1/8] baza OK: {db.DB_PATH}")

    print("[2/8] nowe filmy z YouTube...")
    new = fetch_videos.fetch_new(conn)
    print(f"      dodano: {len(new)}")

    print("[3/8] transkrypcje...")
    stats = transcripts.fetch_pending(conn)
    print(f"      {stats}")

    print("[4/8] analiza wyciągów (Haiku)...")
    astats = analyze.run(conn)
    print(f"      {astats}")

    print("[5/8] tematy dnia...")
    topic_ids = topics.group(conn, today)
    print(f"      tematów: {len(topic_ids)}")

    print("[6/8] twarde dane + wykresy...")
    market_data.enrich_topics(conn, topic_ids, today)

    print("[7/8] drafty na X (Sonnet) + strona...")
    n = drafts.generate(conn, topic_ids, today)
    out = build_site.build(conn, today)
    print(f"      draftów: {n}, strona: {out}")

    print("[8/8] telegram...")
    notify.send(conn, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
