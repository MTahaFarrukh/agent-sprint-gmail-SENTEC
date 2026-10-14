"""Deterministic safety net after the LLM. May only ADD escalation, never remove it."""

from __future__ import annotations

import re
from typing import Any

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

# Offices that appear in data/policy.md (do not invent others).
POLICY_OFFICES = (
    "Accounts Office",
    "Registrar's Office",
    "Hostel Warden",
    "Warden",
    "Warden's office",
    "Security",
    "IT Security",
    "Mess Committee",
    "hostel office",
    "Department office",
    "Dean",
    "Department",
    "Department Chairperson",
    "Examination Department",
    "IT Helpdesk",
    "Network Team",
    "Library",
    "Harassment Committee",
    "campus clinic",
    "Student Counseling Cell",
)

POLICY_PLACEHOLDER = "[contact details to be inserted]"
# Bracketed policy citations like [FEE-2] are allowed; other [tokens] are not.
POLICY_CODE_BRACKET_RE = re.compile(r"^\[(FEE|HOSTEL|ACAD|TECH|ESC)-\d+\]$", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(
    r"\[[^\]]+\]|\{[^}]+\}|"
    r"\b(TODO|TBD|PLACEHOLDER|INSERT\s+HERE)\b",
    re.IGNORECASE,
)
PENALTY_AMOUNT_RE = re.compile(
    r"\b(rs\.?\s*\d|rupees?\s*\d|\d+\s*%|late\s+fee\s+of|carry\s+a\s+late\s+fee)\b",
    re.IGNORECASE,
)
PROMISE_OUTSIDE_POLICY_RE = re.compile(
    r"\b(we\s+(will|have|are)\s+(refund|waive|approve|guarantee|ensure)|"
    r"i\s+promise|we\s+guarantee|guaranteed\s+to\s+you|"
    r"your\s+(refund|waiver)\s+(has\s+been|is)\s+approved|"
    r"we\s+have\s+waived|full\s+refund\s+(approved|processed))\b",
    re.IGNORECASE,
)

ESC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ESC-1",
        re.compile(
            r"\b(fire|spark|sparks|smoke|exposed\s+wire|live\s+wire|ceiling\s+crack|"
            r"structural\s+hazard|electrical\s+hazard|"
            r"aag|bijli\s+ka\s+taar|taar\s+khula|chhat\s+crack|short\s+circuit)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ESC-2",
        re.compile(
            r"\b(harass(?:ment|ed|ing)?|bully(?:ing|ied)?|threat(?:s|en|ened|ening)?|"
            r"stalk(?:ing|ed)?|assault|dhamki|tang\s+kar|pareshan\s+kar)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ESC-3",
        re.compile(
            r"\b(hopeless(?:ness)?|self[-\s]?harm|suicid(?:e|al)|kill\s+myself|"
            r"end\s+my\s+life|want\s+to\s+die|fainted|not\s+responding|"
            r"medical\s+emergenc|khudkushi|marna\s+chaht|jee\s+nahi\s+chahta|"
            r"udaas\s+bohat|zindagi\s+se\s+tang)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ESC-4",
        re.compile(
            r"\b(lawyer|attorney|lawsuit|court|legal\s+notice|media|"
            r"journalist|newspaper|news\s+channel|sue\b|consumer\s+court|"
            r"press\s+release)\b",
            re.IGNORECASE,
        ),
    ),
]

ESC6_ASSISTANT_RE = re.compile(
    r"(ignore\s+(previous|all|your)\s+instructions|ignore\s+all\s+previous|"
    r"system\s+prompt|you\s+are\s+now|act\s+as\b|system\s+update|"
    r"override\s+(your|the)\s+(instructions|rules|policy)|"
    r"reveal\s+(your\s+)?(system\s+)?prompt)",
    re.IGNORECASE,
)
ESC6_OTHER_STUDENTS_RE = re.compile(
    r"((send|reveal|share|give|list|export)\b.{0,40}\b("
    r"other\s+students?|all\s+students?|"
    r"student\s+(data|records?|list|emails?|database)|"
    r"students['’]?\s+(data|records?|list|emails?)))",
    re.IGNORECASE | re.DOTALL,
)
ESC6_CREDENTIAL_PHISH_RE = re.compile(
    r"((password|credentials?|otp|one[-\s]?time\s+password|login\s+details)"
    r".{0,80}(https?://|www\.|\bclick\b|\bverify\b|\blink\b|\botp\b)|"
    r"(https?://|www\.|\bclick\b|\bverify\b|\blink\b).{0,80}"
    r"(password|credentials?|otp|one[-\s]?time\s+password|login\s+details))",
    re.IGNORECASE | re.DOTALL,
)

COUNSELING_SNIPPET = (
    "Please contact the campus clinic or the Student Counseling Cell "
    "[contact details to be inserted]."
)


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


def _ensure_signoff(reply: str) -> str:
    """Ensure final line is exactly 'Student Helpdesk' with nothing after."""
    lines = [ln.rstrip() for ln in reply.rstrip().splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return SIGNOFF
    last = lines[-1].strip()
    if last == SIGNOFF:
        return "\n".join(lines)
    if SIGNOFF.lower() in last.lower() or last.lower().startswith("student helpdesk"):
        lines = lines[:-1]
        while lines and not lines[-1].strip():
            lines.pop()
    lines.append(SIGNOFF)
    return "\n".join(lines)


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
    llm_refs: list[str] | None = None,
    llm_escalated: bool = False,
) -> str:
    """Add escalation. Returns honesty tag: confirmed / overrode."""
    llm_refs_u = [r.upper() for r in (llm_refs or [])]
    already = bool(llm_escalated) and esc_code.upper() in llm_refs_u

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

    if already:
        tag = f"confirmed {esc_code}"
    else:
        prev = "true" if llm_escalated else "false"
        tag = f"overrode: escalate {prev}->true ({esc_code})"
    if tag not in fixes:
        fixes.append(tag)
    return tag


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _evidence_in_body(evidence: str, body: str) -> bool:
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
        if (
            "student counseling cell" in reply.lower()
            or "student counselling cell" in reply.lower()
        ):
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


def _invented_offices(reply: str) -> list[str]:
    allowed_lower = {o.lower() for o in POLICY_OFFICES}
    allowed_lower.add("relevant university office")
    allowed_lower.add("student helpdesk")
    found: list[str] = []
    office_re = re.compile(
        r"\b((?:[A-Z][A-Za-z']*(?:\s+[A-Z][A-Za-z']*)*)\s+"
        r"(?:Office|Committee|Department|Team|Cell|Clinic|Warden)|"
        r"Dean|Library|Security)\b"
    )
    for match in office_re.finditer(reply):
        name = match.group(0).strip()
        name_l = name.lower()
        ok = any(name_l == a or name_l in a or a in name_l for a in allowed_lower)
        if not ok and name not in found:
            found.append(name)
    return found


def lookup_policy(code: str, policy_codes: dict[str, str]) -> str | None:
    """Return rule text for a code, or None if unknown."""
    return policy_codes.get(code.strip().upper())


def inspect_draft(draft: str, *, policy_refs: list[str]) -> list[str]:
    """Return draft quality issues (does not mutate).

    Checks: word count, sign-off, next step, ESC-4 arguing, promises outside
    policy, placeholder text other than the policy's own, invented offices.
    """
    issues: list[str] = []
    words = _word_count(draft)
    if words > MAX_REPLY_WORDS:
        issues.append(f"word count {words} exceeds {MAX_REPLY_WORDS}")

    lines = [ln.rstrip() for ln in draft.rstrip().splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[-1].strip() != SIGNOFF:
        issues.append("missing or impure sign-off (must be exactly 'Student Helpdesk')")

    if not any(ln.strip().lower().startswith("next step:") for ln in lines):
        issues.append("missing next step line")

    refs_upper = [r.upper() for r in policy_refs]
    if "ESC-4" in refs_upper and PENALTY_AMOUNT_RE.search(draft):
        issues.append("arguing on ESC-4 (restates penalty/amount)")

    if PROMISE_OUTSIDE_POLICY_RE.search(draft):
        issues.append("promises outside policy")

    for match in PLACEHOLDER_RE.finditer(draft):
        token = match.group(0)
        if token.lower() == POLICY_PLACEHOLDER.lower():
            continue
        if POLICY_CODE_BRACKET_RE.match(token):
            continue
        issues.append(f"placeholder text: {token}")

    for office in _invented_offices(draft):
        issues.append(f"invented office name: {office}")

    joined = draft.rstrip().splitlines()
    for idx, ln in enumerate(joined):
        if ln.strip() == SIGNOFF and idx < len(joined) - 1:
            issues.append("text after sign-off line")
            break

    return issues


def validate_result(
    result: dict[str, Any],
    email: dict[str, Any],
    policy_codes: dict[str, str],
    policy_text: str,  # kept for API compatibility
) -> tuple[dict[str, Any], list[str]]:
    """Validate schema and escalation. May only ADD escalation.

    Honesty tags:
    - "confirmed ESC-x" when LLM already escalated with that code
    - "overrode: escalate false->true (ESC-x)" when validator changed the decision

    Confidence is lowered only when escalate, category, or policy_refs change —
    not when the validator only appends a citation to the reply or confirms.
    """
    del policy_text  # unused; kept for call-site compatibility
    fixes: list[str] = []
    out = dict(result)

    llm_escalate = bool(out.get("escalate", False))
    llm_category = str(out.get("category") or "other").strip().lower()
    llm_refs = [
        str(r).strip().upper()
        for r in (out.get("policy_refs") or [])
        if str(r).strip()
    ]

    category = llm_category
    if category not in CATEGORIES:
        fixes.append(f"overrode: category {category!r}->other")
        category = "other"
    out["category"] = category

    priority = str(out.get("priority") or "medium").strip().lower()
    if priority not in PRIORITIES:
        fixes.append(f"normalized priority {priority!r}->medium")
        priority = "medium"
    out["priority"] = priority

    try:
        confidence = float(out.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
        fixes.append("normalized confidence")
    confidence = max(0.0, min(1.0, confidence))

    out["escalate"] = llm_escalate
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
            fixes.append(f"dropped unknown code {code}")
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
            fixes.append(f"overrode: added missing ref {fallback_code}")
        else:
            was = out["escalate"]
            out["escalate"] = True
            out["escalation_reason"] = _combine_reasons(
                out["escalation_reason"],
                "no valid policy_refs for non-other category",
            )
            if not was:
                fixes.append("overrode: escalate false->true (missing refs)")

    body = str(email.get("body") or "")
    blob = " ".join([str(email.get("subject") or ""), body])

    triggered_esc: set[str] = set()
    for esc_code, pattern in ESC_PATTERNS:
        if pattern.search(blob):
            _force_escalate(
                out,
                esc_code=esc_code,
                reason=f"keyword trigger for {esc_code}",
                fixes=fixes,
                llm_refs=llm_refs,
                llm_escalated=llm_escalate,
            )
            triggered_esc.add(esc_code)

    if _esc6_triggered(blob):
        _force_escalate(
            out,
            esc_code="ESC-6",
            reason="keyword trigger for ESC-6",
            fixes=fixes,
            llm_refs=llm_refs,
            llm_escalated=llm_escalate,
        )
        triggered_esc.add("ESC-6")

    if overdue:
        if _evidence_in_body(overdue_evidence, body):
            _force_escalate(
                out,
                esc_code="ESC-5",
                reason=f"overdue wait evidenced by: {overdue_evidence.strip()[:120]}",
                fixes=fixes,
                llm_refs=llm_refs,
                llm_escalated=llm_escalate,
            )
            triggered_esc.add("ESC-5")
        else:
            out["overdue"] = False
            fixes.append("ignored overdue: evidence not verbatim in body")

    # Confirm LLM ESC codes that the keyword loop did not already tag.
    if llm_escalate:
        for code in llm_refs:
            if not code.startswith("ESC-"):
                continue
            if any(f == f"confirmed {code}" or f"({code})" in f for f in fixes):
                continue
            fixes.append(f"confirmed {code}")

    if "ESC-3" in (out.get("policy_refs") or []):
        before = out["reply_draft"]
        out["reply_draft"] = _ensure_esc3_reply(out["reply_draft"])
        if out["reply_draft"] != before:
            fixes.append("patched ESC-3 counseling wording")

    before_signoff = str(out.get("reply_draft") or "")
    out["reply_draft"] = _ensure_signoff(before_signoff)
    if out["reply_draft"] != before_signoff:
        fixes.append("ensured Student Helpdesk sign-off")

    refs_now = [str(r).upper() for r in (out.get("policy_refs") or [])]
    if any(r in {"ESC-1", "ESC-2", "ESC-3"} for r in refs_now):
        if out.get("priority") != "high":
            out["priority"] = "high"
            fixes.append("priority forced high for critical ESC")

    material_change = (
        bool(out.get("escalate")) != llm_escalate
        or str(out.get("category")) != llm_category
        or [str(r).upper() for r in (out.get("policy_refs") or [])] != llm_refs
    )
    if material_change:
        confidence = min(confidence, max(0.35, confidence - 0.15))
        notes = str(out.get("agent_notes") or "").strip()
        override_tags = [f for f in fixes if f.startswith("overrode")]
        fix_note = (
            "Validator: " + "; ".join(override_tags[:3])
            if override_tags
            else "Validator: material fields changed"
        )
        out["agent_notes"] = (notes + " " + fix_note).strip() if notes else fix_note
    else:
        confirmed = [f for f in fixes if f.startswith("confirmed ")]
        if confirmed:
            notes = str(out.get("agent_notes") or "").strip()
            fix_note = "Validator: " + "; ".join(confirmed[:3])
            out["agent_notes"] = (notes + " " + fix_note).strip() if notes else fix_note

    out["confidence"] = round(confidence, 3)
    # Never remove escalation the LLM already set.
    if llm_escalate and not out["escalate"]:
        out["escalate"] = True
    return out, fixes
