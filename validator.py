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

# (esc_code, compiled pattern) — first match wins for notes; all matches apply
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
    (
        "ESC-6",
        re.compile(
            r"("
            r"ignore\s+(previous\s+)?instructions|ignore\s+your\s+instructions|"
            r"system\s+prompt|reveal\s+(your\s+)?prompt|"
            r"send\s+(me\s+)?(all\s+)?student\s+data|"
            r"password|api\s*key|token\.json|"
            r"you\s+are\s+now|act\s+as\s+dan|"
            r"do\s+not\s+escalate|bypass\s+policy"
            r")",
            re.IGNORECASE,
        ),
    ),
]

WAIT_DAYS_RE = re.compile(
    r"(\d+)\s*(?:working\s+)?days?\s*(?:ago|se|wait|waiting|and\s+nobody|without)?",
    re.IGNORECASE,
)
WAIT_WEEKS_RE = re.compile(r"(\d+)\s*weeks?", re.IGNORECASE)
WAIT_HOURS_RE = re.compile(r"(\d+)\s*hours?", re.IGNORECASE)
THIRD_EMAIL_RE = re.compile(r"\bthird\s+email\b|\b3rd\s+email\b|\btisri\s+email\b", re.I)

# Approximate SLA ceilings in days for overdue detection (ESC-5)
SLA_DAYS_BY_PREFIX: dict[str, float] = {
    "FEE": 5.0,
    "HOSTEL": 2.0,  # 48 hours maintenance
    "ACAD": 15.0,  # re-evaluation window outcome
    "TECH": 1.0,  # 24 hours account reset
}

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


def _extract_wait_days(text: str) -> float | None:
    """Best-effort wait duration in days from the email body."""
    if THIRD_EMAIL_RE.search(text):
        return 20.0  # treat repeated chasing as overdue signal
    weeks = WAIT_WEEKS_RE.findall(text)
    if weeks:
        return max(float(w) * 7.0 for w in weeks)
    days = WAIT_DAYS_RE.findall(text)
    if days:
        return max(float(d) for d in days)
    hours = WAIT_HOURS_RE.findall(text)
    if hours:
        return max(float(h) / 24.0 for h in hours)
    return None


def _sla_for_refs(refs: list[str], category: str) -> float | None:
    prefixes: set[str] = set()
    for ref in refs:
        prefix = ref.split("-")[0].upper()
        if prefix in SLA_DAYS_BY_PREFIX:
            prefixes.add(prefix)
    cat_map = {
        "fee": "FEE",
        "hostel": "HOSTEL",
        "academic": "ACAD",
        "technical": "TECH",
    }
    if category in cat_map:
        prefixes.add(cat_map[category])
    if not prefixes:
        return None
    return max(SLA_DAYS_BY_PREFIX[p] for p in prefixes if p in SLA_DAYS_BY_PREFIX)


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
        # Prefer a category-prefix code if any exist
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
            _force_escalate(
                out,
                esc_code="ESC-5",
                reason="no valid policy_refs for non-other category",
                fixes=fixes,
            )

    # Reply must cite at least one valid code when category is not other
    reply = out["reply_draft"]
    if category != "other" and cleaned_refs:
        cited = any(code in reply for code in cleaned_refs)
        if not cited:
            reply = f"{reply.rstrip()} (Policy {cleaned_refs[0]})."
            fixes.append(f"injected policy cite {cleaned_refs[0]}")
            out["reply_draft"] = reply

    # --- keyword / Roman Urdu escalation patterns ---
    blob = " ".join(
        [
            str(email.get("subject") or ""),
            str(email.get("body") or ""),
        ]
    )
    for esc_code, pattern in ESC_PATTERNS:
        if pattern.search(blob):
            _force_escalate(
                out,
                esc_code=esc_code,
                reason=f"keyword trigger for {esc_code}",
                fixes=fixes,
            )

    # --- overdue vs policy response time ---
    wait_days = _extract_wait_days(blob)
    if wait_days is not None:
        sla = _sla_for_refs(list(out.get("policy_refs") or []), category)
        if sla is not None and wait_days > sla:
            _force_escalate(
                out,
                esc_code="ESC-5",
                reason=(
                    f"stated wait ~{wait_days:.0f} days exceeds policy response "
                    f"time (~{sla:.0f} days)"
                ),
                fixes=fixes,
            )

    # ESC-3 reply content requirements
    if "ESC-3" in (out.get("policy_refs") or []) or out.get("category") == "wellbeing":
        if any("ESC-3" in f or "ESC-3" in str(out.get("escalation_reason")) for f in fixes) or (
            "ESC-3" in (out.get("policy_refs") or [])
        ):
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
