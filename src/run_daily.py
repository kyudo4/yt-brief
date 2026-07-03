"""Pełny dzienny obieg: python -m src.run_daily

Etapy dochodzą w kolejnych krokach budowy — każdy podpinany tutaj.
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import db, fetch_videos, transcripts


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

    # TODO Etap 3: analyze.run(conn) + topics.group(conn, today)
    # TODO Etap 4: market_data + charts przy budowie kart
    # TODO Etap 5: build_site.build(conn, today) + drafts
    # TODO Etap 6: notify.send(today)
    print("Kolejne etapy jeszcze nie podpięte (Etap 1: szkielet).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
