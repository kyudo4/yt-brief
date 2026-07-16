"""Bramka redakcyjna dla draftów.

To nie jest automatyczny fact-check internetu. Jej zadaniem jest zatrzymać
materiał, gdy nie ma źródła, gdy liczba wygląda na nieopisaną opinię z filmu
albo gdy temat jest zbyt słabo potwierdzony. Wynik jest zawsze widoczny na
stronie, więc autor decyduje świadomie przed publikacją.
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"(?<![\w$])\d+(?:[.,]\d+)?(?:%|k|m|mld|k)?", re.IGNORECASE)


def review(card: dict) -> dict:
    """Zwraca prosty, transparentny status publikacyjny dla jednej karty."""
    draft = card.get("draft_x") or {}
    text = (draft.get("tekst") or "").strip()
    sources = card.get("kto_co_mowi") or []
    notes: list[str] = []

    if not text:
        return {"status": "brak_draftu", "etykieta": "bez draftu", "uwagi": []}
    if not sources:
        notes.append("Brak podpiętego filmu źródłowego — nie publikuj bez uzupełnienia.")
    if len(sources) == 1:
        notes.append("Temat opiera się na jednym materiale; sprawdź kluczową tezę w źródle przed publikacją.")

    numbers = _NUMBER.findall(text)
    hard_data = card.get("twarde_dane") or []
    if numbers and "wg " not in text.lower() and not hard_data:
        notes.append("Draft zawiera liczby bez oznaczenia „wg kanał” i bez danych z API — sprawdź ich źródło.")

    if not sources:
        status, label = "blokada", "nie publikuj"
    elif notes:
        status, label = "sprawdz", "sprawdź przed publikacją"
    else:
        status, label = "gotowy", "gotowe do Twojej akceptacji"
    return {"status": status, "etykieta": label, "uwagi": notes}


def run(conn, topic_ids: list[int], date: str) -> dict:
    """Zapisuje raport redakcyjny w kartach tematów danego dnia."""
    ids = set(topic_ids)
    stats = {"gotowe": 0, "do_sprawdzenia": 0, "blokady": 0}
    for topic in conn.execute("SELECT id, card FROM topics WHERE date = ? ORDER BY id", (date,)).fetchall():
        if topic["id"] not in ids:
            continue
        import json
        card = json.loads(topic["card"])
        report = review(card)
        card["redakcja"] = report
        conn.execute("UPDATE topics SET card = ? WHERE id = ?", (json.dumps(card, ensure_ascii=False), topic["id"]))
        if report["status"] == "gotowy":
            stats["gotowe"] += 1
        elif report["status"] == "blokada":
            stats["blokady"] += 1
        else:
            stats["do_sprawdzenia"] += 1
    conn.commit()
    return stats
