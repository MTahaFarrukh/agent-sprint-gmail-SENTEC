"""Load and parse Student Helpdesk policy.md into code -> text."""

from __future__ import annotations

import re
from pathlib import Path

CODE_LINE_RE = re.compile(
    r"^(?P<code>[A-Z]{2,}(?:-[A-Z]+)?-\d+)\s*:\s*(?P<text>.+)$",
    re.MULTILINE,
)


def load_policy(path: str | Path) -> tuple[str, dict[str, str]]:
    """Return (full_policy_text, {code: rule_text}).

    Parses every ``CODE-N:`` line (e.g. FEE-1, HOSTEL-3, ESC-6).
    """
    policy_path = Path(path).resolve()
    if not policy_path.exists():
        raise FileNotFoundError(f"Policy not found: {policy_path}")

    text = policy_path.read_text(encoding="utf-8")
    codes: dict[str, str] = {}
    for match in CODE_LINE_RE.finditer(text):
        code = match.group("code").strip().upper()
        rule = match.group("text").strip()
        codes[code] = rule
    return text, codes


def is_valid_code(code: str, codes: dict[str, str]) -> bool:
    """True if code exists in the loaded policy."""
    return code.strip().upper() in codes
