"""Run the classifier on data/test_emails.json and print a summary table.

Usage (from any directory, venv active):
    python scripts/test_classifier.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.classifier import classify
from src.config import TEST_EMAILS_PATH


def _trunc(text: str, width: int) -> str:
    """Truncate text to fit a column width."""
    text = text.replace("\n", " ").strip()
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def main() -> None:
    test_path = TEST_EMAILS_PATH.resolve()
    print(f"Loading test emails from: {test_path}")
    emails = json.loads(test_path.read_text(encoding="utf-8"))
    if not isinstance(emails, list) or not emails:
        print(f"No emails found in {test_path}")
        sys.exit(1)

    print(f"Loaded {len(emails)} emails")
    print()

    headers = (
        "id",
        "subject",
        "category",
        "urgency",
        "language",
        "escalate",
        "unusual",
        "confidence",
        "summary",
        "error",
    )
    widths = [8, 35, 16, 10, 9, 9, 8, 10, 50, 30]
    row_fmt = "  ".join(f"{{:<{w}}}" for w in widths)

    print(row_fmt.format(*headers))
    print(row_fmt.format(*("-" * w for w in widths)))

    unusual_count = 0
    escalated_count = 0

    for email in emails:
        email_id = str(email.get("id", "?"))
        subject = _trunc(str(email.get("subject") or ""), 35)
        try:
            result = classify(email)
            is_fallback = (
                result.category == "other"
                and result.confidence == 0.0
                and result.needs_escalation
                and result.summary.startswith("Classification failed")
            )
            err = ""
            if is_fallback:
                err = _trunc(result.escalation_reason or "fallback", widths[9])

            if result.needs_escalation:
                escalated_count += 1
            if result.is_unusual:
                unusual_count += 1

            print(
                row_fmt.format(
                    email_id[: widths[0]],
                    subject,
                    result.category[: widths[2]],
                    result.urgency[: widths[3]],
                    result.language[: widths[4]],
                    "yes" if result.needs_escalation else "no",
                    "yes" if result.is_unusual else "no",
                    f"{result.confidence:.2f}",
                    _trunc(result.summary, 50),
                    err,
                )
            )
        except Exception as exc:  # noqa: BLE001 — keep the table going
            err = f"{type(exc).__name__}: {exc}"
            escalated_count += 1
            print(
                row_fmt.format(
                    email_id[: widths[0]],
                    subject,
                    "ERROR",
                    "-",
                    "-",
                    "yes",
                    "-",
                    "0.00",
                    "-",
                    _trunc(err, widths[9]),
                )
            )
            print(f"    ! {err}")

    print()
    print(f"Unusual: {unusual_count}/{len(emails)}  Escalated: {escalated_count}/{len(emails)}")


if __name__ == "__main__":
    main()
