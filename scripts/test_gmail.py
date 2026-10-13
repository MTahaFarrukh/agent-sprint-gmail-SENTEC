"""Smoke-test Gmail client: fetch up to 3 emails and create one draft.

Usage (from project root, venv active):
    python scripts/test_gmail.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/test_gmail.py` from project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.gmail_client import create_draft, fetch_unread_emails, get_gmail_service


def main() -> None:
    print("Authenticating with Gmail...")
    service = get_gmail_service()

    print("Fetching up to 3 unread emails...")
    emails = fetch_unread_emails(service, max_results=3)

    if not emails:
        print("No unread emails found. Send yourself a test message and retry.")
        return

    for i, email in enumerate(emails, start=1):
        snippet = (email.body[:120] + "…") if len(email.body) > 120 else email.body
        print(f"\n--- Email {i} ---")
        print(f"  id:      {email.message_id}")
        print(f"  thread:  {email.thread_id}")
        print(f"  from:    {email.sender}")
        print(f"  subject: {email.subject}")
        print(f"  date:    {email.date}")
        print(f"  attach:  {email.has_attachments}")
        print(f"  body:    {snippet!r}")

    target = emails[0]
    print(f"\nCreating a test draft in thread {target.thread_id}...")
    draft_id = create_draft(
        service,
        to=target.sender,
        subject=target.subject,
        body=(
            "This is a test draft from the Gmail agent sprint setup.\n\n"
            "Nothing was sent — drafts only.\n"
        ),
        thread_id=target.thread_id,
        in_reply_to=target.rfc_message_id,
        references=target.rfc_message_id,
    )
    print(f"Draft created. draft_id={draft_id}")
    print("Check Gmail → Drafts to confirm.")


if __name__ == "__main__":
    main()
