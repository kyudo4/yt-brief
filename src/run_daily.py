"""Pełny dzienny obieg: python -m src.run_daily

Etapy dochodzą w kolejnych krokach budowy — każdy podpinany tutaj.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import analyze, build_site, db, drafts, fetch_videos, llm, market_data, notify, topics, transcripts


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
    # Domyślnie okno 24h (użytkownik chce tylko najświeższe filmy); dedup
    # (extracts_for_date pomija filmy z wcześniejszych briefów) chroni przed powtórkami.
    # Szersze okno tylko ręcznie przez env, gdyby trzeba było nadrobić zaległości.
    lookback = int(os.environ.get("YT_BRIEF_LOOKBACK_DAYS", "1"))
    try:
        topic_ids = topics.group(conn, today, lookback_days=lookback)
    except Exception as e:
        # Najczęściej wyczerpana pula LLM — wyciągi są już zapisane, dokończymy jutro.
        print(f"      ! grupowanie nieudane ({type(e).__name__}) — zostawiam wczorajszy brief")
        topic_ids = []
    print(f"      tematów: {len(topic_ids)} (okno {lookback} dni)")
    if not topic_ids:
        # Zero tematów (np. wyczerpany limit LLM albo cisza na kanałach) — NIE ruszamy
        # strony: lepiej zostawić wczorajszy pełny brief niż opublikować pusty.
        print("      brak nowych tematów — zostawiam wczorajszy brief, kończę bez przebudowy")
        print(f"koszt API (orientacyjnie): {llm.cost_summary()}")
        return 0

    print("[6/8] twarde dane + wykresy...")
    market_data.enrich_topics(conn, topic_ids, today)

    print("[7/8] drafty na X (Sonnet) + strona...")
    n = drafts.generate(conn, topic_ids, today)
    out = build_site.build(conn, today)
    print(f"      draftów: {n}, strona: {out}")

    print("[8/8] telegram...")
    notify.send(conn, today)

    print(f"koszt API (orientacyjnie): {llm.cost_summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
