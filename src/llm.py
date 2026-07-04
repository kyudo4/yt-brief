"""Wspólna warstwa wywołań Claude API.

- Ekstrakcja i grupowanie: claude-haiku-4-5-20251001 (najtańszy).
- Drafty na X: claude-sonnet-4-6 (tylko finalne teksty).
- Stałe części promptów (system) z cache_control ephemeral — hity cache
  w obrębie jednego runu. Uwaga: Haiku 4.5 cache'uje prefiksy od ~4096
  tokenów, krótsze systemy po prostu nie łapią cache (bez błędu).
- JSON przez structured outputs (output_config.format) — API gwarantuje
  poprawny JSON zgodny ze schematem, zero parsowania fence'ów.
"""

from __future__ import annotations

import json
import os

import anthropic
from dotenv import load_dotenv

MODEL_CHEAP = "claude-haiku-4-5-20251001"   # ekstrakcja + tematy
MODEL_DRAFTS = "claude-sonnet-4-6"          # drafty + fact-check

# ceny $/mln tokenów (wejście/wyjście) + web search $/1000 zapytań
PRICE = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0)}
WEB_SEARCH_PRICE = 10.0 / 1000

_client = None
_usage = {"haiku": [0, 0], "sonnet": [0, 0], "web_searches": 0}  # [wejście, wyjście]


def track(model: str, resp) -> None:
    """Zlicza tokeny i web searche z odpowiedzi — do orientacyjnego logu kosztów."""
    tier = "haiku" if "haiku" in model else "sonnet"
    u = resp.usage
    wejscie = u.input_tokens + (getattr(u, "cache_read_input_tokens", 0) or 0) \
        + (getattr(u, "cache_creation_input_tokens", 0) or 0)
    _usage[tier][0] += wejscie
    _usage[tier][1] += u.output_tokens
    stu = getattr(u, "server_tool_use", None)
    if stu:
        _usage["web_searches"] += getattr(stu, "web_search_requests", 0) or 0


def cost_summary() -> str:
    """Orientacyjny koszt runu (górny szacunek — wejście liczone bez rabatu za cache)."""
    total = _usage["web_searches"] * WEB_SEARCH_PRICE
    for tier, (pin, pout) in PRICE.items():
        total += _usage[tier][0] / 1e6 * pin + _usage[tier][1] / 1e6 * pout
    h, s = _usage["haiku"], _usage["sonnet"]
    return (f"~${total:.3f}  (haiku {h[0]//1000}k→{h[1]//1000}k, "
            f"sonnet {s[0]//1000}k→{s[1]//1000}k, web search {_usage['web_searches']})")


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Brak ANTHROPIC_API_KEY — uzupełnij .env (instrukcja w README).")
        _client = anthropic.Anthropic()
    return _client


def call_json(*, model: str, system: str, user: str, schema: dict, max_tokens: int = 4096) -> dict:
    """Wywołanie ze structured output — zwraca dict zgodny ze schematem."""
    resp = client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user}],
    )
    track(model, resp)
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def call_text(*, model: str, system: str, user: str, max_tokens: int = 2048) -> str:
    """Zwykłe wywołanie tekstowe (drafty)."""
    resp = client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    track(model, resp)
    return next(b.text for b in resp.content if b.type == "text")
