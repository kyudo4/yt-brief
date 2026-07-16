"""Jinja2 -> docs/ (GitHub Pages z /docs).

- docs/index.html          — brief z dzisiaj
- docs/briefs/YYYY-MM-DD.html — archiwum (ten sam szablon, prefix ../)
- docs/briefs/index.html   — lista dat
- docs/style.css           — kopiowany z templates/
"""

from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db

ROOT = Path(__file__).parent.parent
TEMPLATES = ROOT / "templates"
DOCS = ROOT / "docs"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def _write_html(path: Path, html: str) -> None:
    """Nie zostawiaj białych znaków generowanych przez wcięcia Jinja."""
    path.write_text("\n".join(line.rstrip() for line in html.splitlines()) + "\n", encoding="utf-8")


def build(conn, date: str, docs: Path | None = None) -> Path:
    docs = docs or DOCS
    (docs / "briefs").mkdir(parents=True, exist_ok=True)
    env = _env()
    topics = db.topics_for_date(conn, date)

    brief_tpl = env.get_template("brief.html")
    # strona główna (prefix "") i kopia archiwalna (prefix "../")
    _write_html(docs / "index.html", brief_tpl.render(date=date, topics=topics, prefix=""))
    _write_html(docs / "briefs" / f"{date}.html", brief_tpl.render(date=date, topics=topics, prefix="../"))

    # indeks archiwum z bazy (wszystkie daty z tematami)
    rows = conn.execute(
        "SELECT date, COUNT(*) n, GROUP_CONCAT(title, ' · ') titles"
        " FROM topics GROUP BY date ORDER BY date DESC"
    ).fetchall()
    dates = [{"date": r["date"], "count": r["n"], "titles": (r["titles"] or "")[:160]} for r in rows]
    _write_html(docs / "briefs" / "index.html", env.get_template("archive.html").render(dates=dates))

    shutil.copy(TEMPLATES / "style.css", docs / "style.css")
    return docs / "index.html"


if __name__ == "__main__":
    from datetime import datetime
    from zoneinfo import ZoneInfo
    conn = db.connect()
    out = build(conn, datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%Y-%m-%d"))
    print(f"wygenerowano: {out}")
