"""Student Helpdesk Triage Agent.

Usage:
    python agent.py
    python agent.py --inbox data/inbox --policy data/policy.md --out outbox.json --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_gemini_api_key() -> str:
    """Prefer process env (GEMINI_API_KEY / GOOGLE_API_KEY), else project .env."""
    key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip().strip('"').strip("'")
    if key:
        os.environ["GEMINI_API_KEY"] = key
        return key

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip().strip('"').strip("'")
    if key:
        os.environ["GEMINI_API_KEY"] = key
    return key


# Must run before importing llm / src.config so the key is visible.
GEMINI_API_KEY = _load_gemini_api_key()

from llm import triage_email  # noqa: E402
from policy import load_policy  # noqa: E402
from validator import validate_result  # noqa: E402

HOLDING_REPLY = (
    "Dear Student,\n\n"
    "Thank you for writing to us. We received your message and a team member "
    "will review it shortly. If this is urgent, please contact the relevant "
    "campus office directly.\n\n"
    "Student Helpdesk"
)


def _setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("helpdesk_agent")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def _safe_failure(email_id: str, err: str) -> dict[str, Any]:
    return {
        "email_id": email_id,
        "category": "other",
        "priority": "medium",
        "escalate": True,
        "escalation_reason": "agent error, needs human",
        "policy_refs": [],
        "reply_draft": HOLDING_REPLY,
        "confidence": 0.0,
        "agent_notes": f"Failure path: {err[:180]}",
    }


def _load_email_file(path: Path, logger: logging.Logger) -> dict[str, Any] | None:
    """Load one inbox JSON; tolerate bad JSON / missing fields."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("%s loaded=fail read_error=%s", path.name, exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.info("%s loaded=fail bad_json=%s", path.name, exc)
        return {
            "id": path.stem,
            "from_name": "Student",
            "from_email": "",
            "subject": "",
            "body": "",
            "received_at": "",
            "_load_error": f"bad JSON: {exc}",
        }
    if not isinstance(data, dict):
        logger.info("%s loaded=fail not_object", path.name)
        return {
            "id": path.stem,
            "from_name": "Student",
            "from_email": "",
            "subject": "",
            "body": "",
            "received_at": "",
            "_load_error": "JSON root is not an object",
        }

    email = {
        "id": str(data.get("id") or path.stem),
        "from_name": str(data.get("from_name") or "Student"),
        "from_email": str(data.get("from_email") or ""),
        "subject": str(data.get("subject") or ""),
        "body": str(data.get("body") or ""),
        "received_at": str(data.get("received_at") or ""),
    }
    logger.info(
        "%s loaded id=%s subject=%r body_len=%d",
        path.name,
        email["id"],
        email["subject"][:40],
        len(email["body"]),
    )
    return email


def _atomic_write_json(path: Path, payload: list[dict[str, Any]]) -> None:
    """Rewrite outbox fully via temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        suffix=".tmp",
    ) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_name = tmp.name
    Path(tmp_name).replace(path)


def process_email(
    email: dict[str, Any],
    policy_text: str,
    policy_codes: dict[str, str],
    logger: logging.Logger,
) -> dict[str, Any]:
    """Triage one email end-to-end with per-email failure handling."""
    email_id = str(email.get("id") or "UNKNOWN")
    if email.get("_load_error"):
        logger.info("%s final=safe_failure reason=%s", email_id, email["_load_error"])
        return _safe_failure(email_id, str(email["_load_error"]))

    try:
        logger.info("%s llm_call=start", email_id)
        raw = triage_email(email, policy_text, policy_codes)
        logger.info(
            "%s llm_call=ok category=%s escalate=%s refs=%s",
            email_id,
            raw.get("category"),
            raw.get("escalate"),
            raw.get("policy_refs"),
        )

        result, fixes = validate_result(raw, email, policy_codes, policy_text)
        if fixes:
            logger.info("%s validator_fixes=%s", email_id, "; ".join(fixes))
        else:
            logger.info("%s validator_fixes=none", email_id)

        notes = str(result.get("agent_notes") or "").strip()
        if not notes:
            result["agent_notes"] = (
                f"Classified as {result.get('category')} with refs "
                f"{result.get('policy_refs')}."
            )
        # Keep agent_notes to ~2 lines
        note_lines = [ln.strip() for ln in result["agent_notes"].splitlines() if ln.strip()]
        result["agent_notes"] = " ".join(note_lines[:2])

        logger.info(
            "%s final category=%s priority=%s escalate=%s confidence=%s",
            email_id,
            result.get("category"),
            result.get("priority"),
            result.get("escalate"),
            result.get("confidence"),
        )
        return {
            "email_id": result["email_id"],
            "category": result["category"],
            "priority": result["priority"],
            "escalate": bool(result["escalate"]),
            "escalation_reason": str(result.get("escalation_reason") or ""),
            "policy_refs": list(result.get("policy_refs") or []),
            "reply_draft": str(result.get("reply_draft") or HOLDING_REPLY),
            "confidence": float(result.get("confidence") or 0.0),
            "agent_notes": str(result.get("agent_notes") or ""),
        }
    except Exception as exc:  # noqa: BLE001 — never crash the loop
        logger.info("%s final=safe_failure error=%s: %s", email_id, type(exc).__name__, exc)
        return _safe_failure(email_id, f"{type(exc).__name__}: {exc}")


def _print_summary(results: list[dict[str, Any]]) -> None:
    headers = ("id", "category", "priority", "escalate", "refs", "confidence")
    widths = [8, 12, 8, 9, 28, 10]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print()
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for row in results:
        refs = ",".join(row.get("policy_refs") or [])
        print(
            fmt.format(
                str(row.get("email_id", ""))[: widths[0]],
                str(row.get("category", ""))[: widths[1]],
                str(row.get("priority", ""))[: widths[2]],
                "yes" if row.get("escalate") else "no",
                refs[: widths[4]],
                f"{float(row.get('confidence') or 0):.2f}",
            )
        )
    escalated = sum(1 for r in results if r.get("escalate"))
    print()
    print(f"Processed {len(results)} emails | Escalated {escalated}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Student Helpdesk Triage Agent")
    parser.add_argument(
        "--inbox",
        type=Path,
        default=ROOT / "data" / "inbox",
        help="Folder of *.json emails (re-scanned each run)",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "data" / "policy.md",
        help="Path to policy.md",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "outbox.json",
        help="Output outbox.json path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of emails to process (0 = all)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "logs" / "agent.log",
        help="Log file path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = _setup_logging(args.log.resolve())
    started = datetime.now(timezone.utc).isoformat()
    logger.info("run_start at=%s inbox=%s policy=%s", started, args.inbox, args.policy)

    if not GEMINI_API_KEY:
        msg = (
            "No API key found. Set GEMINI_API_KEY or GOOGLE_API_KEY in the "
            "environment, or put it in the project-root .env file."
        )
        logger.info("api_key_missing")
        print(msg, file=sys.stderr)
        return 1
    logger.info("api_key_loaded source=env_or_dotenv len=%d", len(GEMINI_API_KEY))

    try:
        policy_text, policy_codes = load_policy(args.policy)
    except Exception as exc:  # noqa: BLE001
        logger.info("policy_load_failed %s: %s", type(exc).__name__, exc)
        print(f"Failed to load policy: {exc}", file=sys.stderr)
        return 1

    logger.info("policy_loaded codes=%d", len(policy_codes))

    inbox = Path(args.inbox).resolve()
    if not inbox.is_dir():
        print(f"Inbox folder not found: {inbox}", file=sys.stderr)
        return 1

    files = sorted(inbox.glob("*.json"))
    if args.limit and args.limit > 0:
        files = files[: args.limit]
    logger.info("inbox_scan files=%d", len(files))

    results: list[dict[str, Any]] = []
    for path in files:
        email = _load_email_file(path, logger)
        if email is None:
            results.append(_safe_failure(path.stem, "could not read file"))
            continue
        results.append(process_email(email, policy_text, policy_codes, logger))

    out_path = Path(args.out).resolve()
    _atomic_write_json(out_path, results)
    logger.info("outbox_written path=%s count=%d", out_path, len(results))

    _print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
