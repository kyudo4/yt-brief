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
MODEL_DRAFTS = "claude-sonnet-4-6"          # wyłącznie drafty na X

_client = None


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
    return next(b.text for b in resp.content if b.type == "text")
