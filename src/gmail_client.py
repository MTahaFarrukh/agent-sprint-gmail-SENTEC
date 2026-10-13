"""Gmail OAuth client: fetch unread mail, create drafts, manage labels.

Never sends email. Uses gmail.modify only (no gmail.send).
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from email.mime.text import MIMEText
from html import unescape
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from src.config import (
    CREDENTIALS_PATH,
    GMAIL_QUERY,
    GMAIL_SCOPES,
    LABEL_ESCALATED,
    LABEL_NEEDS_REVIEW,
    LABEL_PROCESSED,
    TOKEN_PATH,
)


@dataclass
class ParsedEmail:
    """Normalized fields from a Gmail message."""

    message_id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    date: str
    rfc_message_id: str
    has_attachments: bool
    label_ids: list[str]


def get_gmail_service() -> Resource:
    """Authenticate with OAuth and return a Gmail API service.

    Opens a browser on first run; refreshes or reuses token.json afterward.
    """
    creds: Credentials | None = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Missing {CREDENTIALS_PATH}. Download OAuth client "
                    "credentials from Google Cloud Console and place them there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH),
                GMAIL_SCOPES,
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def _header_map(headers: list[dict[str, str]]) -> dict[str, str]:
    """Lowercase header name -> value."""
    return {h.get("name", "").lower(): h.get("value", "") for h in headers}


def _strip_html(html: str) -> str:
    """Remove tags and unescape entities for a plain-text fallback."""
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _decode_b64url(data: str) -> str:
    """Decode Gmail's URL-safe base64 body payload."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode(
        "utf-8",
        errors="replace",
    )


def _walk_parts(payload: dict[str, Any]) -> tuple[str | None, str | None, bool]:
    """Walk MIME tree; return (text/plain, text/html, has_attachments)."""
    plain: str | None = None
    html: str | None = None
    has_attachments = False

    mime = payload.get("mimeType", "")
    body = payload.get("body") or {}
    filename = payload.get("filename") or ""

    if filename or (body.get("attachmentId") and not mime.startswith("text/")):
        has_attachments = True

    data = body.get("data")
    if data and mime == "text/plain" and plain is None:
        plain = _decode_b64url(data)
    elif data and mime == "text/html" and html is None:
        html = _decode_b64url(data)

    for part in payload.get("parts") or []:
        p_plain, p_html, p_att = _walk_parts(part)
        if p_plain and plain is None:
            plain = p_plain
        if p_html and html is None:
            html = p_html
        has_attachments = has_attachments or p_att

    return plain, html, has_attachments


def extract_body(payload: dict[str, Any]) -> tuple[str, bool]:
    """Prefer text/plain; fall back to stripped HTML. Also detect attachments."""
    plain, html, has_attachments = _walk_parts(payload)

    # Single-part messages sometimes put body on the root payload only
    if plain is None and html is None:
        data = (payload.get("body") or {}).get("data")
        mime = payload.get("mimeType", "")
        if data:
            decoded = _decode_b64url(data)
            if mime == "text/html":
                html = decoded
            else:
                plain = decoded

    if plain:
        return plain.strip(), has_attachments
    if html:
        return _strip_html(html), has_attachments
    return "", has_attachments


def parse_message(raw: dict[str, Any]) -> ParsedEmail:
    """Parse a Gmail messages.get payload into ParsedEmail."""
    payload = raw.get("payload") or {}
    headers = _header_map(payload.get("headers") or [])
    body, has_attachments = extract_body(payload)

    return ParsedEmail(
        message_id=raw.get("id", ""),
        thread_id=raw.get("threadId", ""),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        body=body,
        date=headers.get("date", ""),
        rfc_message_id=headers.get("message-id", ""),
        has_attachments=has_attachments,
        label_ids=list(raw.get("labelIds") or []),
    )


def fetch_unread_emails(
    service: Resource,
    *,
    query: str | None = None,
    max_results: int = 20,
) -> list[ParsedEmail]:
    """List messages matching query (default: unread inbox, not AGENT_PROCESSED)."""
    q = query if query is not None else f"is:unread {GMAIL_QUERY}"
    response = (
        service.users()
        .messages()
        .list(userId="me", q=q, maxResults=max_results)
        .execute()
    )
    messages = response.get("messages") or []
    parsed: list[ParsedEmail] = []

    for meta in messages:
        raw = (
            service.users()
            .messages()
            .get(userId="me", id=meta["id"], format="full")
            .execute()
        )
        parsed.append(parse_message(raw))

    return parsed


def _ensure_label(service: Resource, label_name: str) -> str:
    """Return label id, creating the user label if it does not exist."""
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels") or []:
        if label.get("name") == label_name:
            return label["id"]

    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def add_label(service: Resource, message_id: str, label_name: str) -> None:
    """Add a user label to a message (creates the label if needed)."""
    label_id = _ensure_label(service, label_name)
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id]},
    ).execute()


def remove_label(service: Resource, message_id: str, label_name: str) -> None:
    """Remove a user label from a message if the label exists."""
    results = service.users().labels().list(userId="me").execute()
    label_id: str | None = None
    for label in results.get("labels") or []:
        if label.get("name") == label_name:
            label_id = label["id"]
            break
    if not label_id:
        return
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": [label_id]},
    ).execute()


def mark_processed(service: Resource, message_id: str) -> None:
    """Apply AGENT_PROCESSED and remove UNREAD."""
    label_id = _ensure_label(service, LABEL_PROCESSED)
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": ["UNREAD"]},
    ).execute()


def mark_escalated(service: Resource, message_id: str) -> None:
    """Apply ESCALATED label."""
    add_label(service, message_id, LABEL_ESCALATED)


def mark_needs_review(service: Resource, message_id: str) -> None:
    """Apply NEEDS_REVIEW label."""
    add_label(service, message_id, LABEL_NEEDS_REVIEW)


def create_draft(
    service: Resource,
    *,
    to: str,
    subject: str,
    body: str,
    thread_id: str,
    in_reply_to: str = "",
    references: str = "",
) -> str:
    """Create a draft reply in the same thread. Returns draft id.

    Does not send. Sets threadId and reply headers when provided.
    """
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    message = MIMEText(body, _charset="utf-8")
    message["To"] = to
    message["Subject"] = reply_subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    refs = references or in_reply_to
    if refs:
        message["References"] = refs

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    draft_body: dict[str, Any] = {"message": {"raw": raw, "threadId": thread_id}}

    draft = (
        service.users()
        .drafts()
        .create(userId="me", body=draft_body)
        .execute()
    )
    return draft.get("id", "")
