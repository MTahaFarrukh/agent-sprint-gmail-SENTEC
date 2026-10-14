"""Streamlit status dashboard for the Student Helpdesk Triage Agent.

Reads outbox.json, data/inbox/*.json, data/policy.md and the agent trace
(logs/trace.jsonl if present, otherwise steps derived from logs/agent.log).
Never sends anything: it only reads files, saves new inbox JSON files and
runs agent.py as a subprocess.

Run with:
    streamlit run dashboard.py
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
OUTBOX_PATH = ROOT / "outbox.json"
INBOX_DIR = ROOT / "data" / "inbox"
POLICY_PATH = ROOT / "data" / "policy.md"
TRACE_PATH = ROOT / "logs" / "trace.jsonl"
LOG_PATH = ROOT / "logs" / "agent.log"

TEAM_NAME = "Teen Haseen"
LOW_CONFIDENCE = 0.6
LOG_TAIL_LINES = 22

ACCENT = "#8B7CF6"
ACCENT_SOFT = "rgba(139,124,246,0.16)"
DANGER = "#F43F5E"
DANGER_SOFT = "rgba(244,63,94,0.14)"
TEXT = "#E7E9F0"
MUTED = "#8A90A6"
GRID = "rgba(255,255,255,0.06)"
FONT = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"

STEP_ORDER = ("PLAN", "ACTION", "OBSERVATION", "DECISION")
PRIORITY_ORDER = ("high", "medium", "low")
CODE_RE = re.compile(r"^\s*([A-Z]{2,}-\d+)\s*:\s*(.+?)\s*$")
ESC_RE = re.compile(r"\bESC-\d+\b")
LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\w+\s+(.*)$"
)


# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {{
  --bg: #0B0D12; --surface: #12151C; --surface-2: #181C25; --border: #232836;
  --text: {TEXT}; --muted: {MUTED}; --accent: {ACCENT}; --accent-soft: {ACCENT_SOFT};
  --danger: {DANGER}; --danger-soft: {DANGER_SOFT};
}}
html, body, .stApp, [data-testid="stAppViewContainer"] {{
  background: var(--bg) !important; color: var(--text); font-family: {FONT};
}}
.stApp p, .stApp label, .stApp span, .stApp li {{ color: var(--text); }}
header[data-testid="stHeader"] {{ background: transparent !important; }}
#MainMenu, footer, .stDeployButton, [data-testid="stDecoration"] {{ display: none !important; }}
.block-container {{ padding-top: 2rem; max-width: 1400px; }}

[data-testid="stSidebar"] {{ background: #0E1118 !important; border-right: 1px solid var(--border); }}
[data-testid="stSidebar"] * {{ color: var(--text); }}

/* inputs (also force dark when the Streamlit theme is light) */
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="base-input"],
[data-baseweb="textarea"], .stTextInput input, .stTextArea textarea {{
  background: var(--surface-2) !important; color: var(--text) !important;
  border-color: var(--border) !important; border-radius: 10px !important;
}}
[data-baseweb="select"] > div:focus-within, [data-baseweb="input"]:focus-within,
[data-baseweb="textarea"]:focus-within {{ border-color: var(--accent) !important; }}
[data-baseweb="popover"] ul, [data-baseweb="menu"], [data-baseweb="popover"] li {{
  background: var(--surface-2) !important; color: var(--text) !important;
}}
[data-baseweb="tag"] {{ background: var(--accent-soft) !important; border-radius: 8px !important; }}
[data-baseweb="tag"] span {{ color: var(--accent) !important; }}
input::placeholder, textarea::placeholder {{ color: #5B6175 !important; }}

/* buttons */
.stButton > button, [data-testid="stFormSubmitButton"] > button {{
  width: 100%; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--text); font-weight: 600;
  transition: all .15s ease;
}}
.stButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {{
  border-color: var(--accent); color: var(--accent); background: var(--surface-2);
}}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] {{
  background: var(--accent); border-color: var(--accent); color: #0B0D12;
}}
.stButton > button[kind="primary"]:hover {{ filter: brightness(1.08); color: #0B0D12; }}
[data-testid="stForm"] {{ border: 1px solid var(--border); border-radius: 14px; background: var(--surface); }}
[data-testid="stExpander"] details {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }}
[data-testid="stExpander"] summary:hover {{ color: var(--accent); }}

/* header */
.hd {{ display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:1rem;
  padding: 1.4rem 1.6rem; border-radius: 18px; border:1px solid var(--border);
  background: radial-gradient(1200px 200px at 0% 0%, var(--accent-soft), transparent 60%), var(--surface); }}
.hd h1 {{ font-size: 1.65rem; font-weight: 700; margin: 0; color: var(--text); letter-spacing: -0.02em; padding:0; }}
.hd .sub {{ color: var(--muted); font-size: .9rem; margin-top: .25rem; }}
.hd .team {{ color: var(--accent); font-weight: 600; }}
.safe {{ display:inline-flex; align-items:center; gap:.5rem; padding:.5rem .9rem; border-radius:999px;
  border:1px solid var(--accent); background: var(--accent-soft); color: var(--accent);
  font-weight:700; font-size:.78rem; letter-spacing:.06em; }}
.safe .dot {{ width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 10px var(--accent); }}

/* cards */
.kpi {{ background: var(--surface); border:1px solid var(--border); border-radius:16px; padding:1.1rem 1.2rem; height:100%; }}
.kpi .lbl {{ color: var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; font-weight:600; }}
.kpi .val {{ font-size:2rem; font-weight:700; margin-top:.35rem; color: var(--text); letter-spacing:-0.02em; }}
.kpi .hint {{ color: var(--muted); font-size:.78rem; margin-top:.15rem; }}
.kpi.accent .val {{ color: var(--accent); }}
.kpi.danger {{ border-color: rgba(244,63,94,.35); }}
.kpi.danger .val {{ color: var(--danger); }}
.card {{ background: var(--surface); border:1px solid var(--border); border-radius:16px; padding:1rem 1.2rem; margin-bottom: .9rem; }}
.card h4 {{ margin:0 0 .6rem 0; font-size:.8rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-weight:600; padding:0; }}
[class*="st-key-chartcard_"] {{ background: var(--surface); border:1px solid var(--border); border-radius:16px; padding:1rem 1.1rem .4rem; }}
.card-title {{ font-size:.8rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-weight:600; }}
.section {{ font-size:1.05rem; font-weight:650; margin: 1.6rem 0 .7rem; color: var(--text); display:flex; align-items:center; gap:.55rem; }}
.section .bar {{ width:4px; height:18px; border-radius:4px; background: var(--accent); display:inline-block; }}
.section.danger .bar {{ background: var(--danger); }}
.muted {{ color: var(--muted); font-size:.85rem; }}

/* badges */
.bdg {{ display:inline-block; padding:.18rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600;
  background: var(--surface-2); border:1px solid var(--border); color: var(--text); margin: 0 .25rem .2rem 0; white-space:nowrap; }}
.bdg.accent {{ background: var(--accent-soft); border-color: transparent; color: var(--accent); }}
.bdg.danger {{ background: var(--danger-soft); border-color: transparent; color: var(--danger); }}
.bdg.code {{ font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; }}

/* escalation queue */
.esc {{ background: var(--surface); border:1px solid var(--border); border-left: 3px solid var(--danger);
  border-radius: 12px; padding: .8rem 1rem; margin-bottom:.6rem; }}
.esc .top {{ display:flex; justify-content:space-between; gap:.6rem; flex-wrap:wrap; align-items:center; }}
.esc .id {{ font-weight:700; color: var(--danger); margin-right:.5rem; }}
.esc .subj {{ font-weight:600; }}
.esc .reason {{ color: var(--muted); font-size:.86rem; margin-top:.35rem; }}

/* table */
.tbl-wrap {{ max-height: 460px; overflow:auto; border:1px solid var(--border); border-radius:14px; background: var(--surface); }}
table.tbl {{ width:100%; border-collapse: collapse; font-size:.86rem; }}
table.tbl th {{ position: sticky; top:0; background: var(--surface-2); color: var(--muted); text-align:left;
  font-weight:600; font-size:.72rem; text-transform:uppercase; letter-spacing:.07em; padding:.7rem .8rem; z-index:1; }}
table.tbl td {{ padding:.6rem .8rem; border-top:1px solid var(--border); vertical-align: top; color: var(--text); }}
table.tbl tr:hover td {{ background: rgba(139,124,246,0.05); }}
.conf {{ display:flex; align-items:center; gap:.45rem; }}
.conf .track {{ width:60px; height:6px; background: var(--surface-2); border-radius:6px; overflow:hidden; }}
.conf .fill {{ height:100%; background: var(--accent); border-radius:6px; }}
.conf.low .fill {{ background: var(--danger); }}

/* detail */
.reply {{ white-space: pre-wrap; line-height:1.6; font-size:.92rem; color: var(--text);
  background: var(--surface-2); border-radius: 12px; padding: 1rem 1.1rem; border:1px solid var(--border); }}
.body {{ white-space: pre-wrap; line-height:1.55; font-size:.88rem; color: #C6CAD6; }}
.rule {{ padding:.6rem .75rem; border-radius:10px; background: var(--surface-2); margin-bottom:.45rem; font-size:.86rem; line-height:1.5; }}
.rule .c {{ font-weight:700; color: var(--accent); margin-right:.4rem; font-family: ui-monospace, Consolas, monospace; }}
.rule.esc-rule .c {{ color: var(--danger); }}

/* timeline */
.tl {{ position:relative; padding-left: 1.4rem; }}
.tl::before {{ content:""; position:absolute; left:.42rem; top:.3rem; bottom:.3rem; width:2px; background: var(--border); }}
.tl .st {{ position:relative; margin-bottom: .85rem; }}
.tl .st::before {{ content:""; position:absolute; left:-1.18rem; top:.3rem; width:10px; height:10px; border-radius:50%;
  background: var(--bg); border:2px solid var(--accent); }}
.tl .st.DECISION::before {{ background: var(--accent); }}
.tl .kind {{ font-size:.68rem; font-weight:700; letter-spacing:.09em; color: var(--accent); }}
.tl .ts {{ color: var(--muted); font-size:.72rem; margin-left:.4rem; }}
.tl .txt {{ font-size:.86rem; margin-top:.1rem; color: var(--text); word-break: break-word; }}

/* log tail */
.logtail {{ background:#07090D; border:1px solid var(--border); border-radius:12px; padding:.8rem 1rem;
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-size:.74rem; color:#AEB4C6;
  white-space: pre-wrap; max-height: 360px; overflow:auto; }}
.flash {{ border-radius:12px; padding:.7rem 1rem; margin-top: .8rem; font-size:.88rem;
  border:1px solid var(--accent); background: var(--accent-soft); color: var(--text); }}
.flash.err {{ border-color: var(--danger); background: var(--danger-soft); }}
.side-title {{ font-weight:700; font-size:1rem; margin-bottom:.2rem; }}
</style>
"""


def esc(value: Any) -> str:
    """HTML-escape any value. Email content is untrusted and must never render as HTML."""
    return html.escape(str(value if value is not None else ""))


def section(title: str, danger: bool = False) -> None:
    """Render a section heading with an accent bar."""
    cls = "section danger" if danger else "section"
    st.markdown(f'<div class="{cls}"><span class="bar"></span>{esc(title)}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Data loading (every loader tolerates missing or partial files)
# --------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    """Read a JSON file; return None if it is missing, unreadable or invalid."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _to_float(value: Any) -> float:
    """Coerce a value to float in [0, 1], defaulting to 0."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _to_bool(value: Any) -> bool:
    """Coerce JSON-ish truthy values ("true", "yes", 1) to bool."""
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "y"}
    return bool(value)


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults so a partial outbox row never breaks the UI."""
    refs = row.get("policy_refs") or []
    if isinstance(refs, str):
        refs = [r.strip() for r in refs.split(",") if r.strip()]
    return {
        "email_id": str(row.get("email_id") or row.get("id") or "UNKNOWN"),
        "category": str(row.get("category") or "other").lower(),
        "priority": str(row.get("priority") or "medium").lower(),
        "escalate": _to_bool(row.get("escalate")),
        "escalation_reason": str(row.get("escalation_reason") or ""),
        "policy_refs": [str(r).strip().upper() for r in refs if str(r).strip()],
        "reply_draft": str(row.get("reply_draft") or ""),
        "confidence": _to_float(row.get("confidence")),
        "agent_notes": str(row.get("agent_notes") or ""),
    }


def load_outbox() -> tuple[list[dict[str, Any]], str]:
    """Load outbox.json. Returns (rows, warning message or '')."""
    if not OUTBOX_PATH.exists():
        return [], "outbox.json not found yet. Use Run agent in the sidebar."
    data = _read_json(OUTBOX_PATH)
    if data is None:
        return [], "outbox.json could not be parsed (partial write?). Showing nothing until it is valid."
    if isinstance(data, dict):
        data = [dict(v, email_id=v.get("email_id", k)) for k, v in data.items() if isinstance(v, dict)]
    if not isinstance(data, list):
        return [], "outbox.json has an unexpected shape."
    return [normalize_row(r) for r in data if isinstance(r, dict)], ""


def load_inbox() -> dict[str, dict[str, Any]]:
    """Load every inbox email keyed by id (falls back to the file stem)."""
    emails: dict[str, dict[str, Any]] = {}
    if not INBOX_DIR.is_dir():
        return emails
    for path in sorted(INBOX_DIR.glob("*.json")):
        data = _read_json(path)
        if not isinstance(data, dict):
            data = {}
        email_id = str(data.get("id") or path.stem)
        emails[email_id] = data
    return emails


def load_policy_rules() -> dict[str, str]:
    """Parse 'CODE-N: text' lines from policy.md into {code: text}."""
    try:
        text = POLICY_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    rules: dict[str, str] = {}
    for line in text.splitlines():
        match = CODE_RE.match(line)
        if match:
            rules[match.group(1).upper()] = match.group(2)
    return rules


def _trace_from_jsonl(path: Path) -> dict[str, list[dict[str, str]]]:
    """Read logs/trace.jsonl; skip any malformed line."""
    steps: dict[str, list[dict[str, str]]] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return steps
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        email_id = str(rec.get("email_id") or rec.get("id") or "").strip()
        kind = str(rec.get("step") or rec.get("type") or rec.get("kind") or "").upper().strip()
        if not email_id or not kind:
            continue
        detail = rec.get("content", rec.get("text", rec.get("detail", rec.get("message", ""))))
        if not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
        ts = str(rec.get("ts") or rec.get("timestamp") or "")
        if kind == "PLAN" and steps.get(email_id) and steps[email_id][-1]["kind"] == "DECISION":
            steps[email_id] = []  # a new run of the same email: keep only the latest
        steps.setdefault(email_id, []).append({"kind": kind, "ts": ts, "text": detail})
    return steps


def _classify_log_message(msg: str) -> tuple[str, str, str] | None:
    """Map one agent.log message to (email_id, step kind, readable text)."""
    loaded = re.match(r"^(\S+?)\.json loaded id=(\S+) subject=(.*?) body_len=(\d+)", msg)
    if loaded:
        return (
            loaded.group(2),
            "PLAN",
            f"Read email {loaded.group(3)} ({loaded.group(4)} chars). "
            "Next: one LLM triage call against the policy, then the deterministic validator.",
        )
    failed_load = re.match(r"^(\S+?)\.json loaded=fail (.*)$", msg)
    if failed_load:
        return failed_load.group(1), "OBSERVATION", f"Could not load the file: {failed_load.group(2)}"
    parts = msg.split(" ", 1)
    if len(parts) < 2:
        return None
    email_id, rest = parts
    if rest.startswith("llm_call=start"):
        return email_id, "ACTION", "Called the LLM (temperature 0, strict JSON) with the email as untrusted data."
    if rest.startswith("llm_call=ok"):
        return email_id, "OBSERVATION", "LLM proposed " + rest.replace("llm_call=ok", "").strip()
    if rest.startswith("validator_fixes="):
        fixes = rest.split("=", 1)[1]
        text = "Validator: no fixes needed." if fixes == "none" else f"Validator applied fixes: {fixes}"
        return email_id, "OBSERVATION", text
    if rest.startswith("final=safe_failure"):
        return email_id, "DECISION", "Safe failure record (escalate, holding reply): " + rest.split(" ", 1)[-1]
    if rest.startswith("final "):
        return email_id, "DECISION", "Final: " + rest[len("final "):]
    return None


def _trace_from_log(path: Path) -> dict[str, list[dict[str, str]]]:
    """Derive PLAN/ACTION/OBSERVATION/DECISION steps from logs/agent.log (latest run per email)."""
    steps: dict[str, list[dict[str, str]]] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return steps
    for line in lines:
        match = LOG_LINE_RE.match(line)
        if not match:
            continue
        parsed = _classify_log_message(match.group(2))
        if not parsed:
            continue
        email_id, kind, text = parsed
        current = steps.get(email_id, [])
        if kind in {"PLAN", "ACTION"} and current and current[-1]["kind"] == "DECISION":
            current = []  # a later run re-processed this email
        if kind == "PLAN":
            current = []
        current.append({"kind": kind, "ts": match.group(1), "text": text})
        steps[email_id] = current
    return steps


def load_trace() -> tuple[dict[str, list[dict[str, str]]], str]:
    """Return (steps per email id, source label)."""
    if TRACE_PATH.exists():
        steps = _trace_from_jsonl(TRACE_PATH)
        if steps:
            return steps, "logs/trace.jsonl"
    if LOG_PATH.exists():
        return _trace_from_log(LOG_PATH), "derived from logs/agent.log"
    return {}, "no trace or log file found"


# --------------------------------------------------------------------------
# Agent subprocess + inbox writer
# --------------------------------------------------------------------------


def _agent_env() -> dict[str, str]:
    """Environment for the agent subprocess: unbuffered UTF-8 output."""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_agent_live(extra_args: list[str], tail_box: Any) -> tuple[int, list[str]]:
    """Run agent.py, streaming the last lines of output into tail_box. Returns (exit code, all lines)."""
    cmd = [sys.executable, "-u", str(ROOT / "agent.py"), *extra_args]
    tail: deque[str] = deque(maxlen=LOG_TAIL_LINES)
    all_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_agent_env(),
        )
    except OSError as exc:
        return -1, [f"Could not start agent: {exc}"]
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        all_lines.append(line)
        tail.append(line)
        tail_box.markdown(f'<div class="logtail">{esc(chr(10).join(tail))}</div>', unsafe_allow_html=True)
    return proc.wait(), all_lines


def merge_into_outbox(new_rows: list[dict[str, Any]]) -> None:
    """Replace/append rows by email_id in outbox.json, written atomically."""
    existing = _read_json(OUTBOX_PATH)
    if not isinstance(existing, list):
        existing = []
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in existing + new_rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("email_id") or "")
        if key not in by_id:
            order.append(key)
        by_id[key] = row
    merged = [by_id[k] for k in sorted(order)]
    fd, tmp = tempfile.mkstemp(dir=str(ROOT), prefix=".outbox_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, OUTBOX_PATH)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def run_partial(ids: list[str], tail_box: Any) -> tuple[bool, str]:
    """Process only the given ids into a temp outbox, then merge into outbox.json.

    agent.py rewrites --out completely, so --ids must never point at outbox.json.
    """
    fd, tmp_out = tempfile.mkstemp(prefix="outbox_partial_", suffix=".json")
    os.close(fd)
    try:
        code, _ = run_agent_live(["--ids", ",".join(ids), "--out", tmp_out], tail_box)
        rows = _read_json(Path(tmp_out))
        if code != 0 or not isinstance(rows, list) or not rows:
            return False, f"Agent exited with code {code}; outbox.json was left unchanged."
        merge_into_outbox(rows)
        return True, f"Processed {len(rows)} email(s): {', '.join(ids)}. Merged into outbox.json."
    finally:
        try:
            os.remove(tmp_out)
        except OSError:
            pass


def next_email_id(inbox: dict[str, dict[str, Any]]) -> str:
    """Next free id in the E### series used by the sample inbox."""
    numbers = [0]
    for email_id in inbox:
        match = re.fullmatch(r"E(\d+)", email_id)
        if match:
            numbers.append(int(match.group(1)))
    n = max(numbers) + 1
    while (INBOX_DIR / f"E{n:03d}.json").exists():
        n += 1
    return f"E{n:03d}"


def save_new_email(name: str, sender_email: str, subject: str, body: str, inbox: dict[str, Any]) -> str:
    """Save a pasted email into data/inbox/ with the same fields as the samples. Returns its id."""
    email_id = next_email_id(inbox)
    record = {
        "id": email_id,
        "from_name": name.strip() or "Unknown Sender",
        "from_email": sender_email.strip(),
        "subject": subject.strip(),
        "body": body.strip(),
        "received_at": datetime.now().isoformat(timespec="seconds"),
    }
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    (INBOX_DIR / f"{email_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return email_id


# --------------------------------------------------------------------------
# UI pieces
# --------------------------------------------------------------------------


def render_sidebar(inbox: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    """Sidebar controls. Clicks are queued in session_state and executed in the main area."""
    with st.sidebar:
        st.markdown('<div class="side-title">Agent controls</div>', unsafe_allow_html=True)
        st.markdown('<div class="muted">Drafts only. Nothing is ever sent.</div>', unsafe_allow_html=True)
        st.write("")
        if st.button("Run agent on full inbox", type="primary", key="run_all"):
            st.session_state["pending"] = {"mode": "all", "ids": []}

        processed = {r["email_id"] for r in rows}
        new_ids = sorted(i for i in inbox if i not in processed)
        label = f"Process only new emails ({len(new_ids)})"
        if st.button(label, key="run_new", disabled=not new_ids):
            st.session_state["pending"] = {"mode": "ids", "ids": new_ids}
        if new_ids:
            st.markdown(f'<div class="muted">Not yet in outbox: {esc(", ".join(new_ids))}</div>', unsafe_allow_html=True)

        st.write("")
        st.markdown('<div class="side-title">Add a new email</div>', unsafe_allow_html=True)
        with st.form("new_email", clear_on_submit=True):
            name = st.text_input("Sender name", placeholder="e.g. Ayesha Khan")
            sender_email = st.text_input("Sender email (optional)", placeholder="name@example.com")
            subject = st.text_input("Subject")
            body = st.text_area("Body", height=160, placeholder="Paste the email text here")
            after = st.selectbox("After saving", ["Process only this new email", "Just save to inbox"])
            submitted = st.form_submit_button("Save email", type="primary")
        if submitted:
            if not body.strip() and not subject.strip():
                st.session_state["flash"] = ("err", "Subject or body is required.")
                st.rerun()
            try:
                new_id = save_new_email(name, sender_email, subject, body, inbox)
            except OSError as exc:
                st.session_state["flash"] = ("err", f"Could not save email: {exc}")
                st.rerun()
            if after.startswith("Process"):
                st.session_state["pending"] = {"mode": "ids", "ids": [new_id], "saved": new_id}
            else:
                st.session_state["flash"] = ("ok", f"Saved data/inbox/{new_id}.json.")
                st.rerun()


def handle_pending_run() -> None:
    """Execute a queued agent run with a live log tail, then reload the page."""
    pending = st.session_state.pop("pending", None)
    if not pending:
        return
    title = "Running agent on full inbox" if pending["mode"] == "all" else f"Processing {', '.join(pending['ids'])}"
    with st.status(title + "…", expanded=True) as status:
        tail_box = st.empty()
        if pending["mode"] == "all":
            code, _ = run_agent_live([], tail_box)
            ok = code == 0
            msg = "Agent finished; outbox.json rewritten." if ok else f"Agent exited with code {code}."
        else:
            ok, msg = run_partial(pending["ids"], tail_box)
        if pending.get("saved"):
            msg = f"Saved data/inbox/{pending['saved']}.json. " + msg
        status.update(label=msg, state="complete" if ok else "error")
    st.session_state["flash"] = ("ok" if ok else "err", msg)
    st.rerun()


def render_header() -> None:
    """Title, team name and safety badge."""
    st.markdown(
        f"""<div class="hd">
              <div><h1>Student Helpdesk Triage Agent</h1>
                <div class="sub">Team <span class="team">{esc(TEAM_NAME)}</span> · Agent Sprint, Engineer's Code 2026</div></div>
              <div class="safe"><span class="dot"></span>DRAFTS ONLY, NOTHING IS SENT</div>
            </div>""",
        unsafe_allow_html=True,
    )
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, msg = flash
        cls = "flash err" if kind == "err" else "flash"
        st.markdown(f'<div class="{cls}">{esc(msg)}</div>', unsafe_allow_html=True)


def needs_human(row: dict[str, Any]) -> bool:
    """A human must look at it: escalated, low confidence, or an agent failure record."""
    return row["escalate"] or row["confidence"] < LOW_CONFIDENCE or "agent error" in row["escalation_reason"]


def render_kpis(rows: list[dict[str, Any]]) -> None:
    """Five KPI cards."""
    total = len(rows)
    escalated = sum(r["escalate"] for r in rows)
    high = sum(r["priority"] == "high" for r in rows)
    avg_conf = sum(r["confidence"] for r in rows) / total if total else 0.0
    human = sum(needs_human(r) for r in rows)
    cards = [
        ("Total emails", str(total), "in outbox.json", ""),
        ("Escalated", str(escalated), f"{(escalated / total * 100 if total else 0):.0f}% of total", "danger"),
        ("High priority", str(high), "priority = high", ""),
        ("Avg confidence", f"{avg_conf:.2f}", "0 to 1", "accent"),
        ("Needs human", str(human), f"escalated or conf < {LOW_CONFIDENCE}", ""),
    ]
    cols = st.columns(len(cards))
    for col, (label, value, hint, cls) in zip(cols, cards):
        col.markdown(
            f'<div class="kpi {cls}"><div class="lbl">{esc(label)}</div>'
            f'<div class="val">{esc(value)}</div><div class="hint">{esc(hint)}</div></div>',
            unsafe_allow_html=True,
        )


def _style_fig(fig: go.Figure, height: int = 290) -> go.Figure:
    """Apply the dark, minimal chart style."""
    fig.update_layout(
        height=height,
        margin=dict(l=6, r=6, t=6, b=6),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=MUTED, size=12),
        showlegend=False,
        bargap=0.38,
        barcornerradius=6,
        hoverlabel=dict(bgcolor="#181C25", bordercolor="#232836", font=dict(color=TEXT, family=FONT)),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def _chart_card(title: str, fig: go.Figure | None, key: str) -> None:
    """Render a chart inside a titled card, or an empty state."""
    with st.container(key=f"chartcard_{key}"):
        st.markdown(f'<div class="card-title">{esc(title)}</div>', unsafe_allow_html=True)
        if fig is None:
            st.markdown('<div class="muted">No data yet.</div>', unsafe_allow_html=True)
        else:
            st.plotly_chart(fig, theme=None, key=key, config={"displayModeBar": False})


def render_charts(rows: list[dict[str, Any]]) -> None:
    """Category, priority and policy-code usage charts."""
    c1, c2, c3 = st.columns([1.1, 0.8, 1.3])
    with c1:
        counts = Counter(r["category"] for r in rows).most_common()
        fig = None
        if counts:
            labels = [c for c, _ in counts][::-1]
            values = [n for _, n in counts][::-1]
            fig = _style_fig(go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color=ACCENT,
                                              hovertemplate="%{y}: %{x}<extra></extra>")))
        _chart_card("Category distribution", fig, "cat_chart")
    with c2:
        pcount = Counter(r["priority"] for r in rows)
        labels = [p for p in PRIORITY_ORDER if pcount.get(p)] + sorted(p for p in pcount if p not in PRIORITY_ORDER)
        fig = None
        if labels:
            colors = [DANGER if p == "high" else ACCENT if p == "medium" else "#4B5168" for p in labels]
            fig = _style_fig(go.Figure(go.Bar(x=labels, y=[pcount[p] for p in labels], marker_color=colors,
                                              hovertemplate="%{x}: %{y}<extra></extra>")))
        _chart_card("Priority distribution", fig, "prio_chart")
    with c3:
        refs = Counter(code for r in rows for code in r["policy_refs"])
        fig = None
        if refs:
            codes = sorted(refs, key=lambda c: (-refs[c], c))
            colors = [DANGER if c.startswith("ESC-") else ACCENT for c in codes]
            fig = _style_fig(go.Figure(go.Bar(x=codes, y=[refs[c] for c in codes], marker_color=colors,
                                              hovertemplate="%{x}: cited %{y}x<extra></extra>")))
        _chart_card("Policy code usage", fig, "refs_chart")


def esc_codes(row: dict[str, Any]) -> list[str]:
    """ESC-* codes from policy_refs, plus any mentioned in the escalation reason."""
    codes = [c for c in row["policy_refs"] if c.startswith("ESC-")]
    codes += [c for c in ESC_RE.findall(row["escalation_reason"]) if c not in codes]
    return codes


def render_escalation_queue(rows: list[dict[str, Any]], inbox: dict[str, dict[str, Any]]) -> None:
    """Red-accented list of escalated emails, high priority first."""
    queue = [r for r in rows if r["escalate"]]
    section(f"Escalation queue · {len(queue)}", danger=True)
    if not queue:
        st.markdown('<div class="card muted">Nothing escalated.</div>', unsafe_allow_html=True)
        return
    rank = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    queue.sort(key=lambda r: (rank.get(r["priority"], 9), r["email_id"]))
    parts = []
    for r in queue:
        email = inbox.get(r["email_id"], {})
        codes = esc_codes(r)
        code_badges = "".join(f'<span class="bdg danger code">{esc(c)}</span>' for c in codes) or '<span class="bdg">no ESC code</span>'
        parts.append(
            f'<div class="esc"><div class="top"><div><span class="id">{esc(r["email_id"])}</span>'
            f'<span class="subj">{esc(email.get("subject") or "(no subject)")}</span>'
            f'<span class="muted"> · {esc(email.get("from_name") or "unknown sender")}</span></div>'
            f'<div>{code_badges}<span class="bdg">{esc(r["priority"])}</span></div></div>'
            f'<div class="reason">{esc(r["escalation_reason"] or "No reason given.")}</div></div>'
        )
    st.markdown('<div style="max-height:420px;overflow:auto;padding-right:4px">' + "".join(parts) + "</div>",
                unsafe_allow_html=True)


def filter_rows(rows: list[dict[str, Any]], inbox: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter controls + filtering logic for the main table."""
    c1, c2, c3, c4 = st.columns([1.2, 1, 0.8, 1.6])
    cats = sorted({r["category"] for r in rows})
    prios = [p for p in PRIORITY_ORDER if any(r["priority"] == p for r in rows)]
    prios += sorted({r["priority"] for r in rows} - set(prios))
    sel_cats = c1.multiselect("Category", cats, placeholder="All categories")
    sel_prios = c2.multiselect("Priority", prios, placeholder="All priorities")
    sel_esc = c3.selectbox("Escalate", ["All", "Yes", "No"])
    query = c4.text_input("Search", placeholder="id, subject, sender, reply, notes, code…").strip().lower()

    out = []
    for r in rows:
        if sel_cats and r["category"] not in sel_cats:
            continue
        if sel_prios and r["priority"] not in sel_prios:
            continue
        if sel_esc != "All" and r["escalate"] != (sel_esc == "Yes"):
            continue
        if query:
            email = inbox.get(r["email_id"], {})
            hay = " ".join([
                r["email_id"], r["category"], r["reply_draft"], r["agent_notes"], r["escalation_reason"],
                " ".join(r["policy_refs"]), str(email.get("subject", "")), str(email.get("from_name", "")),
                str(email.get("from_email", "")), str(email.get("body", "")),
            ]).lower()
            if query not in hay:
                continue
        out.append(r)
    return out


def _priority_badge(priority: str) -> str:
    """Badge HTML for a priority value."""
    cls = "bdg danger" if priority == "high" else "bdg accent" if priority == "medium" else "bdg"
    return f'<span class="{cls}">{esc(priority)}</span>'


def render_table(rows: list[dict[str, Any]], inbox: dict[str, dict[str, Any]]) -> None:
    """Custom HTML table (keeps the dark look regardless of the Streamlit theme)."""
    if not rows:
        st.markdown('<div class="card muted">No emails match these filters.</div>', unsafe_allow_html=True)
        return
    body = []
    for r in rows:
        email = inbox.get(r["email_id"], {})
        refs = "".join(
            f'<span class="bdg code {"danger" if c.startswith("ESC-") else ""}">{esc(c)}</span>' for c in r["policy_refs"]
        ) or '<span class="muted">none</span>'
        esc_cell = '<span class="bdg danger">yes</span>' if r["escalate"] else '<span class="muted">no</span>'
        low = " low" if r["confidence"] < LOW_CONFIDENCE else ""
        conf = (f'<div class="conf{low}"><div class="track"><div class="fill" style="width:{r["confidence"] * 100:.0f}%"></div></div>'
                f'{r["confidence"]:.2f}</div>')
        body.append(
            f'<tr><td><b>{esc(r["email_id"])}</b></td>'
            f'<td>{esc(email.get("subject") or "(not in inbox)")}<div class="muted">{esc(email.get("from_name", ""))}</div></td>'
            f'<td><span class="bdg accent">{esc(r["category"])}</span></td>'
            f'<td>{_priority_badge(r["priority"])}</td><td>{esc_cell}</td><td>{refs}</td><td>{conf}</td></tr>'
        )
    st.markdown(
        '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>ID</th><th>Subject / sender</th><th>Category</th>'
        '<th>Priority</th><th>Escalate</th><th>Policy refs</th><th>Confidence</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="muted" style="margin-top:.4rem">{len(rows)} email(s) shown</div>', unsafe_allow_html=True)


def _timeline_html(steps: list[dict[str, str]]) -> str:
    """Vertical step timeline."""
    items = []
    for s in steps:
        kind = s["kind"] if s["kind"] in STEP_ORDER else "ACTION"
        items.append(
            f'<div class="st {kind}"><span class="kind">{esc(s["kind"])}</span><span class="ts">{esc(s["ts"])}</span>'
            f'<div class="txt">{esc(s["text"])}</div></div>'
        )
    return '<div class="tl">' + "".join(items) + "</div>"


def render_detail(
    rows: list[dict[str, Any]],
    inbox: dict[str, dict[str, Any]],
    rules: dict[str, str],
    trace: dict[str, list[dict[str, str]]],
    trace_source: str,
) -> None:
    """Detail view for one email: original, cited rules, reply draft, notes and step timeline."""
    if not rows:
        return
    labels = {r["email_id"]: f'{r["email_id"]} · {inbox.get(r["email_id"], {}).get("subject") or "(no subject)"}' for r in rows}
    chosen = st.selectbox("Select an email", list(labels), format_func=lambda i: labels[i])
    row = next(r for r in rows if r["email_id"] == chosen)
    email = inbox.get(chosen, {})

    sender = email.get("from_name") or "Unknown sender"
    addr = f' &lt;{esc(email["from_email"])}&gt;' if email.get("from_email") else ""
    badges = (f'<span class="bdg accent">{esc(row["category"])}</span>{_priority_badge(row["priority"])}'
              + ('<span class="bdg danger">escalated</span>' if row["escalate"] else "")
              + f'<span class="bdg">confidence {row["confidence"]:.2f}</span>')
    st.markdown(
        f'<div class="card"><div style="font-size:1.15rem;font-weight:650">{esc(email.get("subject") or "(no subject)")}</div>'
        f'<div class="muted" style="margin:.2rem 0 .6rem">From {esc(sender)}{addr} · {esc(email.get("received_at", ""))}</div>'
        f'{badges}</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.25, 1])
    with left:
        st.markdown(f'<div class="card"><h4>Reply draft (not sent)</h4><div class="reply">'
                    f'{esc(row["reply_draft"] or "No draft.")}</div></div>', unsafe_allow_html=True)
        notes = esc(row["agent_notes"] or "No notes.")
        reason = (f'<div style="margin-top:.6rem"><span class="bdg danger">escalation reason</span> {esc(row["escalation_reason"])}</div>'
                  if row["escalate"] else "")
        st.markdown(f'<div class="card"><h4>Agent notes</h4><div>{notes}</div>{reason}</div>', unsafe_allow_html=True)
        with st.expander("Original email body"):
            st.markdown(f'<div class="body">{esc(email.get("body") or "(email file not found in data/inbox)")}</div>',
                        unsafe_allow_html=True)
    with right:
        cited = []
        for code in row["policy_refs"]:
            cls = "rule esc-rule" if code.startswith("ESC-") else "rule"
            text = rules.get(code, "Code not found in data/policy.md.")
            cited.append(f'<div class="{cls}"><span class="c">{esc(code)}</span>{esc(text)}</div>')
        st.markdown('<div class="card"><h4>Policy rules cited</h4>'
                    + ("".join(cited) or '<div class="muted">No policy codes cited.</div>') + "</div>",
                    unsafe_allow_html=True)
        steps = trace.get(chosen, [])
        timeline = _timeline_html(steps) if steps else '<div class="muted">No trace recorded for this email yet.</div>'
        st.markdown(f'<div class="card"><h4>Agent steps</h4>{timeline}'
                    f'<div class="muted" style="margin-top:.4rem;font-size:.75rem">Source: {esc(trace_source)}</div></div>',
                    unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> None:
    """Build the page. Every data source is optional; missing files show empty states."""
    st.set_page_config(page_title="Helpdesk Triage · Teen Haseen", page_icon="✉️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    rows, outbox_warning = load_outbox()
    inbox = load_inbox()
    render_sidebar(inbox, rows)
    render_header()
    handle_pending_run()

    if outbox_warning:
        st.markdown(f'<div class="flash err">{esc(outbox_warning)}</div>', unsafe_allow_html=True)

    st.write("")
    render_kpis(rows)
    section("Overview")
    render_charts(rows)
    render_escalation_queue(rows, inbox)

    section("All emails")
    filtered = filter_rows(rows, inbox)
    render_table(filtered, inbox)

    section("Email detail")
    if filtered:
        trace, trace_source = load_trace()
        render_detail(filtered, inbox, load_policy_rules(), trace, trace_source)
    else:
        st.markdown('<div class="card muted">Pick filters that match at least one email.</div>', unsafe_allow_html=True)


main()
