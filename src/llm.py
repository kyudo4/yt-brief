"""Wspólna warstwa wywołań LLM — ŁAŃCUCHY darmowych modeli z automatycznym failoverem.

Zasada: każde zadanie ma uporządkowaną listę darmowych modeli. Gdy model odmawia
(limit dobowy, awaria, odrzucony schemat), wywołanie samo schodzi na następny w łańcuchu.
Prefiks "github:" = GitHub Models (wbudowany token Actions), reszta = Gemini.

Pule są niezależne per model/dostawca (zweryfikowane sondami 2026-07-09):
- Gemini 2.5-flash ~20 zapytań/dobę, 2.5-flash-lite osobna pula; pro i 2.0-flash limit 0.
- GitHub Models (gpt-4.1, gpt-4o, ...) — osobne pule na koncie GitHub.
Ekstrakcja z FILMÓW (YouTube URL) działa wyłącznie na modelach Gemini.
"""

from __future__ import annotations

import json
import os
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Łańcuch draftów: najlepszy pisarz najpierw, potem kolejne darmowe pule.
# Każdy model na GitHub Models ma WŁASNĄ pulę; błędny/wycofany ID nie szkodzi —
# failover po prostu przechodzi dalej. Kolejność = jakość polszczyzny i tonu.
CHAIN_DRAFTS = [m.strip() for m in os.environ.get(
    "LLM_CHAIN_DRAFTS",
    "github:openai/gpt-4.1,github:openai/gpt-4o,github:deepseek/DeepSeek-V3-0324,"
    "github:mistral-ai/Mistral-Large-2411,github:openai/gpt-4.1-mini,"
    "github:meta/Llama-3.3-70B-Instruct,gemini-2.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()]
# Łańcuch ekstrakcji (musi być Gemini — czytanie wideo z URL umie tylko Gemini):
CHAIN_EXTRACT = [m.strip() for m in os.environ.get(
    "LLM_CHAIN_EXTRACT", "gemini-2.5-flash-lite,gemini-2.5-flash").split(",") if m.strip()]
# Łańcuch grupowania tematów: DUŻY payload (kilkanaście wyciągów) nie mieści się
# w limicie wejścia darmowego GitHub Models (~8k tokenów), więc Gemini najpierw.
CHAIN_TOPICS = [m.strip() for m in os.environ.get(
    "LLM_CHAIN_TOPICS",
    "gemini-2.5-flash,gemini-2.5-flash-lite,github:openai/gpt-4.1-mini").split(",") if m.strip()]

# Etykiety zgodne ze starym interfejsem — call sites podają llm.MODEL_*,
# a _chain() rozwija je w pełny łańcuch failoveru.
MODEL_CHEAP = CHAIN_EXTRACT[0]
MODEL_DRAFTS = CHAIN_DRAFTS[0]
MODEL_TOPICS = CHAIN_TOPICS[0]


def _chain(model: str) -> list[str]:
    if model == MODEL_DRAFTS:
        return CHAIN_DRAFTS
    if model == MODEL_TOPICS:
        return CHAIN_TOPICS
    if model == MODEL_CHEAP:
        return CHAIN_EXTRACT
    return [model]

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
    return (f"~$0 (darmowe pule: Gemini + GitHub Models)  — wejście {_usage['in'] // 1000}k, "
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


# --- GitHub Models (darmowe GPT na koncie GitHub; w Actions token wbudowany) ---

GH_MODELS_URL = "https://models.github.ai/inference/chat/completions"


def _github_chat(model: str, system: str, user: str, max_tokens: int, schema=None) -> str:
    """Jedno wywołanie GitHub Models (model = 'github:openai/gpt-4.1').
    Ze schematem używa strict json_schema (nasze schematy mają additionalProperties=false
    i pełne required, czyli dokładnie to, czego strict wymaga)."""
    import urllib.error
    import urllib.request
    token = os.environ.get("GH_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("brak GITHUB_TOKEN dla GitHub Models")
    gh_model = model.split(":", 1)[1]
    body = {
        "model": gh_model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": min(max_tokens, 4000),  # darmowy tier ogranicza wyjście
    }
    if schema is not None:
        if gh_model.startswith("openai/"):
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "wynik", "strict": True, "schema": schema}}
        else:  # DeepSeek/Grok/Mistral/Llama: strict json_schema nieobsługiwany — schemat w promptcie
            body["messages"][1]["content"] = user + \
                "\n\nZwróć WYŁĄCZNIE poprawny JSON (bez markdown) zgodny ze schematem:\n" + \
                json.dumps(schema, ensure_ascii=False)
    req = urllib.request.Request(
        GH_MODELS_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:  # dołącz treść błędu do logu failoveru
        raise RuntimeError(f"GitHub Models HTTP {e.code}: {e.read()[:200]!r}") from e
    u = d.get("usage") or {}
    _usage["in"] += u.get("prompt_tokens", 0)
    _usage["out"] += u.get("completion_tokens", 0)
    _usage["calls"] += 1
    return d["choices"][0]["message"]["content"]


def _generate(model: str, system: str, user: str, max_tokens: int, schema=None):
    kwargs = dict(system_instruction=system, max_output_tokens=max_tokens)
    if schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = schema
    cfg = types.GenerateContentConfig(**kwargs)
    return client().models.generate_content(model=model, contents=user, config=cfg)


def _gemini_json(model: str, system: str, user: str, schema: dict, max_tokens: int) -> dict:
    """Jedno zadanie JSON na konkretnym modelu Gemini: retry na limicie minutowym,
    fallback json-mime przy odrzuconym schemacie, podwojenie budżetu przy ucięciu.
    Limit DOBOWY rzuca wyjątkiem — decyzję o zmianie modelu podejmuje call_json."""
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
                    raise  # dobowy — niech przejmie następny model w łańcuchu
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


def _require(out: dict, schema: dict) -> dict:
    """Pilnuje kontraktu: brak wymaganych pól = wyjątek = failover do następnego modelu
    (chroni przed kadłubkiem z modeli bez strict json_schema)."""
    missing = [k for k in schema.get("required", []) if k not in out]
    if missing:
        raise ValueError(f"model pominął wymagane pola: {missing}")
    return out


def call_json(*, model: str, system: str, user: str, schema: dict, max_tokens: int = 4096) -> dict:
    """Structured output -> dict zgodny ze schematem, z failoverem po łańcuchu
    darmowych modeli: gdy jeden odmawia (limit/awaria), próbuje następnego."""
    last = None
    for m in _chain(model):
        try:
            if m.startswith("github:"):
                return _require(_loads(_github_chat(m, system, user, max_tokens, schema=schema)), schema)
            return _require(_gemini_json(m, system, user, schema, max_tokens), schema)
        except Exception as e:
            print(f"  ~ {m} odmówił ({type(e).__name__}: {str(e)[:100]}) — próbuję następny w łańcuchu")
            last = e
    raise last


def call_text(*, model: str, system: str, user: str, max_tokens: int = 2048) -> str:
    """Zwykłe wywołanie tekstowe, z failoverem po łańcuchu jak call_json."""
    last = None
    for m in _chain(model):
        try:
            if m.startswith("github:"):
                return _github_chat(m, system, user, max_tokens).strip()
            resp = _generate(m, system, user, max_tokens)
            track(m, resp)
            return _text(resp).strip()
        except Exception as e:
            print(f"  ~ {m} odmówił ({type(e).__name__}: {str(e)[:100]}) — próbuję następny w łańcuchu")
            last = e
    raise last


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


def _gemini_video_json(model: str, system: str, user: str, schema: dict,
                       video_url: str, max_tokens: int) -> dict:
    """Jedna ekstrakcja z filmu na konkretnym modelu Gemini (retry minutowy w środku)."""
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


def call_json_video(*, model: str, system: str, user: str, schema: dict, video_url: str,
                    max_tokens: int = 8000) -> dict:
    """Ekstrakcja wprost z FILMU YouTube — Gemini 'ogląda' URL, więc omijamy blokadę
    pobierania transkrypcji z IP chmury (Google pobiera film u siebie).

    Failover po łańcuchu ekstrakcji (modele GitHub pomijane — wideo umie tylko Gemini).
    Niska rozdzielczość + myślenie off + przycięcie do ~33 min (limit tokenów/min).
    """
    last = None
    for m in _chain(model):
        if m.startswith("github:"):
            continue  # GitHub Models nie czyta YouTube z URL
        try:
            return _gemini_video_json(m, system, user, schema, video_url, max_tokens)
        except Exception as e:
            print(f"  ~ {m} odmówił przy wideo ({type(e).__name__}: {str(e)[:100]}) — próbuję następny")
            last = e
    raise last
