"""Pełny dzienny obieg: python -m src.run_daily

Etapy dochodzą w kolejnych krokach budowy — każdy podpinany tutaj.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import analyze, build_site, db, drafts, fetch_videos, llm, market_data, notify, topics, transcripts, verify


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
    # Okno grupowania szersze niż domyślne 24h: kanały publikują nierówno, a dedup
    # (extracts_for_date pomija filmy z wcześniejszych briefów) chroni przed powtórkami.
    lookback = int(os.environ.get("YT_BRIEF_LOOKBACK_DAYS", "3"))
    topic_ids = topics.group(conn, today, lookback_days=lookback)
    print(f"      tematów: {len(topic_ids)} (okno {lookback} dni)")

    print("[6/8] twarde dane + wykresy...")
    market_data.enrich_topics(conn, topic_ids, today)

    print("[7/8] drafty na X (Sonnet) + fact-check (web search) + strona...")
    n = drafts.generate(conn, topic_ids, today)
    vstats = verify.run(conn, topic_ids, today)
    print(f"      fact-check: {vstats}")
    out = build_site.build(conn, today)
    print(f"      draftów: {n}, strona: {out}")

    print("[8/8] telegram...")
    notify.send(conn, today)

    print(f"koszt API (orientacyjnie): {llm.cost_summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
