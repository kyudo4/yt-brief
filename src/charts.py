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
    "oil": [
        {"typ": "link", "opis": "Ropa WTI", "url": "https://www.tradingview.com/symbols/NYMEX-CL1%21/", "zrodlo": "TradingView"},
        {"typ": "link", "opis": "Cena ropy WTI (EIA/FRED)", "url": "https://fred.stlouisfed.org/series/DCOILWTICO", "zrodlo": "FRED"},
    ],
}

COINGECKO_IDS = {"btc": ("bitcoin", "Bitcoin"), "eth": ("ethereum", "Ethereum")}

# Horyzont wykresu dobrany do CHARAKTERU aktywa: krypto ogląda się w skali dni
# (ruch tygodnia), a makro/waluty/indeksy to zmiany REŻIMU — na 30 dni widać
# tylko szum, więc idą na wieloletnim oknie. Klucz -> etykieta horyzontu.
CHART_HORIZON = {
    "btc": "30d", "eth": "30d",
    "dxy": "5y", "gold": "5y", "spx": "5y", "oil": "5y", "mu": "2y",
}

# horyzont -> (dni CoinGecko, range Yahoo, interval Yahoo, opis do tytułu)
HORIZONS = {
    "30d": (30, "1mo", "1d", "ostatnie 30 dni"),
    "1y":  (365, "1y", "1d", "ostatni rok"),
    "2y":  (730, "2y", "1wk", "ostatnie 2 lata"),
    "5y":  (1825, "5y", "1wk", "ostatnie 5 lat"),
}

# aktywa z Yahoo, dla których generujemy własny PNG (label, symbol Yahoo, jednostka osi)
YAHOO_PNG = {
    "oil":  ("Ropa WTI", "CL=F", "$"),
    "gold": ("Złoto", "GC=F", "$"),
    "spx":  ("S&P 500", "^GSPC", ""),
    "dxy":  ("Indeks dolara (DXY)", "DX-Y.NYB", ""),
    "mu":   ("Micron (MU)", "MU", "$"),
}

# Krypto z Yahoo — używane TYLKO na długim horyzoncie (CoinGecko za darmo tnie do
# 365 dni, więc cyklu 4-letniego BTC nie da się z niego narysować). Krótkie okno
# dalej idzie z CoinGecko (price_chart_png).
YAHOO_CRYPTO = {
    "btc": ("Bitcoin", "BTC-USD", "$"),
    "eth": ("Ethereum", "ETH-USD", "$"),
}
_YAHOO_ALL = {**YAHOO_PNG, **YAHOO_CRYPTO}

_COLORS = {"btc": "#f7931a", "eth": "#8a92f8", "oil": "#e0803a", "gold": "#e8c559",
           "spx": "#5ec27a", "dxy": "#6bd0d6", "mu": "#c07ad6"}


def _render_png(out: Path, xs, ys, title: str, key: str, unit: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    color = _COLORS.get(key, "#8a92f8")
    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=110)
    fig.patch.set_facecolor("#14161a")
    ax.set_facecolor("#14161a")
    ax.plot(xs, ys, color=color, linewidth=1.8)
    ax.fill_between(xs, ys, min(ys), alpha=0.12, color=color)
    ax.set_title(title, color="#e8e8e8", fontsize=10, loc="left")
    ax.tick_params(colors="#9aa0a6", labelsize=8)
    span_days = (max(xs) - min(xs)).days if len(xs) > 1 else 0
    xfmt = "%Y" if span_days > 730 else "%m.%y" if span_days > 180 else "%d.%m"
    ax.xaxis.set_major_formatter(mdates.DateFormatter(xfmt))
    ax.yaxis.set_major_formatter(lambda v, _: f"{unit}{v:,.0f}".replace(",", " "))
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(color="#2a2d33", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)


def price_chart_png(key: str, date: str, assets_dir: Path, horizon: str = "30d") -> dict | None:
    """PNG z ceną BTC/ETH z CoinGecko na zadanym horyzoncie."""
    from datetime import datetime, timezone

    days, _yr, _yi, opis = HORIZONS.get(horizon, HORIZONS["30d"])
    coin_id, label = COINGECKO_IDS[key]
    assets_dir.mkdir(parents=True, exist_ok=True)
    out = assets_dir / f"{date}-{key}-{horizon}.png"
    rel = f"assets/{out.name}"
    meta = {"typ": "png", "opis": f"{label} — {opis}", "sciezka": rel, "zrodlo": "CoinGecko"}
    if out.exists():  # jeden wykres na dzień wystarczy
        return meta

    r = requests.get(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": days},  # interval dobiera CoinGecko po zakresie
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    points = r.json()["prices"]
    xs = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in points]
    ys = [p[1] for p in points]
    _render_png(out, xs, ys, f"{label} / USD — {opis} (CoinGecko)", key, "$")
    return meta


def yahoo_chart_png(key: str, date: str, assets_dir: Path, horizon: str = "30d") -> dict | None:
    """PNG z ceną aktywa z Yahoo Finance (ropa, złoto, indeksy, akcje) na zadanym horyzoncie."""
    from datetime import datetime, timezone

    _days, yrange, yinterval, opis = HORIZONS.get(horizon, HORIZONS["30d"])
    label, symbol, unit = _YAHOO_ALL[key]
    assets_dir.mkdir(parents=True, exist_ok=True)
    out = assets_dir / f"{date}-{key}-{horizon}.png"
    rel = f"assets/{out.name}"
    meta = {"typ": "png", "opis": f"{label} — {opis}", "sciezka": rel, "zrodlo": "Yahoo Finance"}
    if out.exists():
        return meta

    r = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": yrange, "interval": yinterval}, headers=UA, timeout=20,
    )
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    pairs = [(datetime.fromtimestamp(t, tz=timezone.utc), c) for t, c in zip(ts, closes) if c is not None]
    if len(pairs) < 2:
        return None
    xs, ys = zip(*pairs)
    _render_png(out, list(xs), list(ys), f"{label} — {opis} (Yahoo Finance)", key, unit)
    return meta


def for_topic(keys: set[str], date: str, assets_dir: Path | None = None,
              dlugi: bool = False) -> list[dict]:
    """Wykresy dla tematu: kuratorowane linki + własny PNG. Horyzont dobrany do
    tezy tematu: `dlugi=True` (teza strukturalna/cykliczna) ciągnie krypto na
    wieloletnim oknie z Yahoo; krótka teza zostaje na 30 dniach z CoinGecko.
    Makro (DXY, złoto, S&P, ropa) i tak jest wieloletnie z definicji."""
    assets_dir = assets_dir or DEFAULT_ASSETS
    out: list[dict] = []
    for key in sorted(keys):
        out.extend(LINK_CHARTS.get(key, []))
        try:
            png = None
            if key in COINGECKO_IDS:
                if dlugi and key in YAHOO_CRYPTO:  # cykl/reżim — długie okno z Yahoo
                    png = yahoo_chart_png(key, date, assets_dir, horizon="5y")
                else:  # bieżący ruch — 30 dni z CoinGecko
                    png = price_chart_png(key, date, assets_dir, horizon="30d")
            elif key in YAHOO_PNG:
                png = yahoo_chart_png(key, date, assets_dir, horizon=CHART_HORIZON.get(key, "30d"))
            if png:
                out.append(png)
        except Exception as e:
            print(f"  ! wykres {key}: {type(e).__name__}: {e}")
    return out
