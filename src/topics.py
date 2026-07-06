"""Haiku: wyciągi dnia -> TEMATY DNIA (cross-kanałowo) + pamięć tematów.

Jeden zbiorczy call grupujący, plus (tylko dla tematów-kontynuacji) krótki call
"co się zmieniło od wczoraj". Karta tematu powstaje tutaj w wersji tekstowej;
twarde dane i wykresy dokłada Etap 4, drafty Etap 5.
"""

from __future__ import annotations

import json

from . import db, llm

TOPICS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tematy"],
    "properties": {
        "tematy": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tytul", "zajawka", "o_co_chodzi", "tlo", "keywords", "tickery",
                             "kto_co_mowi", "konsensus_rozjazdy", "wniosek", "nadaje_sie_na_x",
                             "potrzebne_dane"],
                "properties": {
                    "tytul": {"type": "string", "description": "krótki nagłówek tematu"},
                    "zajawka": {"type": "string", "description": "JEDNO zdanie do Telegrama, zrozumiałe bez kontekstu"},
                    "o_co_chodzi": {"type": "string", "description": "jedno zdanie rozwinięcia nagłówka"},
                    "tlo": {"type": "string", "description": "3-5 zdań tła na chłopski rozum: co to za kwestia, skąd się wzięła, czemu teraz głośno; zero żargonu bez wyjaśnienia"},
                    "keywords": {"type": "array", "items": {"type": "string"},
                                 "description": "słowa kluczowe do dopasowania historycznego, lowercase"},
                    "tickery": {"type": "array", "items": {"type": "string"}},
                    "kto_co_mowi": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["video_id", "stanowisko", "timestamp"],
                            "properties": {
                                "video_id": {"type": "string", "description": "dokładne video_id z wyciągu"},
                                "stanowisko": {"type": "string", "description": "1-2 zdania: co ten kanał mówi w tym temacie"},
                                "timestamp": {"type": "string", "description": "timestamp mm:ss najlepszego fragmentu (z cytatów), albo 00:00"},
                            },
                        },
                    },
                    "konsensus_rozjazdy": {"type": "string",
                                           "description": "wprost: w czym kanały się zgadzają, w czym rozjeżdżają; przy jednym kanale napisz że brak porównania"},
                    "wniosek": {"type": "string", "description": "1-2 zdania: co z tego wynika dla rynku/portfela"},
                    "nadaje_sie_na_x": {"type": "boolean", "description": "czy temat nadaje się na draft posta na X"},
                    "potrzebne_dane": {"type": "array", "items": {"type": "string"},
                                       "description": "z listy: btc, eth, dominacja_btc, fear_greed, dxy, mu, spx, gold, oil. Dodaj ticker/dane TYLKO gdy temat jest WPROST o cenie, ruchu lub poziomie tego aktywa. Temat o modelu biznesowym, technologii, migracji, przejęciu, regulacji czy narracji — NAWET jeśli wspomina BTC/ETH — daje PUSTĄ listę (cena BTC nic nie wnosi do wpisu o tym, że górnicy przechodzą na AI). W razie wątpliwości: pusta lista."},
                },
            },
        },
    },
}

SYSTEM_GROUP = """Jesteś redaktorem dziennego briefu rynkowego (krypto + makro + akcje) po polsku. \
Dostajesz wyciągi z dzisiejszych filmów YouTube (JSON): tezy, sentyment, tickery, cytaty, \
poziomy wg kanału, wagę kanału (weight).

Pogrupuj je w TEMATY DNIA — cross-kanałowo: jeśli dwa kanały mówią o tym samym, to JEDEN temat. \
Zasady:
- Wybieraj tematy będące CIEKAWOSTKĄ lub ANALIZĄ z realną wartością: nieoczywisty mechanizm, \
zaskakujący ruch, ukryty powód, konsekwencja której inni nie widzą, sprzeczność w narracji. \
Odrzucaj generyczne newsy bez kąta ("cena spadła", "ktoś coś ogłosił") — chyba że jest do nich \
nieoczywisty komentarz. Priorytet: krypto, makro (stopy, ropa, dolar, inflacja), akcje.
- 2-6 tematów; lepiej 3 mocne i nieoczywiste niż 6 płytkich. Nie twórz tematu z każdej pierdoły, \
ale nie sklejaj na siłę różnych spraw.
- Kanały z wyższym weight ważniejsze przy wyborze tematów.
- Tło pisz tak, żeby wprowadzić czytelnika OD ZERA, prostym językiem.
- W kto_co_mowi używaj DOKŁADNYCH video_id z wyciągów i timestampów z cytatów.
- NIE podawaj żadnych liczb rynkowych jako faktów. Liczby z wyciągów przywołuj wyłącznie \
z dopiskiem "wg [nazwa kanału]" — to opinie. Twarde dane dołoży system z API.
- nadaje_sie_na_x = true tylko gdy temat ma potencjał na ciekawą opinię, nie suchy news."""

SYSTEM_UPDATE = """Piszesz sekcję "Aktualizacja — co się zmieniło od wczoraj" w dziennym briefie \
rynkowym po polsku. Dostajesz wczorajszą kartę tematu i dzisiejszy stan tematu. Napisz 2-4 zdania: \
co nowego, co się zmieniło w narracji kanałów, co pozostaje aktualne. Prosty język, bez powtarzania \
całego tła. Nie podawaj liczb rynkowych jako faktów (liczby tylko z dopiskiem "wg [kanał]")."""


def group(conn, date: str) -> list[int]:
    """Grupuje wyciągi dnia w tematy, zapisuje karty. Zwraca id tematów."""
    extracts = db.extracts_for_date(conn, date)
    if not extracts:
        print("  brak wyciągów do pogrupowania")
        return []

    removed = db.delete_topics_for_date(conn, date)  # idempotentność: nadpisz, nie dubluj
    if removed:
        print(f"  (usunięto {removed} tematów z wcześniejszego runu tego dnia)")

    channels = _channel_weights()
    payload = [
        {
            "video_id": e["video_id"],
            "kanal": e["channel_name"],
            "weight": channels.get(e["channel_name"], 1),
            "tytul": e["title"],
            "wyciag": e["data"],
        }
        for e in extracts
    ]
    result = llm.call_json(
        model=llm.MODEL_CHEAP, system=SYSTEM_GROUP,
        user=json.dumps(payload, ensure_ascii=False),
        schema=TOPICS_SCHEMA, max_tokens=8000,
    )

    by_vid = {e["video_id"]: e for e in extracts}
    topic_ids = []
    for t in result["tematy"]:
        related = db.find_related_topic(conn, t["keywords"], t["tickery"], before_date=date)
        card = _build_card(t, by_vid, related, date)
        tid = db.save_topic(
            conn, date=date, title=t["tytul"], teaser=t["zajawka"],
            keywords=t["keywords"], tickers=t["tickery"], card=card,
            parent_id=related["id"] if related else None,
            video_ids=[k["video_id"] for k in t["kto_co_mowi"] if k["video_id"] in by_vid],
        )
        topic_ids.append(tid)
        mark = f" [aktualizacja tematu #{related['id']}]" if related else ""
        print(f"  + temat #{tid}: {t['tytul']}{mark}")
    return topic_ids


def _build_card(t: dict, by_vid: dict, related: dict | None, date: str) -> dict:
    kto = []
    for k in t["kto_co_mowi"]:
        v = by_vid.get(k["video_id"])
        if not v:
            continue
        kto.append({
            "kanal": v["channel_name"],
            "tytul_filmu": v["title"],
            "url": f"{v['url']}&t={_to_seconds(k['timestamp'])}s",
            "stanowisko": k["stanowisko"],
        })
    card = {
        "naglowek": t["tytul"],
        "o_co_chodzi": t["o_co_chodzi"],
        "kto_co_mowi": kto,
        "konsensus_rozjazdy": t["konsensus_rozjazdy"],
        "wniosek": t["wniosek"],
        "nadaje_sie_na_x": t["nadaje_sie_na_x"],
        "potrzebne_dane": t["potrzebne_dane"],
        "poziomy_wg_kanalu": _collect_levels(t, by_vid),
        "ciekawostki": _collect_facts(t, by_vid),
    }
    if related:
        card["aktualizacja"] = _update_intro(related, t)
        card["poprzednio"] = {"data": related["date"], "tytul": related["title"]}
    else:
        card["tlo"] = t["tlo"]
    return card


def _collect_levels(t: dict, by_vid: dict) -> list[dict]:
    """Poziomy 'wg kanału' — TYLKO dla aktywów, o które temat realnie prosi
    (potrzebne_dane). Dzięki temu wpis o modelu biznesowym nie ciągnie za sobą
    prognoz ceny BTC tylko dlatego, że BTC pada w temacie z boku."""
    needed = {d.lower() for d in t.get("potrzebne_dane", [])}
    if not needed:
        return []
    levels = []
    for k in t["kto_co_mowi"]:
        v = by_vid.get(k["video_id"])
        if not v:
            continue
        for lvl in v["data"].get("poziomy_wg_kanalu", []):
            if lvl["ticker"].lower() in needed:
                levels.append({**lvl, "kanal": v["channel_name"]})
    return levels


def _collect_facts(t: dict, by_vid: dict) -> list[dict]:
    """Nieoczywiste ciekawostki/fakty z filmów przypiętych do tematu — materiał na draft."""
    facts = []
    for k in t["kto_co_mowi"]:
        v = by_vid.get(k["video_id"])
        if not v:
            continue
        for fact in v["data"].get("ciekawostki", []):
            facts.append({"kanal": v["channel_name"], "fakt": fact})
    return facts


def _update_intro(related: dict, t: dict) -> str:
    old = {k: related["card"].get(k) for k in ("naglowek", "o_co_chodzi", "tlo", "konsensus_rozjazdy", "wniosek")}
    user = json.dumps({"wczoraj": old, "dzisiaj": {"tytul": t["tytul"], "o_co_chodzi": t["o_co_chodzi"],
                       "kto_co_mowi": [k["stanowisko"] for k in t["kto_co_mowi"]],
                       "konsensus_rozjazdy": t["konsensus_rozjazdy"]}}, ensure_ascii=False)
    try:
        return llm.call_text(model=llm.MODEL_CHEAP, system=SYSTEM_UPDATE, user=user, max_tokens=500)
    except Exception as e:
        print(f"  ! nie udało się wygenerować aktualizacji: {e}")
        return t["tlo"]


def _to_seconds(ts: str) -> int:
    """'mm:ss' / 'h:mm:ss' / '[mm:ss]' -> sekundy; śmieci -> 0."""
    try:
        parts = [int(p) for p in ts.strip("[] ").split(":")]
    except ValueError:
        return 0
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0


def _channel_weights() -> dict:
    from .fetch_videos import load_channels
    return {c["name"]: c.get("weight", 1) for c in load_channels()}


if __name__ == "__main__":
    from datetime import datetime
    from zoneinfo import ZoneInfo
    conn = db.connect()
    group(conn, datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%Y-%m-%d"))
