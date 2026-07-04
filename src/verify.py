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

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 4}
MAX_CONTINUE = 3  # obsługa pause_turn przy dłuższej serii wyszukiwań

SYSTEM = """Jesteś fact-checkerem wpisów o krypto, makro i akcjach. Dostajesz draft wpisu na X.

Sprawdź w internecie (web_search) TYLKO te fakty i liczby, które FAKTYCZNIE pojawiają się w treści
tego draftu — nie sprawdzaj niczego spoza niego. Skup się na rzeczach, które mogłyby ośmieszyć autora,
gdyby były błędne: pomylone nazwy/osoby, zła kwota, wymyślona lub przekręcona statystyka, błędna data.
Ignoruj opinie, prognozy i tezy ("moim zdaniem", "może spaść") — tego nie da się zweryfikować.

Wybierz maksymalnie 1-3 NAJWAŻNIEJSZE sprawdzalne twierdzenia. Nie mnóż drobiazgów. Jeśli fakty się
zgadzają albo draft to sam komentarz — zwróć {"ustalenia":[]} (nie ma o czym pisać).

Zwróć WYŁĄCZNIE JSON (żadnego tekstu przed ani po):
{"ustalenia":[{"twierdzenie":"<krótko, co w drafcie>","status":"rozbieznosc|niepewne","wersja_z_sieci":"<co naprawdę mówią źródła>","zrodlo":"<domena>"}]}

Zgłaszaj TYLKO problemy:
- "rozbieznosc" — draft mówi co innego niż rzeczywistość; w wersja_z_sieci podaj POPRAWNĄ wersję
- "niepewne" — twierdzenie brzmi ryzykownie, a brak wiarygodnego źródła, żeby je potwierdzić
Nie zwracaj statusu "potwierdzone" — jeśli coś się zgadza, po prostu tego nie wymieniaj."""


def _extract_json(text: str) -> dict:
    """Wyłuskuje obiekt JSON z odpowiedzi (model bywa gadatliwy mimo instrukcji)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"ustalenia": []}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"ustalenia": []}


def verify_draft(text: str) -> list[dict]:
    """Zwraca listę ustaleń fact-checku dla jednego draftu (tylko jego treść)."""
    client = llm.client()
    messages = [{"role": "user", "content": f"Draft do sprawdzenia:\n\n{text}"}]

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
            ustalenia = verify_draft(draft["tekst"])
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
