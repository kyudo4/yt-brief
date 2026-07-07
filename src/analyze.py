"""Haiku: transkrypcja -> strukturalny wyciąg JSON.

Twarda zasada: liczby z transkrypcji NIGDY nie są faktami — trafiają wyłącznie
do `poziomy_wg_kanalu` jako opinia danego kanału. Twarde dane rynkowe dokłada
później market_data.py z API.
"""

from __future__ import annotations

from . import db, llm

MAX_TRANSCRIPT_CHARS = 80_000  # ~30k tokenów przy ścieżce tekstowej
# Film >2h to ~700k+ tokenów w jednym zapytaniu — pomijamy, żeby nie oberwać
# rate-limitem darmowego tieru Gemini na pojedynczym gigancie.
MAX_VIDEO_S = 7200

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

SYSTEM_VIDEO = """Jesteś analitykiem treści finansowych. OGLĄDASZ film z YouTube \
(krypto/makro/akcje, zwykle po angielsku lub polsku).

Twoje zadanie: wyciągnij strukturalny wyciąg zgodny ze schematem. Zasady:
- Pisz po polsku, zwięźle, bez lania wody.
- Tezy to opinie i argumenty AUTORA filmu, nie twoje.
- ciekawostki to serce wyciągu — nieoczywiste, konkretne rzeczy, które robią z filmu wartościowy
  materiał na wpis: unikalne dane, zaskakujące mechanizmy, mocne/kontrariańskie opinie, smaczki.
  Pomijaj oczywistości i ogólniki. Lepiej 2 mocne ciekawostki niż 5 pustych.
- KLUCZOWE: każdą liczbę, poziom cenowy czy prognozę wypowiedzianą w filmie umieść \
w poziomy_wg_kanalu. Liczby z filmu to zawsze opinia kanału, nigdy fakt rynkowy.
- Cytaty bierz dosłownie z wypowiedzi; timestamp podaj jako [mm:ss] z momentu, gdy padają.
- Tickery normalizuj do wielkich liter (BTC, ETH, MU, DXY, SPX, GOLD). Nazwy własne (projekty,
  giełdy, osoby) pisz poprawnie."""


def _is_rate_limit(e) -> bool:
    s = str(e).lower()
    return any(k in s for k in ("resource_exhausted", "429", "quota", "rate limit", "exhausted"))


def run(conn) -> dict:
    """Robi wyciągi z niezanalizowanych filmów. Jeśli jest transkrypcja — analiza z tekstu
    (tania ścieżka, głównie lokalnie). Jeśli nie ma (blokada IP w chmurze) — Gemini ogląda
    sam FILM z URL. Przy limicie darmowego tieru przerywa i zostawia resztę na kolejny run."""
    stats = {"ok": 0, "video": 0, "error": 0, "skip": 0}
    seen, pending = set(), []
    for status in ("transcribed", "new"):  # 'transcribed' = tekst, 'new' = blokada -> wideo
        for v in db.videos_by_status(conn, status):
            if v["video_id"] not in seen:
                seen.add(v["video_id"])
                pending.append(v)
    pending.sort(key=lambda v: v.get("published_at") or "", reverse=True)  # najnowsze pierwsze

    rl_streak = 0  # ile rate-limitów z rzędu (3 = pewnie wyczerpany dzienny limit)
    for v in pending:
        vid = v["video_id"]
        try:
            t = db.get_transcript(conn, vid)
        except Exception:
            t = None
        try:
            if t and t.get("text"):
                user = (f"Kanał: {v['channel_name']}\nTytuł: {v['title']}\n"
                        f"Transkrypcja ({t['lang']}, {'auto' if t['generated'] else 'ręczne'} napisy):\n\n"
                        + t["text"][:MAX_TRANSCRIPT_CHARS])
                data = llm.call_json(model=llm.MODEL_CHEAP, system=SYSTEM, user=user,
                                     schema=EXTRACT_SCHEMA, max_tokens=3000)
                src = ""
            else:
                if (v.get("duration_s") or 0) > MAX_VIDEO_S:
                    print(f"  - pomijam (>{MAX_VIDEO_S // 3600}h, za długi na video-URL): {v['title'][:45]}")
                    stats["skip"] += 1
                    continue
                user = (f"Kanał: {v['channel_name']}\nTytuł: {v['title']}\n"
                        "Wyciąg pisz po polsku.")
                data = llm.call_json_video(model=llm.MODEL_CHEAP, system=SYSTEM_VIDEO, user=user,
                                           schema=EXTRACT_SCHEMA, video_url=v["url"], max_tokens=8000)
                src = " [z filmu]"
                stats["video"] += 1
        except Exception as e:
            if _is_rate_limit(e):
                rl_streak += 1
                print(f"  ! limit Gemini na {vid} (z rzędu: {rl_streak})")
                if rl_streak >= 3:
                    print("  ! 3x limit z rzędu — kończę analizę, reszta w kolejnym runie")
                    break
                continue  # pojedynczy film (pewnie za długi) — pomiń, próbuj dalej
            print(f"  ! błąd analizy {vid}: {type(e).__name__}: {str(e)[:120]}")
            db.set_video_status(conn, vid, "error", f"analyze: {e}")
            stats["error"] += 1
            continue
        rl_streak = 0  # sukces resetuje licznik limitów
        db.save_extract(conn, vid, data, model=llm.MODEL_CHEAP)
        print(f"  + wyciąg{src} [{v['channel_name']}] sentyment={data['sentyment']:+d} "
              f"tickery={','.join(data['tickery'][:5])} — {v['title'][:45]}")
        stats["ok"] += 1
    return stats


if __name__ == "__main__":
    print(run(db.connect()))
