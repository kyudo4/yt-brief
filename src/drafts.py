"""Sonnet: karta tematu -> draft wpisu na X. GŁÓWNY PRODUKT aplikacji.

Draft dostaje automatycznie dobrany wykres (załącznik do wpisu). Tło i wyjaśnienia
zostają na stronie jako ściąga dla autora — nigdy w treści draftu.

Zasada liczb: w drafcie wolno użyć wyłącznie liczb z twarde_dane (API) albo
z dopiskiem "wg [kanał]". Pilnowane promptem + danymi wejściowymi.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import db, llm

STYLE_FILE = Path(__file__).parent.parent / "style_examples.json"

RULES = """Piszesz drafty wpisów na X (Twitter) po polsku dla autora konta o krypto/makro/rynkach.

STYL:
- Ton luźny, bezpośredni, własne zdanie wprost. Zero tonu eksperta-wykładowcy, zero korpomowy.
- Krótkie, cięte zdania. Często małe litery. Puenta zamiast wywodu.
- Naturalny polski slang krypto (FUD, low capy, degen) + chłopski rozum.
- Nitka (3-5 tweetów) TYLKO przy realnej analizie; zwykle jeden mocny tweet.
- Zawsze charakter opinii. Gdy draft brzmi jak call inwestycyjny, dodaj na końcu
  "nie jest to porada inwestycyjna" (małymi literami, naturalnie).

ZAKAZANE:
- emoji-spam, "🚨 BREAKING", sztywne wyliczanki 1/2/3 bez potrzeby,
- kalki z angielskiego, ton doradcy, hasztagowanie na siłę.

LICZBY — ŻELAZNA ZASADA:
- Możesz użyć tylko liczb z sekcji twarde_dane (pochodzą z API) oraz poziomów
  z sekcji poziomy_wg_kanalu — te drugie ZAWSZE z dopiskiem "wg [nazwa kanału]".
- Żadnych liczb z głowy.

FORMAT ODPOWIEDZI:
- Sam tekst wpisu, bez komentarzy i cudzysłowów.
- Nitka: kolejne tweety oddziel linią zawierającą wyłącznie "---".
- Jeśli temat jest zbyt suchy na sensowny wpis, odpowiedz dokładnie: PAS"""


def _style_examples() -> str:
    data = json.loads(STYLE_FILE.read_text())
    parts = []
    for ex in data.get("examples", []):
        if ex.get("type") == "thread":
            text = "\n---\n".join(ex.get("tweets", []))
        else:
            text = ex.get("text", "")
        if text and "PLACEHOLDER" not in text:
            parts.append(text)
    if not parts:
        return ""
    return "\n\nPRZYKŁADY STYLU AUTORA (naśladuj ton, nie treść):\n\n" + "\n\n===\n\n".join(parts)


def _system() -> str:
    return RULES + _style_examples()


def _pick_chart(card: dict) -> dict | None:
    """Wykres-załącznik do wpisu: własny PNG > obrazek > pierwszy link."""
    charts = card.get("wykresy", [])
    for typ in ("png", "img", "link"):
        for ch in charts:
            if ch["typ"] == typ:
                return ch
    return None


def generate(conn, topic_ids: list[int], date: str) -> int:
    """Generuje draft dla każdego tematu dnia. Zwraca liczbę draftów."""
    system = _system()
    made = 0
    for t in db.topics_for_date(conn, date):
        if t["id"] not in set(topic_ids):
            continue
        card = t["card"]
        user = json.dumps({
            "temat": card["naglowek"],
            "o_co_chodzi": card["o_co_chodzi"],
            "stanowiska_kanalow": [
                {"kanal": k["kanal"], "stanowisko": k["stanowisko"]}
                for k in card.get("kto_co_mowi", [])
            ],
            "konsensus_rozjazdy": card.get("konsensus_rozjazdy"),
            "poziomy_wg_kanalu": card.get("poziomy_wg_kanalu", []),
            "twarde_dane": [
                {k: e[k] for k in ("label", "wartosc", "zmiana_24h", "zmiana_5d", "zrodlo") if k in e}
                for e in card.get("twarde_dane", [])
            ],
            "wniosek": card.get("wniosek"),
        }, ensure_ascii=False)

        try:
            text = llm.call_text(model=llm.MODEL_DRAFTS, system=system, user=user, max_tokens=1200).strip()
        except Exception as e:
            print(f"  ! draft dla tematu #{t['id']}: {type(e).__name__}: {e}")
            continue

        if text == "PAS":
            print(f"  - temat #{t['id']} spasowany ({card['naglowek'][:40]})")
            continue
        card["draft_x"] = {"tekst": text, "wykres": _pick_chart(card)}
        db.update_topic_card(conn, t["id"], card)
        kind = "nitka" if "\n---\n" in text else "tweet"
        print(f"  + draft ({kind}) dla tematu #{t['id']}: {card['naglowek'][:50]}")
        made += 1
    return made
