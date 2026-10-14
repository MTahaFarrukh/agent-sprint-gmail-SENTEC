"""Thin multi-provider LLM wrapper. Returns parsed JSON only."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
from typing import Any

import requests

from src.config import (
    ANTHROPIC_API_KEY,
    DEFAULT_GEMINI_MODEL,
    GEMINI_API_KEY,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_API_KEY,
)

LLM_TIMEOUT_SECONDS: int = 30
MAX_RETRIES: int = 3
MAX_429_WAIT_SECONDS: float = 120.0
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
RETRY_DELAY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)

LLM_MIN_INTERVAL_SECONDS: float = float(
    os.getenv("LLM_MIN_INTERVAL_SECONDS", "4.5") or "4.5"
)
LLM_DEBUG: bool = os.getenv("LLM_DEBUG", "").strip().lower() in {"1", "true", "yes"}
LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", "").strip()

_rate_lock = threading.Lock()
_last_call_monotonic: float = 0.0


class RateLimitError(RuntimeError):
    """HTTP 429 from a provider; carries suggested retry delay in seconds."""

    def __init__(self, message: str, retry_delay: float) -> None:
        super().__init__(message)
        self.retry_delay = max(0.0, float(retry_delay))


def _short_message(exc: BaseException, limit: int = 200) -> str:
    """First N chars of the exception message on one line."""
    msg = str(exc).replace("\n", " ").strip()
    if len(msg) > limit:
        msg = msg[: limit - 1] + "…"
    return msg


def _log_failure(stage: str, exc: BaseException, *, raw: str | None = None) -> None:
    """One short failure line; extra detail only when LLM_DEBUG=1."""
    print(
        f"[llm:{stage}] {type(exc).__name__}: {_short_message(exc)}",
        flush=True,
    )
    if LLM_DEBUG:
        if raw is not None:
            print(f"[llm:{stage}] raw response:\n{raw}", flush=True)
        print(f"[llm:{stage}] traceback:\n{traceback.format_exc()}", flush=True)


def _wait_rate_limit() -> None:
    """Enforce a minimum interval between any two LLM HTTP calls."""
    global _last_call_monotonic
    with _rate_lock:
        now = time.monotonic()
        wait = LLM_MIN_INTERVAL_SECONDS - (now - _last_call_monotonic)
        if wait > 0:
            time.sleep(wait)
        _last_call_monotonic = time.monotonic()


def _default_model(provider: str) -> str:
    """Pick a sensible default model when LLM_MODEL is unset."""
    if LLM_MODEL:
        return LLM_MODEL
    defaults = {
        "gemini": DEFAULT_GEMINI_MODEL,
        "anthropic": "claude-3-5-haiku-latest",
        "openai": "gpt-4o-mini",
    }
    return defaults.get(provider, DEFAULT_GEMINI_MODEL)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences so raw JSON can be parsed."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = FENCE_RE.sub("", cleaned).strip()
    return cleaned


def _parse_json_text(text: str) -> dict[str, Any]:
    """Parse model output as a JSON object after stripping fences."""
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        _log_failure("json_parse", exc, raw=text)
        raise
    if not isinstance(data, dict):
        err = ValueError("LLM response JSON must be an object")
        _log_failure("json_parse", err, raw=text)
        raise err
    return data


def _http_error_detail(response: requests.Response) -> str:
    """Short status + body snippet for failed HTTP calls."""
    limit = 2000 if LLM_DEBUG else 200
    body = (response.text or "").replace("\n", " ")[:limit]
    return f"HTTP {response.status_code}: {body}"


def _parse_retry_delay(response: requests.Response, default: float = 15.0) -> float:
    """Extract retryDelay / Retry-After from a 429 response."""
    header = response.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    details = (payload.get("error") or {}).get("details") or []
    for item in details:
        if not isinstance(item, dict):
            continue
        delay = item.get("retryDelay")
        if isinstance(delay, str):
            match = RETRY_DELAY_RE.search(delay)
            if match:
                return float(match.group(1))
        if isinstance(delay, (int, float)):
            return float(delay)

    match = RETRY_DELAY_RE.search(response.text or "")
    if match:
        return float(match.group(1))
    return default


def _raise_for_status(response: requests.Response, *, provider: str, model: str) -> None:
    """Raise RateLimitError on 429, RuntimeError on other HTTP failures."""
    if response.status_code == 429:
        delay = _parse_retry_delay(response)
        raise RateLimitError(
            f"{provider} rate-limited model={model!r}: {_http_error_detail(response)}",
            retry_delay=delay,
        )
    if not response.ok:
        raise RuntimeError(
            f"{provider} call failed for model={model!r}: {_http_error_detail(response)}"
        )


def _call_gemini(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
) -> str:
    """Call Google Gemini generateContent API."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set (check project-root .env via python-dotenv)"
        )

    chosen = model or _default_model("gemini")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{chosen}:generateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    _wait_rate_limit()
    response = requests.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    _raise_for_status(response, provider="Gemini", model=chosen)
    body = response.json()
    try:
        return body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected Gemini response shape: {body!r}") from exc


def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    """Call Anthropic Messages API."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    model = _default_model("anthropic")
    _wait_rate_limit()
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 1024,
            "temperature": 0,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=LLM_TIMEOUT_SECONDS,
    )
    _raise_for_status(response, provider="Anthropic", model=model)
    body = response.json()
    try:
        return body["content"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected Anthropic response shape: {body!r}") from exc


def _call_openai(system_prompt: str, user_prompt: str) -> str:
    """Call OpenAI Chat Completions API."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    model = _default_model("openai")
    _wait_rate_limit()
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=LLM_TIMEOUT_SECONDS,
    )
    _raise_for_status(response, provider="OpenAI", model=model)
    body = response.json()
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected OpenAI response shape: {body!r}") from exc


def _call_provider(
    system_prompt: str,
    user_prompt: str,
    *,
    model_override: str | None = None,
) -> str:
    """Dispatch to the configured provider."""
    provider = (LLM_PROVIDER or "gemini").strip().lower()
    if provider == "gemini":
        return _call_gemini(system_prompt, user_prompt, model=model_override)
    if provider == "anthropic":
        return _call_anthropic(system_prompt, user_prompt)
    if provider == "openai":
        return _call_openai(system_prompt, user_prompt)
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}")


def _sleep_for_429(retry_delay: float, waited_so_far: float) -> float:
    """Sleep for retryDelay+1s within the remaining 429 budget. Returns new total."""
    remaining = MAX_429_WAIT_SECONDS - waited_so_far
    if remaining <= 0:
        raise RateLimitError(
            f"Exceeded {MAX_429_WAIT_SECONDS:.0f}s total 429 wait",
            retry_delay=0,
        )
    sleep_for = min(retry_delay + 1.0, remaining)
    print(
        f"[llm:429] sleeping {sleep_for:.1f}s "
        f"(retryDelay={retry_delay:.1f}s, waited={waited_so_far:.1f}s)",
        flush=True,
    )
    time.sleep(sleep_for)
    return waited_so_far + sleep_for


def generate_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Call the LLM and return a parsed JSON object.

    Temperature is always 0. Retries up to 3 times with exponential backoff on
    transport/API failures or unparseable JSON. HTTP 429 waits use retryDelay and
    do not consume normal retry attempts (capped at 120s total). Markdown fences
    are stripped before parsing.
    """
    last_error: Exception | None = None
    waited_429 = 0.0
    model_override: str | None = None
    fallback_tried = False
    consecutive_429 = 0
    attempt = 0

    def _maybe_switch_fallback() -> bool:
        """Switch to LLM_FALLBACK_MODEL once for Gemini 429 storms."""
        nonlocal model_override, fallback_tried, waited_429, consecutive_429
        if fallback_tried or not LLM_FALLBACK_MODEL:
            return False
        if (LLM_PROVIDER or "gemini").strip().lower() != "gemini":
            return False
        if model_override == LLM_FALLBACK_MODEL:
            return False
        fallback_tried = True
        model_override = LLM_FALLBACK_MODEL
        waited_429 = 0.0
        consecutive_429 = 0
        print(
            f"[llm:fallback] trying LLM_FALLBACK_MODEL={LLM_FALLBACK_MODEL!r}",
            flush=True,
        )
        return True

    while attempt < MAX_RETRIES:
        try:
            raw = _call_provider(
                system_prompt,
                user_prompt,
                model_override=model_override,
            )
            return _parse_json_text(raw)
        except RateLimitError as exc:
            last_error = exc
            consecutive_429 += 1
            _log_failure("429", exc)
            # After repeated 429s on the main model, try the fallback once.
            if consecutive_429 >= 2 and _maybe_switch_fallback():
                continue
            try:
                waited_429 = _sleep_for_429(exc.retry_delay, waited_429)
            except RateLimitError as budget_exc:
                last_error = budget_exc
                if _maybe_switch_fallback():
                    continue
                raise budget_exc
            # 429 wait does not consume a normal retry attempt
            continue
        except Exception as exc:  # noqa: BLE001 — retry then raise
            last_error = exc
            consecutive_429 = 0
            attempt += 1
            _log_failure(f"attempt_{attempt}/{MAX_RETRIES}", exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))

    assert last_error is not None
    raise last_error

