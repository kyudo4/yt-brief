"""Twarde dane rynkowe z darmowych API — jedyne źródło liczb w kartach.

- CoinGecko: ceny/wolumen/zmiana 24h BTC, ETH + dominacja BTC
- Yahoo Finance (chart API, bez klucza): MU, DXY, S&P 500, złoto
  (Stooq odpadł — wprowadził challenge anty-botowy, nieużywalny ze skryptu)
- alternative.me: Fear & Greed Index

Każdy wpis niesie 'zrodlo' + 'url' — karta zawsze pokazuje skąd liczba.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

from . import db

UA = {"User-Agent": "Mozilla/5.0 (yt-brief)"}
TIMEOUT = 20

YAHOO = {
    "mu":   ("MU", "Micron (MU)"),
    "dxy":  ("DX-Y.NYB", "Indeks dolara (DXY)"),
    "spx":  ("^GSPC", "S&P 500"),
    "gold": ("GC=F", "Złoto (futures)"),
}


def _get(url: str, **params) -> dict:
    r = requests.get(url, params=params or None, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _fmt(x: float, unit: str = "$") -> str:
    if x >= 1000:
        return f"{unit}{x:,.0f}".replace(",", " ")
    return f"{unit}{x:,.2f}"


def crypto_prices() -> list[dict]:
    data = _get(
        "https://api.coingecko.com/api/v3/simple/price",
        ids="bitcoin,ethereum", vs_currencies="usd",
        include_24hr_change="true", include_24hr_vol="true",
    )
    out = []
    for key, cg, label in (("btc", "bitcoin", "Bitcoin"), ("eth", "ethereum", "Ethereum")):
        d = data[cg]
        out.append({
            "klucz": key, "label": label,
            "wartosc": _fmt(d["usd"]),
            "zmiana_24h": f"{d['usd_24h_change']:+.1f}%",
            "wolumen_24h": _fmt(d["usd_24h_vol"]),
            "zrodlo": "CoinGecko",
            "url": f"https://www.coingecko.com/en/coins/{cg}",
        })
    return out


def btc_dominance() -> dict:
    g = _get("https://api.coingecko.com/api/v3/global")["data"]
    return {
        "klucz": "dominacja_btc", "label": "Dominacja BTC",
        "wartosc": f"{g['market_cap_percentage']['btc']:.1f}%",
        "zrodlo": "CoinGecko", "url": "https://www.coingecko.com/en/global-charts",
    }


def fear_greed() -> dict:
    d = _get("https://api.alternative.me/fng/?limit=1")["data"][0]
    return {
        "klucz": "fear_greed", "label": "Fear & Greed Index",
        "wartosc": f"{d['value']} ({d['value_classification']})",
        "zrodlo": "alternative.me", "url": "https://alternative.me/crypto/fear-and-greed-index/",
    }


def yahoo_quote(key: str) -> dict:
    symbol, label = YAHOO[key]
    meta = _get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        range="5d", interval="1d",
    )["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    entry = {
        "klucz": key, "label": label,
        "wartosc": _fmt(price, "$" if key in ("mu", "gold") else ""),
        "zrodlo": "Yahoo Finance",
        "url": f"https://finance.yahoo.com/quote/{symbol}",
    }
    if prev:
        entry["zmiana_5d"] = f"{(price / prev - 1) * 100:+.1f}%"
    return entry


def fetch(keys: set[str]) -> list[dict]:
    """Pobiera tylko dane z `keys`. Błąd jednego źródła nie blokuje reszty."""
    out: list[dict] = []

    def _try(fn, *args):
        try:
            res = fn(*args)
            out.extend(res if isinstance(res, list) else [res])
        except Exception as e:
            print(f"  ! dane rynkowe ({fn.__name__}{args}): {type(e).__name__}: {e}")

    if keys & {"btc", "eth"}:
        _try(crypto_prices)
        out[:] = [e for e in out if e["klucz"] in keys or e["klucz"] not in ("btc", "eth")]
    if "dominacja_btc" in keys:
        _try(btc_dominance)
    if "fear_greed" in keys:
        _try(fear_greed)
    for key in keys & set(YAHOO):
        _try(yahoo_quote, key)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for e in out:
        e["pobrano"] = stamp
    return out


def enrich_topics(conn, topic_ids: list[int], date: str, assets_dir=None) -> None:
    """Dokłada twarde dane i wykresy do kart zapisanych tematów."""
    from . import charts

    rows = [t for t in db.topics_for_date(conn, date) if t["id"] in set(topic_ids)]
    all_keys = set()
    for t in rows:
        all_keys |= set(t["card"].get("potrzebne_dane", []))
    data = {e["klucz"]: e for e in fetch(all_keys)} if all_keys else {}

    for t in rows:
        card = t["card"]
        keys = set(card.get("potrzebne_dane", []))
        card["twarde_dane"] = [data[k] for k in keys if k in data]
        card["wykresy"] = charts.for_topic(keys, date, assets_dir)
        db.update_topic_card(conn, t["id"], card)
        print(f"  + temat #{t['id']}: {len(card['twarde_dane'])} metryk, {len(card['wykresy'])} wykresów")


if __name__ == "__main__":
    print(json.dumps(fetch({"btc", "eth", "dominacja_btc", "fear_greed", "dxy", "mu", "spx", "gold"}),
                     ensure_ascii=False, indent=2))
