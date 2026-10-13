"""Thin multi-provider LLM wrapper. Returns parsed JSON only."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from src.config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_API_KEY,
)

LLM_TIMEOUT_SECONDS: int = 30
MAX_RETRIES: int = 3
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _default_model(provider: str) -> str:
    """Pick a sensible default model when LLM_MODEL is unset."""
    if LLM_MODEL:
        return LLM_MODEL
    defaults = {
        "gemini": "gemini-2.0-flash",
        "anthropic": "claude-3-5-haiku-latest",
        "openai": "gpt-4o-mini",
    }
    return defaults.get(provider, "gemini-2.0-flash")


def _strip_fences(text: str) -> str:
    """Remove markdown code fences so raw JSON can be parsed."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = FENCE_RE.sub("", cleaned).strip()
    return cleaned


def _parse_json_text(text: str) -> dict[str, Any]:
    """Parse model output as a JSON object after stripping fences."""
    cleaned = _strip_fences(text)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("LLM response JSON must be an object")
    return data


def _call_gemini(system_prompt: str, user_prompt: str) -> str:
    """Call Google Gemini generateContent API."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    model = _default_model("gemini")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
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
    response.raise_for_status()
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
    response.raise_for_status()
    body = response.json()
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected OpenAI response shape: {body!r}") from exc


def _call_provider(system_prompt: str, user_prompt: str) -> str:
    """Dispatch to the configured provider."""
    provider = (LLM_PROVIDER or "gemini").strip().lower()
    if provider == "gemini":
        return _call_gemini(system_prompt, user_prompt)
    if provider == "anthropic":
        return _call_anthropic(system_prompt, user_prompt)
    if provider == "openai":
        return _call_openai(system_prompt, user_prompt)
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}")


def generate_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Call the LLM and return a parsed JSON object.

    Temperature is always 0. Retries up to 3 times with exponential backoff
    on transport/API failures or unparseable JSON. Markdown fences are stripped
    before parsing.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            raw = _call_provider(system_prompt, user_prompt)
            return _parse_json_text(raw)
        except Exception as exc:  # noqa: BLE001 — retry then raise
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)

    assert last_error is not None
    raise last_error
