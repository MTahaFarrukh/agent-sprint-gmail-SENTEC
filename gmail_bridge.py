"""Real Gmail mode: fetch inbox mail → helpdesk triage → create drafts only.

Never sends email. Never requests gmail.send.
Uses the same agent loop as agent.py (PLAN → ACTION → OBSERVATION → DECISION).

Usage:
    python gmail_bridge.py --status
    python gmail_bridge.py --preview --limit 5
    python gmail_bridge.py --limit 3
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GMAIL_OUTBOX_PATH = ROOT / "data" / "gmail_outbox.json"
GMAIL_LOG_PATH = ROOT / "logs" / "gmail_agent.log"
GMAIL_TRACE_PATH = ROOT / "logs" / "gmail_trace.jsonl"
POLICY_PATH = ROOT / "data" / "policy.md"

FROM_RE = re.compile(r"<([^>]+)>")


def _setup_logging(log_path: Path) -> logging.Logger:
    """File + console logger for Gmail runs."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("gmail_bridge")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def parse_sender(header: str) -> tuple[str, str]:
    """Return (display_name, email) from a From header."""
    name, addr = parseaddr(header or "")
    addr = (addr or "").strip()
    name = (name or "").strip()
    if not addr:
        match = FROM_RE.search(header or "")
        if match:
            addr = match.group(1).strip()
        else:
            addr = (header or "").strip()
    if not name:
        name = addr.split("@")[0] if "@" in addr else (addr or "Student")
    return name, addr


def connected_gmail_address() -> str:
    """Return the Gmail address for the current token, or '' if unavailable."""
    try:
        service = connect_gmail()
        profile = service.users().getProfile(userId="me").execute()
        return str(profile.get("emailAddress") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def gmail_status(*, resolve_email: bool = True) -> dict[str, Any]:
    """Report OAuth file presence and whether a refreshable token exists."""
    from src.config import CREDENTIALS_PATH, GMAIL_QUERY, GMAIL_SCOPES, TOKEN_PATH

    creds_ok = CREDENTIALS_PATH.is_file()
    token_ok = TOKEN_PATH.is_file()
    token_valid = False
    token_detail = "missing"
    if token_ok:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_file(
                str(TOKEN_PATH), GMAIL_SCOPES
            )
            if creds and creds.valid:
                token_valid = True
                token_detail = "valid"
            elif creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
                token_valid = True
                token_detail = "refreshed"
            else:
                token_detail = "expired_needs_reauth"
        except Exception as exc:  # noqa: BLE001
            token_detail = f"error:{type(exc).__name__}"

    email = ""
    if resolve_email and creds_ok and token_valid:
        email = connected_gmail_address()

    return {
        "credentials_path": str(CREDENTIALS_PATH),
        "token_path": str(TOKEN_PATH),
        "credentials_present": creds_ok,
        "token_present": token_ok,
        "token_valid": token_valid,
        "token_detail": token_detail,
        "connected_email": email,
        "scopes": list(GMAIL_SCOPES),
        "default_query": GMAIL_QUERY,
        "ready": creds_ok and token_valid,
        "can_connect": creds_ok,
    }


def connect_gmail() -> Any:
    """Open browser OAuth if needed; return Gmail API service."""
    from src.gmail_client import get_gmail_service

    return get_gmail_service()


def parsed_to_agent_email(parsed: Any, index: int) -> dict[str, Any]:
    """Map Gmail ParsedEmail → agent inbox-shaped dict."""
    name, addr = parse_sender(getattr(parsed, "sender", "") or "")
    short_id = f"G{index:03d}"
    mid = str(getattr(parsed, "message_id", "") or "")
    if mid:
        short_id = f"G{mid[-8:].upper()}"
    return {
        "id": short_id,
        "from_name": name,
        "from_email": addr,
        "subject": str(getattr(parsed, "subject", "") or ""),
        "body": str(getattr(parsed, "body", "") or ""),
        "received_at": str(getattr(parsed, "date", "") or ""),
        "_gmail_message_id": mid,
        "_gmail_thread_id": str(getattr(parsed, "thread_id", "") or ""),
        "_rfc_message_id": str(getattr(parsed, "rfc_message_id", "") or ""),
        "_gmail_sender_raw": str(getattr(parsed, "sender", "") or ""),
    }


def preview_inbox(
    *,
    limit: int = 10,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch matching messages without triaging or drafting."""
    from src.gmail_client import fetch_unread_emails

    service = connect_gmail()
    parsed_list = fetch_unread_emails(
        service,
        query=query,
        max_results=max(1, min(limit, 50)),
    )
    return [parsed_to_agent_email(p, i) for i, p in enumerate(parsed_list, start=1)]


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def process_gmail_batch(
    *,
    limit: int = 5,
    query: str | None = None,
    dry_run: bool = False,
    out_path: Path | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Fetch → triage with agent → create draft replies (unless dry_run).

    Returns a summary dict with results list for the dashboard.
    """
    from agent import HOLDING_REPLY, TraceLogger, process_email
    from policy import load_policy
    from src.gmail_client import (
        create_draft,
        fetch_unread_emails,
        mark_escalated,
        mark_needs_review,
        mark_processed,
    )

    log = logger or _setup_logging(GMAIL_LOG_PATH)
    out = out_path or GMAIL_OUTBOX_PATH
    started = datetime.now(timezone.utc).isoformat()
    log.info("gmail_run_start at=%s limit=%d dry_run=%s", started, limit, dry_run)

    status = gmail_status()
    if not status["credentials_present"]:
        raise FileNotFoundError(
            f"Missing credentials.json at {status['credentials_path']}. "
            "Download OAuth Desktop credentials from Google Cloud Console."
        )

    policy_text, policy_codes = load_policy(POLICY_PATH)
    service = connect_gmail()
    parsed_list = fetch_unread_emails(
        service,
        query=query,
        max_results=max(1, min(limit, 50)),
    )
    log.info("gmail_fetched count=%d", len(parsed_list))

    trace = TraceLogger(GMAIL_TRACE_PATH)
    results: list[dict[str, Any]] = []

    for index, parsed in enumerate(parsed_list, start=1):
        email = parsed_to_agent_email(parsed, index)
        email_id = str(email["id"])
        gmail_mid = str(email.get("_gmail_message_id") or "")
        thread_id = str(email.get("_gmail_thread_id") or "")
        rfc_id = str(email.get("_rfc_message_id") or "")
        to_addr = str(email.get("from_email") or "")

        row: dict[str, Any] = {
            "email_id": email_id,
            "gmail_message_id": gmail_mid,
            "gmail_thread_id": thread_id,
            "from_name": email.get("from_name"),
            "from_email": to_addr,
            "subject": email.get("subject"),
            "received_at": email.get("received_at"),
            "draft_id": "",
            "error": "",
            "dry_run": dry_run,
        }

        try:
            # agent.process_email returns reply_draft / escalation_reason
            triage = process_email(
                email,
                policy_text,
                policy_codes,
                log,
                trace,
                demo_failures=False,
                email_index=index,
            )
            reply_text = str(
                triage.get("reply_draft")
                or triage.get("draft_reply")
                or ""
            ).strip() or HOLDING_REPLY
            row.update(
                {
                    "category": triage.get("category"),
                    "priority": triage.get("priority"),
                    "escalate": bool(triage.get("escalate")),
                    "confidence": triage.get("confidence"),
                    "policy_refs": triage.get("policy_refs") or [],
                    "reason": triage.get("escalation_reason")
                    or triage.get("reason")
                    or "",
                    "agent_notes": triage.get("agent_notes") or "",
                    "draft_reply": reply_text,
                    "reply_draft": reply_text,
                }
            )

            if dry_run:
                row["draft_id"] = "(dry-run — no draft created)"
                log.info("%s dry_run skip_draft", email_id)
            else:
                if not to_addr or "@" not in to_addr:
                    raise ValueError(f"Cannot draft: invalid From address {to_addr!r}")
                if not thread_id:
                    raise ValueError("Cannot draft: missing thread_id")

                draft_id = create_draft(
                    service,
                    to=to_addr,
                    subject=str(email.get("subject") or ""),
                    body=reply_text,
                    thread_id=thread_id,
                    in_reply_to=rfc_id,
                    references=rfc_id,
                )
                row["draft_id"] = draft_id
                log.info(
                    "%s draft_created id=%s chars=%d",
                    email_id,
                    draft_id,
                    len(reply_text),
                )

                if gmail_mid:
                    mark_processed(service, gmail_mid)
                    if row.get("escalate"):
                        mark_escalated(service, gmail_mid)
                    elif float(row.get("confidence") or 0) < 0.6:
                        mark_needs_review(service, gmail_mid)

        except Exception as exc:  # noqa: BLE001
            # Main loop never crashes on one bad message.
            log.info(
                "%s gmail_item_failed %s: %s",
                email_id,
                type(exc).__name__,
                exc,
            )
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["escalate"] = True
            row["category"] = row.get("category") or "unknown"
            row["priority"] = row.get("priority") or "high"
            row["draft_reply"] = row.get("draft_reply") or (
                "Dear Student,\n\n"
                "Thank you for writing to us. We received your message and a "
                "team member will review it shortly.\n\n"
                "Student Helpdesk"
            )
            if not dry_run and gmail_mid and not row.get("draft_id"):
                try:
                    mark_needs_review(service, gmail_mid)
                except Exception as label_exc:  # noqa: BLE001
                    log.info(
                        "%s label_failed %s: %s",
                        email_id,
                        type(label_exc).__name__,
                        label_exc,
                    )

        results.append(row)

    payload = {
        "run_at": started,
        "dry_run": dry_run,
        "query": query,
        "count": len(results),
        "drafts_created": sum(
            1 for r in results if r.get("draft_id") and not str(r["draft_id"]).startswith("(")
        ),
        "escalated": sum(1 for r in results if r.get("escalate")),
        "errors": sum(1 for r in results if r.get("error")),
        "results": results,
    }
    _atomic_write_json(out, payload)
    log.info(
        "gmail_run_done count=%d drafts=%d errors=%d out=%s",
        payload["count"],
        payload["drafts_created"],
        payload["errors"],
        out,
    )
    return payload


def load_gmail_outbox(path: Path | None = None) -> dict[str, Any]:
    """Load last Gmail run payload (empty structure if missing)."""
    p = path or GMAIL_OUTBOX_PATH
    if not p.is_file():
        return {
            "run_at": "",
            "count": 0,
            "drafts_created": 0,
            "escalated": 0,
            "errors": 0,
            "results": [],
        }
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "run_at": "",
            "count": 0,
            "drafts_created": 0,
            "escalated": 0,
            "errors": 0,
            "results": [],
            "warning": f"Could not parse {p.name}",
        }
    if isinstance(data, list):
        return {
            "run_at": "",
            "count": len(data),
            "drafts_created": sum(1 for r in data if r.get("draft_id")),
            "escalated": sum(1 for r in data if r.get("escalate")),
            "errors": sum(1 for r in data if r.get("error")),
            "results": data,
        }
    if isinstance(data, dict):
        data.setdefault("results", [])
        return data
    return {"run_at": "", "count": 0, "results": []}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gmail helpdesk bridge (drafts only — never sends)"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print OAuth / credentials status and exit",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="List matching inbox messages without drafting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Triage only — do not create Gmail drafts or change labels",
    )
    parser.add_argument("--limit", type=int, default=5, help="Max messages (default 5)")
    parser.add_argument(
        "--query",
        type=str,
        default="",
        help="Optional Gmail search query (overrides default unread filter)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=GMAIL_OUTBOX_PATH,
        help="Where to write the run summary JSON",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = _setup_logging(GMAIL_LOG_PATH)

    if args.status:
        status = gmail_status()
        print(json.dumps(status, indent=2))
        return 0 if status.get("can_connect") else 1

    query = args.query.strip() or None

    try:
        if args.preview:
            rows = preview_inbox(limit=args.limit, query=query)
            # ensure_ascii so Windows consoles (cp1252) don't crash on hair spaces etc.
            text = json.dumps(rows, indent=2, ensure_ascii=True)
            try:
                print(text)
            except UnicodeEncodeError:
                sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
            print(f"\nPreviewed {len(rows)} message(s). No drafts created.")
            return 0

        payload = process_gmail_batch(
            limit=args.limit,
            query=query,
            dry_run=bool(args.dry_run),
            out_path=Path(args.out),
            logger=logger,
        )
        print(
            f"Processed {payload['count']} | drafts {payload['drafts_created']} | "
            f"escalated {payload['escalated']} | errors {payload['errors']}"
        )
        print(f"Wrote {args.out}")
        return 0 if payload.get("errors", 0) == 0 else 0
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.info("gmail_fatal %s: %s", type(exc).__name__, exc)
        print(f"Gmail bridge failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
