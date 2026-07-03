"""Pełny dzienny obieg: python -m src.run_daily

Etapy dochodzą w kolejnych krokach budowy — każdy podpinany tutaj.
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import analyze, build_site, db, drafts, fetch_videos, market_data, topics, transcripts


def main() -> int:
    today = datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%Y-%m-%d")
    print(f"yt-brief — obieg dzienny {today}")

    conn = db.connect()
    print(f"[1/7] baza OK: {db.DB_PATH}")

    print("[2/7] nowe filmy z YouTube...")
    new = fetch_videos.fetch_new(conn)
    print(f"      dodano: {len(new)}")

    print("[3/7] transkrypcje...")
    stats = transcripts.fetch_pending(conn)
    print(f"      {stats}")

    print("[4/7] analiza wyciągów (Haiku)...")
    astats = analyze.run(conn)
    print(f"      {astats}")

    print("[5/7] tematy dnia...")
    topic_ids = topics.group(conn, today)
    print(f"      tematów: {len(topic_ids)}")

    print("[6/7] twarde dane + wykresy...")
    market_data.enrich_topics(conn, topic_ids, today)

    print("[7/7] drafty na X (Sonnet) + strona...")
    n = drafts.generate(conn, topic_ids, today)
    out = build_site.build(conn, today)
    print(f"      draftów: {n}, strona: {out}")

    # TODO Etap 6: notify.send(today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
