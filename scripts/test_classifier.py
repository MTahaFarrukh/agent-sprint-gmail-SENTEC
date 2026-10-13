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


def main() -> None:
    test_path = TEST_EMAILS_PATH.resolve()
    print(f"Loading test emails from: {test_path}")
    emails = json.loads(test_path.read_text(encoding="utf-8"))
    if not isinstance(emails, list) or not emails:
        print(f"No emails found in {test_path}")
        sys.exit(1)

    print(f"Loaded {len(emails)} emails")
    print()

    headers = ("id", "category", "urgency", "escalate", "confidence", "error")
    widths = [8, 16, 10, 9, 10, 40]
    row_fmt = "  ".join(f"{{:<{w}}}" for w in widths)

    print(row_fmt.format(*headers))
    print(row_fmt.format(*("-" * w for w in widths)))

    for email in emails:
        email_id = str(email.get("id", "?"))
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
                err = (result.escalation_reason or "fallback")[: widths[5]]
            print(
                row_fmt.format(
                    email_id[: widths[0]],
                    result.category[: widths[1]],
                    result.urgency[: widths[2]],
                    "yes" if result.needs_escalation else "no",
                    f"{result.confidence:.2f}",
                    err,
                )
            )
        except Exception as exc:  # noqa: BLE001 — keep the table going
            err = f"{type(exc).__name__}: {exc}"
            print(
                row_fmt.format(
                    email_id[: widths[0]],
                    "ERROR",
                    "-",
                    "yes",
                    "0.00",
                    err[: widths[5]],
                )
            )
            print(f"    ! {err}")


if __name__ == "__main__":
    main()
