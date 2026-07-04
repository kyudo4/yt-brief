"""Fact-check draftu przez wyszukiwarkę Claude (web_search).

Po wygenerowaniu draftu sprawdza w sieci jego kluczowe FAKTY i LICZBY — zwłaszcza
te "wg [kanał]", bo pochodzą z filmu i mogą być nieścisłe. Rozbieżność oznacza i
podaje wersję z internetu, żeby autor nie wrzucił cudzej bzdury jako własnego faktu.

Koszt: web_search jest płatny w ramach API Anthropic (dolicza się do rachunku),
dlatego ograniczamy liczbę zapytań na draft i sprawdzamy tylko fakty, nie opinie.
"""

from __future__ import annotations

import json
import re

from . import db, llm

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
MAX_CONTINUE = 3  # obsługa pause_turn przy dłuższej serii wyszukiwań

SYSTEM = """Jesteś skrupulatnym fact-checkerem wpisów o krypto, makro i akcjach.
Dostajesz draft wpisu na X oraz surowe twierdzenia z filmów, na których się opiera.

Sprawdź w internecie (web_search) kluczowe FAKTY, LICZBY, DATY i WYDARZENIA z draftu —
szczególnie te przypisane "wg [kanał]", bo pochodzą z nagrania i bywają przekręcone.
NIE weryfikuj czystych opinii, prognoz ani tez ("moim zdaniem", "może spaść") — tylko
sprawdzalne fakty. Bądź konkretny: szukaj oficjalnych źródeł, danych, wiarygodnych mediów.

Zwróć WYŁĄCZNIE JSON (żadnego tekstu przed ani po), dokładnie w formacie:
{"ustalenia":[{"twierdzenie":"<krótko, co sprawdzasz>","status":"potwierdzone|rozbieznosc|niepewne","wersja_z_sieci":"<co naprawdę mówią źródła; przy potwierdzeniu krótkie potwierdzenie>","zrodlo":"<domena lub nazwa źródła>"}]}

status:
- "potwierdzone" — sieć potwierdza twierdzenie
- "rozbieznosc" — sieć mówi co innego; w wersja_z_sieci podaj POPRAWNĄ wersję
- "niepewne" — brak wiarygodnych źródeł, nie da się potwierdzić

Sprawdź maksymalnie 4-5 najważniejszych twierdzeń. Jeśli nie ma nic sprawdzalnego (sam komentarz),
zwróć {"ustalenia":[]}."""


def _extract_json(text: str) -> dict:
    """Wyłuskuje obiekt JSON z odpowiedzi (model bywa gadatliwy mimo instrukcji)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"ustalenia": []}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"ustalenia": []}


def verify_draft(text: str, ciekawostki: list[dict]) -> list[dict]:
    """Zwraca listę ustaleń fact-checku dla jednego draftu."""
    client = llm.client()
    user = json.dumps({
        "draft": text,
        "twierdzenia_z_filmow": [f"{c.get('kanal','')}: {c.get('fakt','')}" for c in ciekawostki],
    }, ensure_ascii=False)
    messages = [{"role": "user", "content": user}]

    for _ in range(MAX_CONTINUE + 1):
        resp = client.messages.create(
            model=llm.MODEL_DRAFTS, max_tokens=2000,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=[WEB_SEARCH_TOOL],
            messages=messages,
        )
        if resp.stop_reason == "pause_turn":  # serwer przerwał serię wyszukiwań — wznów
            messages.append({"role": "assistant", "content": resp.content})
            continue
        out = "".join(b.text for b in resp.content if b.type == "text")
        return _extract_json(out).get("ustalenia", [])
    return []


def run(conn, topic_ids: list[int], date: str) -> dict:
    """Weryfikuje drafty dnia. Wynik zapisuje do card['draft_x']['weryfikacja']."""
    stats = {"sprawdzone": 0, "rozbieznosci": 0}
    ids = set(topic_ids)
    for t in db.topics_for_date(conn, date):
        if t["id"] not in ids:
            continue
        card = t["card"]
        draft = card.get("draft_x")
        if not draft or not draft.get("tekst"):
            continue
        try:
            ustalenia = verify_draft(draft["tekst"], card.get("ciekawostki", []))
        except Exception as e:
            print(f"  ! weryfikacja tematu #{t['id']}: {type(e).__name__}: {e}")
            continue
        draft["weryfikacja"] = ustalenia
        db.update_topic_card(conn, t["id"], card)
        rozb = sum(1 for u in ustalenia if u.get("status") == "rozbieznosc")
        stats["sprawdzone"] += 1
        stats["rozbieznosci"] += rozb
        flaga = f" ⚠️ {rozb} rozbieżności" if rozb else " ✓"
        print(f"  + fact-check #{t['id']}: {len(ustalenia)} ustaleń{flaga}")
    return stats
