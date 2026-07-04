"""Sonnet: karta tematu -> draft wpisu na X. GŁÓWNY PRODUKT aplikacji.

Załącznik (wykres do wrzucenia do posta) i liczby trafiają do draftu TYLKO gdy
realnie pasują do jego treści — decyduje o tym model piszący draft, bo tylko on
wie, co napisał. Wpis o cenie/ruchu aktywa dostaje wykres tego aktywa; wpis o
regulacjach, przejęciu czy sentymencie — żaden. Tło i pełne dane zostają w
ściądze na stronie, nigdy w treści draftu.

Zasada liczb: w drafcie wolno użyć wyłącznie liczb z twarde_dane (API) albo
z dopiskiem "wg [kanał]". Pilnowane promptem + danymi wejściowymi.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import db, llm

STYLE_FILE = Path(__file__).parent.parent / "style_examples.json"

DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tekst", "wykres_id"],
    "properties": {
        "tekst": {
            "type": "string",
            "description": "Treść wpisu na X. Nitka: tweety oddzielone linią '---'. "
                           "Pusty string, jeśli temat jest zbyt suchy na sensowny wpis (pas).",
        },
        "wykres_id": {
            "type": "integer",
            "description": "id załącznika z listy dostepne_wykresy, który BEZPOŚREDNIO ilustruje "
                           "treść wpisu i warto go wrzucić do posta. -1, jeśli żaden nie pasuje "
                           "albo wpis nie potrzebuje wykresu.",
        },
    },
}

RULES = """Piszesz drafty wpisów na X (Twitter) po polsku dla autora konta o krypto/makro/rynkach.

CEL — realna wartość, nie banał (NAJWAŻNIEJSZE):
- Sekcja "ciekawostki" to twoja amunicja: nieoczywiste fakty, unikalne dane i mocne opinie
  wyłuskane z filmów. Oprzyj wpis na najmocniejszej z nich — to ona ma dać czytelnikowi
  "nie wiedziałem tego". Nie rozwadniaj jej ogólnikami.
- Każdy draft ma dać czytelnikowi coś, czego sam nie zauważył: nieoczywisty kąt,
  mechanizm "jak to naprawdę działa", policzoną konsekwencję, ukryty powód, sprzeczność.
- NIE streszczaj newsa ("X ogłosił Y"). Pokaż CO Z TEGO WYNIKA i czemu to ważne — jak
  w przykładach autora: BMNP to maszynka na ETH (ten sam mechanizm co Strategy na BTC);
  wycena STG z przejęcia vs pump na FOMO; -85% vs -90% to realnie 36% gorsze wejście.
- Postaw własne zdanie i tezę. Sceptycyzm, konkret, wniosek. Zero suchego relacjonowania.
- Jeśli temat to oczywistość bez kąta ("BTC spadł, na rynku strach") — zwróć pusty tekst
  (pas). Lepiej brak wpisu niż banał.

TYPY WPISU (dobierz do tematu):
- Reakcja z kątem: wydarzenie + nieoczywisty komentarz, teza, sceptycyzm (jak większość przykładów).
- Deep dive projektu: gdy temat to konkretny protokół/projekt z nowością (np. Ondo, Hyperliquid) —
  wyjaśnij PROSTO jak to działa i co KONKRETNIE nowego wprowadzają, a potem CO TO ZNACZY dla rynku
  i dla samego projektu w dłuższym dystansie (adopcja, realny popyt, konkurencja, ryzyko). To zwykle
  nitka. Bez marketingu projektu — twoja własna, wyważona ocena, nie ulotka.

STYL:
- Ton luźny, bezpośredni, własne zdanie wprost. Zero tonu eksperta-wykładowcy, zero korpomowy.
- Krótkie, cięte zdania. Często małe litery. Puenta zamiast wywodu.
- Naturalny polski slang krypto (FUD, low capy, degen) + chłopski rozum.
- Nitka (3-5 tweetów) TYLKO przy realnej analizie; zwykle jeden mocny tweet.
- Zawsze charakter opinii. Gdy draft brzmi jak call inwestycyjny, dodaj na końcu
  "nie jest to porada inwestycyjna" (małymi literami, naturalnie).

EMOJI I FORMA (jak w przykładach autora):
- Emoji oszczędnie i akcentująco: 🚨/🟢 na start ważnej wiadomości, 🔹 lub • do
  punktów listy konkretów, $TICKER przy tokenach, sporadyczny 🤔/👀/xD dla tonu.
- Wyliczanki z bulletami (•/🔹) OK, gdy to realna lista faktów/liczb; nie sztuczne 1/2/3.

POPRAWNOŚĆ:
- Popraw ewidentnie przekręcone nazwy własne i tickery z materiału (Ono→Ondo, Círcle→Circle itp.).
  Nie przepisuj literówek z auto-napisów do wpisu.

ZAKAZANE:
- emoji-spam (emoji w co drugim słowie), korpo-nagłówki typu "BREAKING",
- kalki z angielskiego, ton doradcy, hasztagowanie na siłę.

LICZBY — źródło ZAWSZE jawne (żelazna zasada):
- Tylko liczby z sekcji twarde_dane pochodzą z API (CoinGecko/Yahoo) — te i tylko te
  możesz podać jako fakt bez zastrzeżeń.
- KAŻDA inna liczba, dana czy konkretne twierdzenie (z ciekawostek, stanowisk_kanalow,
  poziomy_wg_kanalu) pochodzi z wypowiedzi kanału — podawaj ją ZAWSZE z atrybucją
  "wg [nazwa kanału]" (np. "wg 0xResearch", "wg Bankless"). Nigdy jako gołego faktu:
  to cudze twierdzenie z filmu, nie zweryfikowana prawda. Dotyczy też procentów, kwot,
  dat i statystyk ("akcje spadły -50% wg Bankless", nie "akcje spadły -50%").
- Nie wciskaj liczb, jeśli wpis ich nie potrzebuje. Żadnych liczb z głowy.

ZAŁĄCZNIK (wykres_id):
- Wskaż wykres z dostepne_wykresy TYLKO jeśli bezpośrednio ilustruje treść wpisu —
  np. wpis o ruchu/poziomie ropy dostaje wykres ropy, wpis o cenie BTC wykres BTC.
- Wpis o regulacjach, licencji, przejęciu, wywiadzie, sentymencie, narracji →
  wykres_id: -1. Nie podpinaj wykresu tylko dlatego, że jest dostępny.
- Lepiej brak wykresu niż niepasujący. Nigdy nie dobieraj wykresu innego aktywa
  niż to, o którym jest wpis."""


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


def _attachable(card: dict) -> list[dict]:
    """Wykresy nadające się na załącznik do wpisu — tylko obrazki (png/img),
    które da się realnie wrzucić. Linki (TradingView itp.) zostają w ściądze."""
    return [w for w in card.get("wykresy", []) if w.get("typ") in ("png", "img")]


def generate(conn, topic_ids: list[int], date: str) -> int:
    """Generuje draft dla każdego tematu dnia. Zwraca liczbę draftów."""
    system = _system()
    made = 0
    for t in db.topics_for_date(conn, date):
        if t["id"] not in set(topic_ids):
            continue
        card = t["card"]
        kandydaci = _attachable(card)
        user = json.dumps({
            "temat": card["naglowek"],
            "o_co_chodzi": card["o_co_chodzi"],
            "stanowiska_kanalow": [
                {"kanal": k["kanal"], "stanowisko": k["stanowisko"]}
                for k in card.get("kto_co_mowi", [])
            ],
            "konsensus_rozjazdy": card.get("konsensus_rozjazdy"),
            "ciekawostki": card.get("ciekawostki", []),
            "poziomy_wg_kanalu": card.get("poziomy_wg_kanalu", []),
            "twarde_dane": [
                {k: e[k] for k in ("label", "wartosc", "zmiana_24h", "zmiana_5d", "zrodlo") if k in e}
                for e in card.get("twarde_dane", [])
            ],
            "wniosek": card.get("wniosek"),
            "dostepne_wykresy": [
                {"id": i, "opis": w["opis"], "zrodlo": w["zrodlo"]}
                for i, w in enumerate(kandydaci)
            ],
        }, ensure_ascii=False)

        try:
            res = llm.call_json(model=llm.MODEL_DRAFTS, system=system, user=user,
                                schema=DRAFT_SCHEMA, max_tokens=1200)
        except Exception as e:
            print(f"  ! draft dla tematu #{t['id']}: {type(e).__name__}: {e}")
            continue

        text = res["tekst"].strip()
        if not text:
            print(f"  - temat #{t['id']} spasowany ({card['naglowek'][:40]})")
            continue

        idx = res["wykres_id"]
        wykres = kandydaci[idx] if isinstance(idx, int) and 0 <= idx < len(kandydaci) else None
        card["draft_x"] = {"tekst": text, "wykres": wykres}
        db.update_topic_card(conn, t["id"], card)
        kind = "nitka" if "\n---\n" in text else "tweet"
        zal = f", + wykres: {wykres['opis']}" if wykres else ", bez wykresu"
        print(f"  + draft ({kind}) dla tematu #{t['id']}: {card['naglowek'][:45]}{zal}")
        made += 1
    return made
