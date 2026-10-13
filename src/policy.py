"""Load company policy from data/policy.json and retrieve category rules."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.config import POLICY_PATH

EMPTY_RULES: dict[str, Any] = {
    "rules": [],
    "allowed_promises": [],
    "forbidden": [],
    "sla": "",
}


@lru_cache(maxsize=1)
def load_policy(path: str | None = None) -> dict[str, Any]:
    """Load and return the policy JSON object.

    Works with any file matching the TECH_SPEC section 9 shape.
    """
    policy_path = Path(path) if path else POLICY_PATH
    if not policy_path.exists():
        raise FileNotFoundError(f"Policy file not found: {policy_path}")

    data = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("policy.json must contain a JSON object")
    return data


def reload_policy(path: str | None = None) -> dict[str, Any]:
    """Clear the cache and reload policy (useful after swapping the file)."""
    load_policy.cache_clear()
    return load_policy(path)


def get_rules(category: str, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return rules/allowed_promises/forbidden/sla for a category.

    Unknown categories get an empty ruleset so the agent never invents policy.
    """
    doc = policy if policy is not None else load_policy()
    categories = doc.get("categories") or {}
    if not isinstance(categories, dict):
        return dict(EMPTY_RULES)

    raw = categories.get(category)
    if not isinstance(raw, dict):
        return dict(EMPTY_RULES)

    return {
        "rules": list(raw.get("rules") or []),
        "allowed_promises": list(raw.get("allowed_promises") or []),
        "forbidden": list(raw.get("forbidden") or []),
        "sla": str(raw.get("sla") or ""),
    }


def get_company_name(policy: dict[str, Any] | None = None) -> str:
    """Return company_name from policy."""
    doc = policy if policy is not None else load_policy()
    return str(doc.get("company_name") or "")


def get_signature(policy: dict[str, Any] | None = None) -> str:
    """Return the email signature from policy."""
    doc = policy if policy is not None else load_policy()
    return str(doc.get("signature") or "")


def get_tone(policy: dict[str, Any] | None = None) -> str:
    """Return the preferred tone string from policy."""
    doc = policy if policy is not None else load_policy()
    return str(doc.get("tone") or "polite, empathetic, concise")


def get_escalation_keywords(policy: dict[str, Any] | None = None) -> list[str]:
    """Return escalation keyword list from policy."""
    doc = policy if policy is not None else load_policy()
    raw = doc.get("escalation_keywords") or []
    return [str(k) for k in raw]


def get_refund_threshold(policy: dict[str, Any] | None = None) -> float:
    """Return refund_escalation_threshold (0 if missing)."""
    doc = policy if policy is not None else load_policy()
    try:
        return float(doc.get("refund_escalation_threshold") or 0)
    except (TypeError, ValueError):
        return 0.0
