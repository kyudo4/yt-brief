"""Telegram: jedna wiadomość dziennie — spis zajawek + link do briefu."""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

from . import db


def _site_url() -> str:
    """SITE_URL z env, a w Actions domyślnie https://<owner>.github.io/<repo>."""
    url = os.environ.get("SITE_URL")
    if url:
        return url.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY")  # owner/repo w Actions
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}"
    return ""


def send(conn, date: str) -> bool:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("  ! brak TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — pomijam powiadomienie")
        return False

    topics = db.topics_for_date(conn, date)
    if not topics:
        text = f"📋 Brief {date} — dziś bez tematów (kanały milczały)."
    else:
        drafted = sum(1 for t in topics if t["card"].get("draft_x"))
        lines = [f"📋 Brief {date} — {len(topics)} tematów, {drafted} draftów na X:", ""]
        lines += [f"{i}. {t['teaser']}" for i, t in enumerate(topics, 1)]
        site = _site_url()
        if site:
            lines += ["", site]
        text = "\n".join(lines)

    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=20,
    )
    ok = r.ok and r.json().get("ok")
    print(f"  telegram: {'wysłano' if ok else f'BŁĄD {r.status_code}: {r.text[:200]}'}")
    return bool(ok)
