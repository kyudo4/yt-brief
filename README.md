# yt-brief

Dostarczyciel pomysłów na content: zbiera ciekawostki z kanałów YouTube
(krypto + makro), analizuje materiały i codziennie oddaje **drafty
wpisów na X** z podpiętym wykresem — plus ściągę "na chłopski rozum", żeby
wiedzieć, o czym się pisze. Wynik jest publikowany wyłącznie na stronie GitHub Pages.

Kanały są głównie anglojęzyczne — transkrypcje idą po angielsku (fallback),
ale cała analiza, ściągi i drafty powstają po polsku.

`telegram_sources.json` trzyma podane kanały t.me — jeszcze nie ingestowane
(osobny moduł do zrobienia; publiczne kanały czyta się przez t.me/s/ bez API).

Codziennie rano GitHub Actions robi pełny obieg: nowe filmy → transkrypcje →
wyciągi → selekcja tematów → twarde dane + wykresy → drafty na X → kontrola
redakcyjna → strona HTML. Ten sam obieg
lokalnie: `python -m src.run_daily`.

## Zasada nr 1: liczby tylko z API

Każda liczba rynkowa na karcie pochodzi z CoinGecko / Stooq / alternative.me.
Transkrypcje dają tezy i sentyment. Liczba wzięta z wypowiedzi na filmie jest
zawsze oznaczona jako „wg [kanał]" i traktowana jako opinia.

## Setup krok po kroku

### 1. Klucze

| Sekret | Skąd |
|---|---|
| `YOUTUBE_API_KEY` | [console.cloud.google.com](https://console.cloud.google.com) → nowy projekt → "APIs & Services" → włącz **YouTube Data API v3** → Credentials → Create API key |

### 2. Lokalnie

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # i uzupełnij klucze
python -m src.run_daily
pytest                 # testy deduplikacji i filtrów
```

### 3. GitHub

1. Utwórz repo, wypchnij kod.
2. **Settings → Secrets and variables → Actions** → dodaj klucze z tabeli wyżej.
3. **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main`, folder `/docs`.
4. **Actions** → workflow `daily` → **Run workflow** (workflow_dispatch) — pierwszy testowy run.

### 4. Dodanie kanału

Dopisz wpis w `channels.json`:

```json
{ "name": "Nazwa", "url": "https://www.youtube.com/@handle", "category": "makro", "weight": 2 }
```

Wystarczy URL z handle — skrypt sam rozwiąże go na `channel_id`. `weight` (1–3)
podbija wagę kanału przy układaniu tematów dnia. Kategorie: `krypto`, `makro`, `akcje`.

## Dlaczego baza SQLite w repo (a nie artefakt Actions)

- Artefakty Actions wygasają (domyślnie po 90 dniach) — po wygaśnięciu tracimy
  deduplikację i pamięć tematów; baza w repo żyje tak długo jak repo.
- Workflow i tak commituje wygenerowane `docs/` — dorzucenie `data/brief.db`
  do tego samego commita to zero dodatkowej infrastruktury.
- Baza to czysty tekst (tezy, tematy), rośnie wolno; gdyby urosła, dodamy
  czyszczenie starych transkrypcji.

## Koszty

Pipeline korzysta z darmowych pul Gemini i GitHub Models. YouTube API,
CoinGecko, Stooq, alternative.me i GitHub Pages/Actions mają darmowe tiery.

## Struktura

```
channels.json         # kanały do śledzenia
style_examples.json   # wzorce twojego stylu na X (TODO: uzupełnij!)
src/                  # pipeline (fetch → transcripts → analyze → topics → drafts → quality → site)
templates/            # Jinja2 + CSS
data/brief.db         # SQLite (commitowana)
docs/                 # wygenerowana strona (GitHub Pages)
.github/workflows/    # codzienny cron + ręczny trigger
```
