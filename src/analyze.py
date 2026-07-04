"""Haiku: transkrypcja -> strukturalny wyciąg JSON.

Twarda zasada: liczby z transkrypcji NIGDY nie są faktami — trafiają wyłącznie
do `poziomy_wg_kanalu` jako opinia danego kanału. Twarde dane rynkowe dokłada
później market_data.py z API.
"""

from __future__ import annotations

from . import db, llm

MAX_TRANSCRIPT_CHARS = 80_000  # ~30k tokenów; Haiku ma 200k kontekstu

EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["streszczenie", "tezy", "ciekawostki", "sentyment", "tickery", "slowa_kluczowe",
                 "cytaty", "poziomy_wg_kanalu"],
    "properties": {
        "streszczenie": {"type": "string", "description": "2-3 zdania po polsku"},
        "tezy": {"type": "array", "items": {"type": "string"},
                 "description": "główne tezy/argumenty autora, max 6"},
        "ciekawostki": {
            "type": "array", "items": {"type": "string"},
            "description": "Nieoczywiste, konkretne smaczki z filmu: zaskakujące fakty, unikalne dane "
                           "lub obserwacje, kontrariańskie/mocne opinie autora, mechanizmy 'jak to naprawdę "
                           "działa', rzeczy których nie usłyszysz w mainstreamie. Każda to samodzielny, "
                           "konkretny kąt — NIE ogólnik typu 'rynek jest niepewny'. Max 5. Pusta lista, "
                           "jeśli film to sama ogólna gadka bez smaczków.",
        },
        "sentyment": {"type": "integer", "enum": [-2, -1, 0, 1, 2],
                      "description": "-2 skrajnie niedźwiedzi ... +2 skrajnie byczy"},
        "tickery": {"type": "array", "items": {"type": "string"},
                    "description": "tickery/aktywa omawiane w filmie, np. BTC, ETH, MU, DXY"},
        "slowa_kluczowe": {"type": "array", "items": {"type": "string"},
                           "description": "5-10 słów kluczowych tematycznych, lowercase, po polsku"},
        "cytaty": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["timestamp", "tekst"],
                "properties": {
                    "timestamp": {"type": "string", "description": "znacznik [mm:ss] lub [h:mm:ss] z transkrypcji"},
                    "tekst": {"type": "string", "description": "krótki, charakterystyczny cytat"},
                },
            },
            "description": "1-3 najmocniejsze cytaty z timestampem",
        },
        "poziomy_wg_kanalu": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ticker", "wartosc", "kontekst"],
                "properties": {
                    "ticker": {"type": "string"},
                    "wartosc": {"type": "string", "description": "liczba/poziom dokładnie jak wypowiedziany"},
                    "kontekst": {"type": "string", "description": "czego dotyczy, np. 'cel na koniec roku'"},
                },
            },
            "description": "WSZYSTKIE liczby/poziomy cenowe wymienione przez autora — to opinie, nie fakty",
        },
    },
}

SYSTEM = """Jesteś analitykiem treści finansowych. Dostajesz transkrypcję filmu z YouTube \
(krypto/makro/akcje, zwykle po polsku) z markerami czasu [mm:ss] na początku bloków.

Twoje zadanie: wyciągnij strukturalny wyciąg zgodny ze schematem. Zasady:
- Pisz po polsku, zwięźle, bez lania wody.
- Tezy to opinie i argumenty AUTORA, nie twoje.
- ciekawostki to serce wyciągu — wyławiaj nieoczywiste, konkretne rzeczy, które robią z filmu
  wartościowy materiał na wpis: unikalne dane, zaskakujące mechanizmy, mocne/kontrariańskie opinie,
  smaczki. Pomijaj oczywistości i ogólniki. Lepiej 2 mocne ciekawostki niż 5 pustych.
- KLUCZOWE: każdą liczbę, poziom cenowy czy prognozę wypowiedzianą w filmie umieść \
w poziomy_wg_kanalu. Liczby z transkrypcji to zawsze opinia kanału, nigdy fakt rynkowy.
- Timestampy cytatów bierz z najbliższego markera [mm:ss] przed cytatem.
- Tickery normalizuj do wielkich liter (BTC, ETH, MU, DXY, SPX, GOLD).
- Auto-napisy bywają zniekształcone, zwłaszcza nazwy własne i tickery (np. "Bajnas"=Binance,
  "Ono"=Ondo, "Círcle"=Circle, "Hyperliquid" przekręcane). Koryguj nazwy projektów, giełd i
  tickerów po sensie i kontekście. Nie zostawiaj literówek w nazwach własnych ani obcojęzycznych
  wtrętów (pisz po polsku)."""


def run(conn) -> dict:
    """Analizuje wszystkie filmy o statusie 'transcribed'."""
    stats = {"ok": 0, "error": 0}
    for v in db.videos_by_status(conn, "transcribed"):
        vid = v["video_id"]
        t = db.get_transcript(conn, vid)
        user = (
            f"Kanał: {v['channel_name']}\nTytuł: {v['title']}\n"
            f"Transkrypcja ({t['lang']}, {'auto' if t['generated'] else 'ręczne'} napisy):\n\n"
            + t["text"][:MAX_TRANSCRIPT_CHARS]
        )
        try:
            data = llm.call_json(
                model=llm.MODEL_CHEAP, system=SYSTEM, user=user,
                schema=EXTRACT_SCHEMA, max_tokens=3000,
            )
        except Exception as e:
            print(f"  ! błąd analizy {vid}: {type(e).__name__}: {e}")
            db.set_video_status(conn, vid, "error", f"analyze: {e}")
            stats["error"] += 1
            continue
        db.save_extract(conn, vid, data, model=llm.MODEL_CHEAP)
        print(f"  + wyciąg [{v['channel_name']}] sentyment={data['sentyment']:+d} "
              f"tickery={','.join(data['tickery'][:5])} — {v['title'][:50]}")
        stats["ok"] += 1
    return stats


if __name__ == "__main__":
    print(run(db.connect()))
