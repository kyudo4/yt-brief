# yt-brief

Dostarczyciel pomysłów na content: zbiera ciekawostki z kanałów YouTube
(krypto + makro), analizuje przez Claude i codziennie oddaje **gotowe drafty
wpisów na X** z podpiętym wykresem — plus ściągę "na chłopski rozum", żeby
wiedzieć, o czym się pisze. Strona na GitHub Pages, powiadomienie na Telegram.

Kanały są głównie anglojęzyczne — transkrypcje idą po angielsku (fallback),
ale cała analiza, ściągi i drafty powstają po polsku.

`telegram_sources.json` trzyma podane kanały t.me — jeszcze nie ingestowane
(osobny moduł do zrobienia; publiczne kanały czyta się przez t.me/s/ bez API).

Codziennie rano (cron 05:00 UTC = 07:00 latem / 06:00 zimą) GitHub Actions robi
pełny obieg: nowe filmy → transkrypcje → wyciągi (Haiku) → tematy dnia → twarde
dane + wykresy → drafty na X (Sonnet) → strona HTML → Telegram. Ten sam obieg
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
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/settings/keys) → Create Key |
| `TELEGRAM_BOT_TOKEN` | Telegram → napisz do **@BotFather** → `/newbot` → skopiuj token |
| `TELEGRAM_CHAT_ID` | napisz do **@userinfobot** (twój prywatny id) albo dodaj bota do grupy i odczytaj id z `https://api.telegram.org/bot<TOKEN>/getUpdates` |

Ważne: napisz najpierw cokolwiek do swojego bota (np. `/start`), inaczej nie
będzie mógł wysyłać ci wiadomości.

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
2. **Settings → Secrets and variables → Actions** → dodaj 4 sekrety z tabeli wyżej.
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

Jedyny płatny element: Anthropic API. Ekstrakcja i grupowanie na
`claude-haiku-4-5-20251001`, drafty na Sonnecie tylko dla tematów, które się
nadają. Stałe części promptów z prompt cachingiem. YouTube API, CoinGecko,
Stooq, alternative.me, GitHub Pages/Actions — darmowe tiery.

## Struktura

```
channels.json         # kanały do śledzenia
style_examples.json   # wzorce twojego stylu na X (TODO: uzupełnij!)
src/                  # pipeline (fetch → transcripts → analyze → topics → site → notify)
templates/            # Jinja2 + CSS
data/brief.db         # SQLite (commitowana)
docs/                 # wygenerowana strona (GitHub Pages)
.github/workflows/    # cron 05:00 UTC (07:00 CEST) + ręczny trigger
```
