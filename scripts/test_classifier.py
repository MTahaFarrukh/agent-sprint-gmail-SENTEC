"""Run the classifier on data/test_emails.json and print a summary table.

Usage (from project root, venv active):
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

TEST_PATH = ROOT / "data" / "test_emails.json"


def main() -> None:
    emails = json.loads(TEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(emails, list) or not emails:
        print(f"No emails found in {TEST_PATH}")
        sys.exit(1)

    headers = ("id", "category", "urgency", "escalate", "confidence")
    widths = [8, 16, 10, 9, 10]
    row_fmt = "  ".join(f"{{:<{w}}}" for w in widths)

    print(row_fmt.format(*headers))
    print(row_fmt.format(*("-" * w for w in widths)))

    for email in emails:
        email_id = str(email.get("id", "?"))
        try:
            result = classify(email)
            print(
                row_fmt.format(
                    email_id[: widths[0]],
                    result.category[: widths[1]],
                    result.urgency[: widths[2]],
                    "yes" if result.needs_escalation else "no",
                    f"{result.confidence:.2f}",
                )
            )
        except Exception as exc:  # noqa: BLE001 — keep the table going
            print(
                row_fmt.format(
                    email_id[: widths[0]],
                    "ERROR",
                    "-",
                    "yes",
                    "0.00",
                )
            )
            print(f"    ! {exc}")


if __name__ == "__main__":
    main()
