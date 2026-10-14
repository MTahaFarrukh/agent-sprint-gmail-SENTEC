"""Student Helpdesk Triage Agent.

Usage:
    python agent.py
    python agent.py --inbox data/inbox --policy data/policy.md --out outbox.json --limit 5
    python agent.py --ids E005,E010,E013,E020 --out outbox_trace.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TRACE_PATH = ROOT / "logs" / "trace.jsonl"
MAX_REPAIRS = 2
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = (2.0, 4.0)


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

from llm import (  # noqa: E402
    arm_demo_corrupt_json_once,
    repair_draft,
    triage_email,
)
from policy import load_policy  # noqa: E402
from validator import inspect_draft, lookup_policy, validate_result  # noqa: E402

HOLDING_REPLY = (
    "Dear Student,\n\n"
    "Thank you for writing to us. We received your message and a team member "
    "will review it shortly. If this is urgent, please contact the relevant "
    "university office directly.\n\n"
    "Student Helpdesk"
)

# Intentionally bad draft for --demo-failures (over 150 words, wrong sign-off,
# invented office). validate_draft + repair_draft must fix it.
_DEMO_BAD_DRAFT = (
    "Dear Student,\n\n"
    "We have forwarded your request to the Quantum Affairs Office which is not "
    "a real office in the helpdesk policy. "
    + ("This filler sentence pads the reply past one hundred fifty words. " * 20)
    + "\n\nBest regards,\nCampus Bot Team\n"
)


class DemoStats:
    """Counters for --demo-failures recovery summary."""

    def __init__(self) -> None:
        self.injected = 0
        self.recovered = 0
        self.safe_fallback = 0
        self.injected_timeout = 0
        self.recovered_timeout = 0
        self.injected_json = 0
        self.recovered_json = 0
        self.injected_draft = 0
        self.recovered_draft = 0

    def summary_detail(self) -> str:
        return (
            f"injected={self.injected} recovered={self.recovered} "
            f"safe_fallback={self.safe_fallback} "
            f"(timeout {self.recovered_timeout}/{self.injected_timeout}, "
            f"bad_json {self.recovered_json}/{self.injected_json}, "
            f"bad_draft {self.recovered_draft}/{self.injected_draft})"
        )


class TraceLogger:
    """One short console line per step + one JSON object per line in trace.jsonl."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # Overwrite at start of each run.
        self.path.write_text("", encoding="utf-8")

    def step(self, email_id: str, step: str, detail: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        record = {
            "email_id": email_id,
            "step": step,
            "detail": detail,
            "timestamp": ts,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        # Short readable console line for live demo.
        print(f"[{email_id}] {step}: {detail}", flush=True)


def _setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("helpdesk_agent")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    # File only — live steps go through TraceLogger console lines.
    logger.addHandler(fh)
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


def _with_retry(
    email_id: str,
    action_name: str,
    fn: Callable[[], Any],
    trace: TraceLogger,
) -> Any:
    """Retry with backoff; log each retry; raise on final failure."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= MAX_RETRIES:
                break
            delay = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
            trace.step(
                email_id,
                "ACTION retry",
                f"{action_name} failed ({type(exc).__name__}: {exc}); "
                f"backoff {delay:.0f}s attempt {attempt + 1}/{MAX_RETRIES}",
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def process_email(
    email: dict[str, Any],
    policy_text: str,
    policy_codes: dict[str, str],
    logger: logging.Logger,
    trace: TraceLogger,
    *,
    demo_failures: bool = False,
    email_index: int = 1,
    demo_stats: DemoStats | None = None,
) -> dict[str, Any]:
    """Explicit agent loop: PLAN → ACTION/OBSERVATION → DECISION."""
    email_id = str(email.get("id") or "UNKNOWN")
    subject = str(email.get("subject") or "")[:50]
    stats = demo_stats

    if email.get("_load_error"):
        trace.step(email_id, "PLAN", f"load failed; emit safe record ({email['_load_error']})")
        trace.step(email_id, "DECISION", "safe failure escalate=true")
        logger.info("%s final=safe_failure reason=%s", email_id, email["_load_error"])
        if stats is not None:
            stats.safe_fallback += 1
        return _safe_failure(email_id, str(email["_load_error"]))

    inject_timeout = bool(demo_failures)
    inject_bad_json = bool(demo_failures) and email_index % 3 == 0
    inject_bad_draft = bool(demo_failures) and email_index % 5 == 0
    timeout_recovered = False
    json_recovered = False
    draft_recovered = False

    try:
        # --- PLAN ---
        plan_extra = ""
        if demo_failures:
            plan_extra = " | DEMO failures armed"
        trace.step(
            email_id,
            "PLAN",
            f"triage -> lookup cited codes -> validate escalation -> "
            f"validate/repair draft -> decide | subject={subject!r}{plan_extra}",
        )

        # --- ACTION triage (optional demo timeout + bad JSON) ---
        trace.step(email_id, "ACTION triage", "LLM classify + draft")
        triage_calls = 0

        if inject_timeout and stats is not None:
            stats.injected += 1
            stats.injected_timeout += 1
        if inject_bad_json:
            arm_demo_corrupt_json_once()
            if stats is not None:
                stats.injected += 1
                stats.injected_json += 1
            logger.info(
                "%s DEMO: simulated failure — first LLM JSON will be corrupted",
                email_id,
            )
            trace.step(
                email_id,
                "OBSERVATION",
                "DEMO: simulated failure — first LLM JSON answer will be invalid",
            )

        def _triage_with_demo() -> dict[str, Any]:
            nonlocal triage_calls, timeout_recovered, json_recovered
            triage_calls += 1
            if inject_timeout and triage_calls == 1:
                msg = "DEMO: simulated failure HTTP 503 timeout"
                logger.info("%s %s", email_id, msg)
                trace.step(email_id, "OBSERVATION", msg)
                raise TimeoutError(msg)
            result = triage_email(email, policy_text, policy_codes)
            if inject_timeout and triage_calls > 1:
                timeout_recovered = True
            if inject_bad_json:
                # generate_json already retried past the corrupted answer.
                json_recovered = True
            return result

        raw = _with_retry(email_id, "triage", _triage_with_demo, trace)
        if inject_timeout and timeout_recovered and stats is not None:
            stats.recovered += 1
            stats.recovered_timeout += 1
            logger.info("%s DEMO: simulated failure — timeout recovered via retry", email_id)
        if inject_bad_json and json_recovered and stats is not None:
            stats.recovered += 1
            stats.recovered_json += 1
            logger.info(
                "%s DEMO: simulated failure — invalid JSON recovered via LLM retry",
                email_id,
            )

        cited = [
            str(r).strip().upper()
            for r in (raw.get("policy_refs") or [])
            if str(r).strip()
        ]
        trace.step(
            email_id,
            "OBSERVATION",
            f"category={raw.get('category')} escalate={raw.get('escalate')} "
            f"cited={cited}",
        )
        logger.info(
            "%s llm_call=ok category=%s escalate=%s refs=%s",
            email_id,
            raw.get("category"),
            raw.get("escalate"),
            cited,
        )

        # --- ACTION lookup_policy for each cited code ---
        kept_refs: list[str] = []
        for code in cited:
            trace.step(email_id, "ACTION lookup_policy", code)
            rule = lookup_policy(code, policy_codes)
            if rule is None:
                trace.step(
                    email_id,
                    "OBSERVATION",
                    f"{code} unknown — dropped",
                )
                continue
            snippet = rule[:80].replace("\n", " ")
            kept_refs.append(code)
            trace.step(email_id, "OBSERVATION", f"{code}: {snippet}")
        raw["policy_refs"] = kept_refs

        # Escalation / schema validator (honesty tags).
        result, fixes = validate_result(raw, email, policy_codes, policy_text)
        if fixes:
            logger.info("%s validator_fixes=%s", email_id, "; ".join(fixes))
            honesty = [
                f
                for f in fixes
                if f.startswith("confirmed ") or f.startswith("overrode:")
            ]
            if honesty:
                trace.step(
                    email_id,
                    "OBSERVATION",
                    "validator " + "; ".join(honesty[:4]),
                )
        else:
            logger.info("%s validator_fixes=none", email_id)

        # Demo: replace first draft with a deliberately bad one.
        if inject_bad_draft:
            if stats is not None:
                stats.injected += 1
                stats.injected_draft += 1
            result["reply_draft"] = _DEMO_BAD_DRAFT
            logger.info(
                "%s DEMO: simulated failure — replaced draft with bad draft",
                email_id,
            )
            trace.step(
                email_id,
                "OBSERVATION",
                "DEMO: simulated failure — bad draft injected "
                "(>150 words, wrong sign-off, invented office)",
            )

        # --- ACTION validate_draft + repair loop ---
        repairs = 0
        while True:
            draft = str(result.get("reply_draft") or "")
            refs_now = list(result.get("policy_refs") or [])
            trace.step(email_id, "ACTION validate_draft", f"check reply (repairs={repairs})")
            issues = inspect_draft(draft, policy_refs=refs_now)
            if not issues:
                trace.step(email_id, "OBSERVATION", "issues=[]")
                if inject_bad_draft and repairs > 0:
                    draft_recovered = True
                break
            trace.step(email_id, "OBSERVATION", f"issues={issues}")
            if repairs >= MAX_REPAIRS:
                trace.step(
                    email_id,
                    "OBSERVATION",
                    f"max repairs ({MAX_REPAIRS}) reached; keeping draft",
                )
                break

            repairs += 1
            issue_list = list(issues)

            def _do_repair(
                _draft: str = draft,
                _refs: list[str] = refs_now,
                _issues: list[str] = issue_list,
            ) -> str:
                return repair_draft(
                    email, policy_text, _draft, _refs, _issues
                )

            trace.step(
                email_id,
                "ACTION repair_draft",
                f"LLM repair #{repairs} for {len(issue_list)} issue(s)",
            )
            try:
                new_draft = _with_retry(
                    email_id,
                    "repair_draft",
                    _do_repair,
                    trace,
                )
                result["reply_draft"] = new_draft
            except Exception as exc:  # noqa: BLE001
                trace.step(
                    email_id,
                    "OBSERVATION",
                    f"repair failed ({type(exc).__name__}); stop repair loop",
                )
                break

        if inject_bad_draft and draft_recovered and stats is not None:
            stats.recovered += 1
            stats.recovered_draft += 1
            logger.info(
                "%s DEMO: simulated failure — bad draft recovered via repair_draft",
                email_id,
            )
        elif inject_bad_draft and not draft_recovered:
            # Final check: maybe last repair cleared issues without loop break on empty.
            final_issues = inspect_draft(
                str(result.get("reply_draft") or ""),
                policy_refs=list(result.get("policy_refs") or []),
            )
            if not final_issues and stats is not None:
                stats.recovered += 1
                stats.recovered_draft += 1
                draft_recovered = True
                logger.info(
                    "%s DEMO: simulated failure — bad draft recovered via repair_draft",
                    email_id,
                )

        notes = str(result.get("agent_notes") or "").strip()
        if not notes:
            result["agent_notes"] = (
                f"Classified as {result.get('category')} with refs "
                f"{result.get('policy_refs')}."
            )
        note_lines = [ln.strip() for ln in result["agent_notes"].splitlines() if ln.strip()]
        result["agent_notes"] = " ".join(note_lines[:2])

        reason = str(result.get("escalation_reason") or "")[:80]
        trace.step(
            email_id,
            "DECISION",
            f"category={result.get('category')} priority={result.get('priority')} "
            f"escalate={result.get('escalate')} reason={reason!r}",
        )
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
        if stats is not None:
            stats.safe_fallback += 1
        trace.step(
            email_id,
            "ACTION retry",
            f"pipeline failed after retries ({type(exc).__name__}: {exc})",
        )
        trace.step(email_id, "DECISION", "safe failure escalate=true")
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
        "--ids",
        type=str,
        default="",
        help="Comma-separated email ids to process (e.g. E003,E010)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "logs" / "agent.log",
        help="Log file path",
    )
    parser.add_argument(
        "--demo-failures",
        action="store_true",
        default=False,
        help=(
            "Demo only (off by default): inject timeout/503, invalid JSON, and "
            "bad drafts so retry/repair paths can be shown live"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = _setup_logging(args.log.resolve())
    trace = TraceLogger(TRACE_PATH)
    started = datetime.now(timezone.utc).isoformat()
    logger.info("run_start at=%s inbox=%s policy=%s", started, args.inbox, args.policy)
    print(f"trace -> {TRACE_PATH}", flush=True)

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
    id_filter = {
        part.strip()
        for part in str(args.ids or "").split(",")
        if part.strip()
    }
    if id_filter:
        files = [p for p in files if p.stem in id_filter]
        logger.info("ids_filter=%s", ",".join(sorted(id_filter)))
    if args.limit and args.limit > 0:
        files = files[: args.limit]
    logger.info("inbox_scan files=%d", len(files))
    demo_failures = bool(getattr(args, "demo_failures", False))
    demo_stats = DemoStats() if demo_failures else None
    if demo_failures:
        logger.info("DEMO: simulated failure mode ON (--demo-failures)")
        print("DEMO: simulated failure mode ON", flush=True)
        trace.step(
            "RUN",
            "PLAN",
            "DEMO: simulated failure mode — timeout each email; "
            "bad JSON every 3rd; bad draft every 5th",
        )

    results: list[dict[str, Any]] = []
    for index, path in enumerate(files, start=1):
        email = _load_email_file(path, logger)
        if email is None:
            eid = path.stem
            trace.step(eid, "PLAN", "could not read file; emit safe record")
            trace.step(eid, "DECISION", "safe failure escalate=true")
            if demo_stats is not None:
                demo_stats.safe_fallback += 1
            results.append(_safe_failure(eid, "could not read file"))
            continue
        results.append(
            process_email(
                email,
                policy_text,
                policy_codes,
                logger,
                trace,
                demo_failures=demo_failures,
                email_index=index,
                demo_stats=demo_stats,
            )
        )

    out_path = Path(args.out).resolve()
    _atomic_write_json(out_path, results)
    logger.info("outbox_written path=%s count=%d", out_path, len(results))

    _print_summary(results)

    if demo_stats is not None:
        detail = demo_stats.summary_detail()
        print(f"\nDEMO recovery summary: {detail}", flush=True)
        logger.info("DEMO recovery summary: %s", detail)
        trace.step("RUN", "DECISION", f"DEMO recovery summary: {detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
