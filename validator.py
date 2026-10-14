"""Deterministic safety net after the LLM. May only ADD escalation, never remove it."""

from __future__ import annotations

import re
from typing import Any, Callable

from llm import regenerate_shorter_reply

CATEGORIES = frozenset(
    {
        "fee",
        "hostel",
        "academic",
        "technical",
        "harassment",
        "wellbeing",
        "suspicious",
        "other",
    }
)
PRIORITIES = frozenset({"low", "medium", "high"})
MAX_REPLY_WORDS = 150
SIGNOFF = "Student Helpdesk"

# Keyword patterns that force escalation (ESC-5 overdue is handled separately).
ESC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ESC-1",
        re.compile(
            r"\b("
            r"fire|spark|sparks|smoke|exposed\s+wire|live\s+wire|ceiling\s+crack|"
            r"structural\s+hazard|electrical\s+hazard|"
            r"aag|bijli\s+ka\s+taar|taar\s+khula|chhat\s+crack|short\s+circuit"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ESC-2",
        re.compile(
            r"\b("
            r"harass(?:ment|ed|ing)?|bully(?:ing|ied)?|threat(?:s|en|ened|ening)?|"
            r"stalk(?:ing|ed)?|assault|"
            r"dhamki|tang\s+kar|pareshan\s+kar"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ESC-3",
        re.compile(
            r"\b("
            r"hopeless(?:ness)?|self[-\s]?harm|suicid(?:e|al)|kill\s+myself|"
            r"end\s+my\s+life|want\s+to\s+die|fainted|not\s+responding|"
            r"medical\s+emergenc|"
            r"khudkushi|marna\s+chaht|jee\s+nahi\s+chahta|udaas\s+bohat|"
            r"zindagi\s+se\s+tang"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ESC-4",
        re.compile(
            r"\b("
            r"lawyer|attorney|lawsuit|court|legal\s+notice|media|"
            r"journalist|newspaper|news\s+channel|sue\b|"
            r"consumer\s+court|press\s+release"
            r")\b",
            re.IGNORECASE,
        ),
    ),
]

# ESC-6: assistant-targeted instructions, other students' data, or credential+phish combo.
# Own forgotten/locked password is NOT suspicious.
ESC6_ASSISTANT_RE = re.compile(
    r"("
    r"ignore\s+(previous|all|your)\s+instructions|"
    r"ignore\s+all\s+previous|"
    r"system\s+prompt|"
    r"you\s+are\s+now|"
    r"act\s+as\b|"
    r"system\s+update|"
    r"override\s+(your|the)\s+(instructions|rules|policy)|"
    r"reveal\s+(your\s+)?(system\s+)?prompt"
    r")",
    re.IGNORECASE,
)
ESC6_OTHER_STUDENTS_RE = re.compile(
    r"("
    r"(send|reveal|share|give|list|export)\b.{0,40}\b("
    r"other\s+students?|"
    r"all\s+students?|"
    r"student\s+(data|records?|list|emails?|database)|"
    r"students['’]?\s+(data|records?|list|emails?)"
    r")"
    r")",
    re.IGNORECASE | re.DOTALL,
)
ESC6_CREDENTIAL_PHISH_RE = re.compile(
    r"("
    r"(password|credentials?|otp|one[-\s]?time\s+password|login\s+details)"
    r".{0,80}"
    r"(https?://|www\.|\bclick\b|\bverify\b|\blink\b|\botp\b)"
    r"|"
    r"(https?://|www\.|\bclick\b|\bverify\b|\blink\b)"
    r".{0,80}"
    r"(password|credentials?|otp|one[-\s]?time\s+password|login\s+details)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

COUNSELING_SNIPPET = (
    "Please contact the campus clinic or the Student Counseling Cell "
    "[contact details to be inserted]."
)


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


def _ensure_signoff(reply: str) -> str:
    text = reply.rstrip()
    if SIGNOFF.lower() not in text.lower():
        text = f"{text}\n\n{SIGNOFF}"
    return text


def _trim_words(text: str, max_words: int = MAX_REPLY_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = " ".join(words[: max_words - 2])
    return _ensure_signoff(trimmed)


def _combine_reasons(existing: str, new: str) -> str:
    existing = (existing or "").strip()
    new = new.strip()
    if not existing:
        return new
    if new.lower() in existing.lower():
        return existing
    return f"{existing}; {new}"


def _add_ref(refs: list[str], code: str) -> None:
    code = code.upper()
    if code not in refs:
        refs.append(code)


def _force_escalate(
    result: dict[str, Any],
    *,
    esc_code: str,
    reason: str,
    fixes: list[str],
) -> None:
    """Add escalation (never clears an existing escalate=true)."""
    result["escalate"] = True
    result["escalation_reason"] = _combine_reasons(
        str(result.get("escalation_reason") or ""),
        reason,
    )
    refs = list(result.get("policy_refs") or [])
    _add_ref(refs, esc_code)
    result["policy_refs"] = refs
    if esc_code in {"ESC-1", "ESC-2", "ESC-3"}:
        result["priority"] = "high"
    fixes.append(f"forced {esc_code}")


def _normalize_for_match(text: str) -> str:
    """Case-fold and collapse whitespace for evidence checks."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _evidence_in_body(evidence: str, body: str) -> bool:
    """True if evidence is a verbatim substring of body (case/whitespace-insensitive)."""
    ev = _normalize_for_match(evidence or "")
    if not ev:
        return False
    return ev in _normalize_for_match(body or "")


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _esc6_triggered(blob: str) -> bool:
    """Suspicious / prompt-injection / credential-phish — not own password lockouts."""
    return bool(
        ESC6_ASSISTANT_RE.search(blob)
        or ESC6_OTHER_STUDENTS_RE.search(blob)
        or ESC6_CREDENTIAL_PHISH_RE.search(blob)
    )


def _ensure_esc3_reply(reply: str) -> str:
    lower = reply.lower()
    needs = (
        "counseling" not in lower
        and "campus clinic" not in lower
        and "counselling" not in lower
    )
    if needs:
        reply = reply.rstrip() + "\n\n" + COUNSELING_SNIPPET
    if "[contact details to be inserted]" not in reply.lower():
        if "student counseling cell" in reply.lower() or "student counselling cell" in reply.lower():
            reply = re.sub(
                r"(Student Counse[l]+ing Cell)",
                r"\1 [contact details to be inserted]",
                reply,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            reply = reply.rstrip() + " " + COUNSELING_SNIPPET
    return _ensure_signoff(reply)


def validate_result(
    result: dict[str, Any],
    email: dict[str, Any],
    policy_codes: dict[str, str],
    policy_text: str,
    *,
    regenerate_fn: Callable[..., str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate and patch one triage result. Returns (result, list_of_fixes)."""
    fixes: list[str] = []
    out = dict(result)

    # --- normalize core fields ---
    category = str(out.get("category") or "other").strip().lower()
    if category not in CATEGORIES:
        fixes.append(f"invalid category {category!r}->other")
        category = "other"
    out["category"] = category

    priority = str(out.get("priority") or "medium").strip().lower()
    if priority not in PRIORITIES:
        fixes.append(f"invalid priority {priority!r}->medium")
        priority = "medium"
    out["priority"] = priority

    try:
        confidence = float(out.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
        fixes.append("bad confidence")
    confidence = max(0.0, min(1.0, confidence))

    escalate = bool(out.get("escalate", False))
    out["escalate"] = escalate
    out["escalation_reason"] = str(out.get("escalation_reason") or "")
    out["reply_draft"] = str(out.get("reply_draft") or "")
    out["agent_notes"] = str(out.get("agent_notes") or "")
    out["email_id"] = str(
        out.get("email_id") or email.get("id") or email.get("email_id") or "UNKNOWN"
    )

    overdue = _coerce_bool(out.get("overdue", False))
    overdue_evidence = str(out.get("overdue_evidence") or "")
    out["overdue"] = overdue
    out["overdue_evidence"] = overdue_evidence

    # --- policy_refs: drop unknowns ---
    raw_refs = out.get("policy_refs") or []
    if not isinstance(raw_refs, list):
        raw_refs = []
        fixes.append("policy_refs not a list")
    cleaned_refs: list[str] = []
    for ref in raw_refs:
        code = str(ref).strip().upper()
        if code in policy_codes:
            if code not in cleaned_refs:
                cleaned_refs.append(code)
        else:
            fixes.append(f"dropped invalid ref {code}")
    out["policy_refs"] = cleaned_refs

    if category != "other" and not cleaned_refs:
        prefix_map = {
            "fee": "FEE",
            "hostel": "HOSTEL",
            "academic": "ACAD",
            "technical": "TECH",
            "harassment": "ESC",
            "wellbeing": "ESC",
            "suspicious": "ESC",
        }
        prefix = prefix_map.get(category, "")
        fallback_code = next(
            (c for c in sorted(policy_codes) if c.startswith(prefix + "-")),
            "",
        )
        if fallback_code:
            cleaned_refs.append(fallback_code)
            out["policy_refs"] = cleaned_refs
            fixes.append(f"added missing ref {fallback_code}")
        else:
            out["escalate"] = True
            out["escalation_reason"] = _combine_reasons(
                out["escalation_reason"],
                "no valid policy_refs for non-other category",
            )
            fixes.append("escalated: missing policy_refs")

    # Reply must cite at least one valid code when category is not other
    reply = out["reply_draft"]
    if category != "other" and cleaned_refs:
        non_esc_refs = [c for c in cleaned_refs if not c.startswith("ESC-")]
        cite_pool = non_esc_refs or cleaned_refs
        cited = any(code in reply for code in cite_pool)
        if not cited:
            reply = f"{reply.rstrip()} (Policy {cite_pool[0]})."
            fixes.append(f"injected policy cite {cite_pool[0]}")
            out["reply_draft"] = reply

    body = str(email.get("body") or "")
    blob = " ".join(
        [
            str(email.get("subject") or ""),
            body,
        ]
    )

    # --- keyword / Roman Urdu escalation patterns (not ESC-5/ESC-6) ---
    for esc_code, pattern in ESC_PATTERNS:
        if pattern.search(blob):
            _force_escalate(
                out,
                esc_code=esc_code,
                reason=f"keyword trigger for {esc_code}",
                fixes=fixes,
            )

    # --- ESC-6 (tightened; no bare "password") ---
    if _esc6_triggered(blob):
        _force_escalate(
            out,
            esc_code="ESC-6",
            reason="keyword trigger for ESC-6",
            fixes=fixes,
        )

    # --- ESC-5 overdue: only if LLM overdue + evidence is verbatim in body ---
    if overdue:
        if _evidence_in_body(overdue_evidence, body):
            _force_escalate(
                out,
                esc_code="ESC-5",
                reason=f"overdue wait evidenced by: {overdue_evidence.strip()[:120]}",
                fixes=fixes,
            )
        else:
            out["overdue"] = False
            fixes.append("ignored overdue: evidence not verbatim in body")

    # ESC-3 reply content requirements
    if "ESC-3" in (out.get("policy_refs") or []):
        before = out["reply_draft"]
        out["reply_draft"] = _ensure_esc3_reply(out["reply_draft"])
        if out["reply_draft"] != before:
            fixes.append("ensured ESC-3 counseling wording")

    # --- reply length ---
    reply = str(out.get("reply_draft") or "")
    if _word_count(reply) > MAX_REPLY_WORDS:
        regen = regenerate_fn or regenerate_shorter_reply
        try:
            reply = regen(
                email,
                policy_text,
                reply,
                list(out.get("policy_refs") or []),
            )
            fixes.append("regenerated long reply")
        except Exception:  # noqa: BLE001 — fall through to trim
            fixes.append("regen failed; trimming")
        if _word_count(reply) > MAX_REPLY_WORDS:
            reply = _trim_words(reply)
            fixes.append("trimmed reply to 150 words")
        out["reply_draft"] = reply

    before_signoff = str(out.get("reply_draft") or "")
    out["reply_draft"] = _ensure_signoff(before_signoff)
    if out["reply_draft"] != before_signoff and "sign-off" not in " ".join(fixes).lower():
        fixes.append("ensured Student Helpdesk sign-off")

    # ESC-1/2/3 force high priority (again after all adds)
    refs_now = [str(r).upper() for r in (out.get("policy_refs") or [])]
    if any(r in {"ESC-1", "ESC-2", "ESC-3"} for r in refs_now):
        if out.get("priority") != "high":
            out["priority"] = "high"
            fixes.append("priority forced high for critical ESC")

    # Lower confidence when validator fixed something
    if fixes:
        confidence = min(confidence, max(0.35, confidence - 0.15 * min(len(fixes), 3)))
        notes = str(out.get("agent_notes") or "").strip()
        fix_note = "Validator: " + "; ".join(fixes[:4])
        out["agent_notes"] = (notes + " " + fix_note).strip() if notes else fix_note

    out["confidence"] = round(confidence, 3)
    # Never remove escalation
    if escalate and not out["escalate"]:
        out["escalate"] = True
    return out, fixes
