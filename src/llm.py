"""Wspólna warstwa wywołań LLM — Google Gemini (darmowy tier).

Migracja z Claude: interfejs (call_json / call_text / MODEL_* / cost_summary /
client / track) BEZ ZMIAN, więc analyze/topics/drafts zostają nietknięte.
Gemini Flash na darmowym tierze — koszt ~$0. Uwaga: darmowy tier ma limity tempa,
a dane z zapytań mogą iść na trening Google (patrz .env.example).

- Ekstrakcja i grupowanie: MODEL_CHEAP (Flash).
- Drafty na X: MODEL_DRAFTS (Flash).
- JSON przez structured output (response_schema); gdy Gemini odrzuci schemat,
  fallback na czysty json-mime z opisem schematu w promcie.
"""

from __future__ import annotations

import json
import os
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Modele Gemini (konfigurowalne env). 2.5-flash to jedyny model z darmowym tierem
# na tym koncie (2.0-flash ma limit 0). Darmowy limit 2.5-flash: ~20 zapytań/dobę —
# starcza na normalny dzień (kilka filmów), przy zaległościach analyze dzieli na kilka dni.
MODEL_CHEAP = os.environ.get("GEMINI_MODEL_CHEAP", "gemini-2.5-flash")    # ekstrakcja + tematy
MODEL_DRAFTS = os.environ.get("GEMINI_MODEL_DRAFTS", "gemini-2.5-flash")  # drafty

_client = None
_usage = {"in": 0, "out": 0, "calls": 0}  # tokeny wejścia/wyjścia + liczba wywołań


def client() -> genai.Client:
    global _client
    if _client is None:
        load_dotenv()
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise SystemExit("Brak GEMINI_API_KEY — pobierz klucz z aistudio.google.com i uzupełnij .env.")
        _client = genai.Client(api_key=key)
    return _client


def track(model: str, resp) -> None:
    """Zlicza tokeny z odpowiedzi — do orientacyjnego logu (Gemini free = ~$0)."""
    u = getattr(resp, "usage_metadata", None)
    if not u:
        return
    _usage["in"] += getattr(u, "prompt_token_count", 0) or 0
    _usage["out"] += getattr(u, "candidates_token_count", 0) or 0
    _usage["calls"] += 1


def cost_summary() -> str:
    return (f"~$0 (Gemini free tier)  — wejście {_usage['in'] // 1000}k, "
            f"wyjście {_usage['out'] // 1000}k, wywołań {_usage['calls']}")


# --- pomocnicze ---

# klucze schematu JSON, których Gemini response_schema nie akceptuje
_DROP_KEYS = {"additionalProperties", "$schema", "$id", "default"}


def _clean_schema(node):
    """Przycina schemat do postaci strawnej dla Gemini: usuwa additionalProperties itd.
    oraz enum-y liczbowe (Gemini wymaga enum jako listy STRINGÓW — typ+opis wystarczą,
    np. sentyment integer -2..2 zostaje bez enum)."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in _DROP_KEYS:
                continue
            if k == "enum" and isinstance(v, list) and not all(isinstance(x, str) for x in v):
                continue  # enum niestringowy — Gemini go nie przyjmie
            out[k] = _clean_schema(v)
        return out
    if isinstance(node, list):
        return [_clean_schema(x) for x in node]
    return node


def _text(resp) -> str:
    """Bezpiecznie wyciąga tekst (resp.text potrafi rzucić przy blokadzie/pustej odpowiedzi)."""
    try:
        if resp.text:
            return resp.text
    except Exception:
        pass
    out = []
    for c in getattr(resp, "candidates", None) or []:
        content = getattr(c, "content", None)
        for p in getattr(content, "parts", None) or []:
            if getattr(p, "text", None):
                out.append(p.text)
    return "".join(out)


def _truncated(resp) -> bool:
    """Czy odpowiedź ucięta na limicie tokenów (odpowiednik Claude stop_reason=max_tokens)."""
    for c in getattr(resp, "candidates", None) or []:
        fr = getattr(c, "finish_reason", None)
        if fr is not None and getattr(fr, "name", str(fr)) == "MAX_TOKENS":
            return True
    return False


def _loads(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)  # ratunek, gdyby model dodał fence/tekst
        if m:
            return json.loads(m.group(0))
        raise


def _generate(model: str, system: str, user: str, max_tokens: int, schema=None):
    kwargs = dict(system_instruction=system, max_output_tokens=max_tokens)
    if schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = schema
    cfg = types.GenerateContentConfig(**kwargs)
    return client().models.generate_content(model=model, contents=user, config=cfg)


def call_json(*, model: str, system: str, user: str, schema: dict, max_tokens: int = 4096) -> dict:
    """Structured output -> dict zgodny ze schematem.

    Przy ucięciu (MAX_TOKENS) ponawia z podwojonym budżetem (żeby nie oddać
    kadłubka). Gdyby Gemini odrzucił schemat, fallback: czysty json-mime z opisem
    schematu doklejonym do promptu.
    """
    gschema = _clean_schema(schema)
    resp = None
    for _ in range(2):
        for attempt in range(4):
            try:
                resp = _generate(model, system, user, max_tokens, schema=gschema)
                break
            except Exception as e:
                if _is_rate_limit(e) and not _is_daily_limit(e) and attempt < 3:
                    time.sleep(35)  # limit tokenów/min — przeczekaj i ponów
                    continue
                if _is_rate_limit(e):
                    raise  # dobowy — fallback nic nie da
                # nie-limit (najczęściej schemat) — fallback json-mime bez response_schema
                hint = user + "\n\nZwróć WYŁĄCZNIE poprawny JSON zgodny ze schematem:\n" \
                    + json.dumps(gschema, ensure_ascii=False)
                resp = client().models.generate_content(
                    model=model, contents=hint,
                    config=types.GenerateContentConfig(
                        system_instruction=system, max_output_tokens=max_tokens,
                        response_mime_type="application/json"))
                break
        track(model, resp)
        if not _truncated(resp):
            break
        max_tokens *= 2  # ucięte — spróbuj jeszcze raz z większym budżetem
    return _loads(_text(resp))


def call_text(*, model: str, system: str, user: str, max_tokens: int = 2048) -> str:
    """Zwykłe wywołanie tekstowe."""
    resp = _generate(model, system, user, max_tokens)
    track(model, resp)
    return _text(resp).strip()


# Darmowy tier: 250k tokenów WEJŚCIA na minutę. Film w niskiej rozdzielczości to
# ~100 tok/s, więc >~40 min = >250k w jednym zapytaniu = zawsze 429. Przycinamy do
# pierwszych ~33 min (200k, z zapasem) — to i tak łapie główne tezy filmu.
VIDEO_CLIP_S = 2000


def _is_rate_limit(e) -> bool:
    s = str(e).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s


def _is_daily_limit(e) -> bool:
    # limit dobowy (nie do przeczekania) vs na minutę (do przeczekania)
    return "perday" in str(e).lower().replace("_", "")


def call_json_video(*, model: str, system: str, user: str, schema: dict, video_url: str,
                    max_tokens: int = 8000) -> dict:
    """Ekstrakcja wprost z FILMU YouTube — Gemini 'ogląda' URL, więc omijamy blokadę
    pobierania transkrypcji z IP chmury (Google pobiera film u siebie).

    Niska rozdzielczość + wyłączone myślenie + przycięcie do ~33 min (limit tokenów/min).
    Przy limicie NA MINUTĘ przeczekuje i ponawia; przy DOBOWYM od razu rzuca (analyze
    zostawi resztę na kolejny run). Przy ucięciu odpowiedzi ponawia z większym budżetem.
    """
    gschema = _clean_schema(schema)
    part_video = types.Part(
        file_data=types.FileData(file_uri=video_url),
        video_metadata=types.VideoMetadata(end_offset=f"{VIDEO_CLIP_S}s"),
    )
    resp = None
    for _ in range(2):
        cfg = types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=max_tokens,
            response_mime_type="application/json", response_schema=gschema,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        for attempt in range(4):
            try:
                resp = client().models.generate_content(
                    model=model,
                    contents=types.Content(parts=[part_video, types.Part(text=user)]),
                    config=cfg,
                )
                break
            except Exception as e:
                if _is_rate_limit(e) and not _is_daily_limit(e) and attempt < 3:
                    time.sleep(35)  # limit tokenów/min odświeża się co minutę
                    continue
                raise
        track(model, resp)
        if not _truncated(resp):
            break
        max_tokens *= 2
    return _loads(_text(resp))
