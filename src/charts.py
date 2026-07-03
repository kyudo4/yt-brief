"""Wykresy do kart tematów.

1. Kuratorowane linki do sprawdzonych wykresów (TradingView, CoinGlass, FRED,
   alternative.me) dobierane po kluczach danych tematu.
2. Dla BTC/ETH dodatkowo własny PNG (matplotlib, 30 dni z CoinGecko) osadzany
   na stronie — generowany raz dziennie, cache po nazwie pliku.
"""

from __future__ import annotations

from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (yt-brief)"}
DEFAULT_ASSETS = Path(__file__).parent.parent / "docs" / "assets"

# klucz danych -> linki do wykresów w necie (typ "link" = miniatura/odnośnik ze źródłem)
LINK_CHARTS: dict[str, list[dict]] = {
    "btc": [
        {"typ": "link", "opis": "BTC/USD — wykres", "url": "https://www.tradingview.com/symbols/BTCUSD/", "zrodlo": "TradingView"},
        {"typ": "link", "opis": "Mapa likwidacji BTC", "url": "https://www.coinglass.com/pro/futures/LiquidationHeatMap", "zrodlo": "CoinGlass"},
    ],
    "eth": [
        {"typ": "link", "opis": "ETH/USD — wykres", "url": "https://www.tradingview.com/symbols/ETHUSD/", "zrodlo": "TradingView"},
    ],
    "dominacja_btc": [
        {"typ": "link", "opis": "Dominacja BTC", "url": "https://www.tradingview.com/symbols/BTC.D/", "zrodlo": "TradingView"},
    ],
    "fear_greed": [
        {"typ": "img", "opis": "Fear & Greed Index", "img": "https://alternative.me/crypto/fear-and-greed-index.png",
         "url": "https://alternative.me/crypto/fear-and-greed-index/", "zrodlo": "alternative.me"},
    ],
    "dxy": [
        {"typ": "link", "opis": "Indeks dolara (DXY)", "url": "https://www.tradingview.com/symbols/TVC-DXY/", "zrodlo": "TradingView"},
        {"typ": "link", "opis": "Szeroki indeks dolara", "url": "https://fred.stlouisfed.org/series/DTWEXBGS", "zrodlo": "FRED"},
    ],
    "mu": [
        {"typ": "link", "opis": "Micron (MU)", "url": "https://www.tradingview.com/symbols/NASDAQ-MU/", "zrodlo": "TradingView"},
    ],
    "spx": [
        {"typ": "link", "opis": "S&P 500", "url": "https://www.tradingview.com/symbols/SPX/", "zrodlo": "TradingView"},
    ],
    "gold": [
        {"typ": "link", "opis": "Złoto (XAU/USD)", "url": "https://www.tradingview.com/symbols/XAUUSD/", "zrodlo": "TradingView"},
    ],
}

COINGECKO_IDS = {"btc": ("bitcoin", "Bitcoin"), "eth": ("ethereum", "Ethereum")}


def price_chart_png(key: str, date: str, assets_dir: Path, days: int = 30) -> dict | None:
    """PNG z ceną BTC/ETH z ostatnich 30 dni (CoinGecko). Fallback matplotlib ze specu."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from datetime import datetime, timezone

    coin_id, label = COINGECKO_IDS[key]
    assets_dir.mkdir(parents=True, exist_ok=True)
    out = assets_dir / f"{date}-{key}-{days}d.png"
    rel = f"assets/{out.name}"
    if out.exists():  # jeden wykres na dzień wystarczy
        return {"typ": "png", "opis": f"{label} — {days} dni", "sciezka": rel, "zrodlo": "CoinGecko"}

    r = requests.get(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": days, "interval": "daily"},
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    points = r.json()["prices"]
    xs = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in points]
    ys = [p[1] for p in points]

    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=110)
    fig.patch.set_facecolor("#14161a")
    ax.set_facecolor("#14161a")
    ax.plot(xs, ys, color="#f7931a" if key == "btc" else "#8a92f8", linewidth=1.8)
    ax.fill_between(xs, ys, min(ys), alpha=0.12, color="#f7931a" if key == "btc" else "#8a92f8")
    ax.set_title(f"{label} / USD — ostatnie {days} dni (CoinGecko)", color="#e8e8e8", fontsize=10, loc="left")
    ax.tick_params(colors="#9aa0a6", labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:,.0f}".replace(",", " "))
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(color="#2a2d33", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return {"typ": "png", "opis": f"{label} — {days} dni", "sciezka": rel, "zrodlo": "CoinGecko"}


def for_topic(keys: set[str], date: str, assets_dir: Path | None = None) -> list[dict]:
    """Wykresy dla tematu: kuratorowane linki + PNG dla BTC/ETH."""
    assets_dir = assets_dir or DEFAULT_ASSETS
    out: list[dict] = []
    for key in sorted(keys):
        out.extend(LINK_CHARTS.get(key, []))
        if key in COINGECKO_IDS:
            try:
                png = price_chart_png(key, date, assets_dir)
                if png:
                    out.append(png)
            except Exception as e:
                print(f"  ! wykres {key}: {type(e).__name__}: {e}")
    return out
