"""Real Gmail Mode — separate control room for live inbox triage.

Drafts only. Never sends. Uses gmail.modify (no gmail.send).

Opened from the main app sidebar (pages) or:
    streamlit run dashboard.py
then choose **Real Gmail Mode**.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gmail_bridge import (  # noqa: E402
    GMAIL_OUTBOX_PATH,
    GMAIL_TRACE_PATH,
    connect_gmail,
    gmail_status,
    load_gmail_outbox,
    preview_inbox,
    process_gmail_batch,
)

TEAM_NAME = "Teen Haseen"
INK = "#0B1F2A"
INK_SOFT = "#143447"
MIST = "#E8F1F4"
SEA = "#0F766E"
SEA_SOFT = "rgba(15,118,110,0.14)"
CORAL = "#E11D48"
CORAL_SOFT = "rgba(225,29,72,0.12)"
AMBER = "#D97706"
TEXT = "#0F172A"
MUTED = "#5B6B76"
FONT = "Figtree, 'Segoe UI', system-ui, sans-serif"
DISPLAY = "Sora, Figtree, system-ui, sans-serif"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Sora:wght@500;600;700&display=swap');

:root {{
  --ink: {INK}; --ink-soft: {INK_SOFT}; --mist: {MIST};
  --sea: {SEA}; --sea-soft: {SEA_SOFT}; --coral: {CORAL}; --coral-soft: {CORAL_SOFT};
  --amber: {AMBER}; --text: {TEXT}; --muted: {MUTED};
}}

@keyframes th-fade-up {{
  from {{ opacity: 0; transform: translateY(12px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes th-pulse-dot {{
  0%, 100% {{ box-shadow: 0 0 0 0 rgba(52,211,153,0.55); }}
  50% {{ box-shadow: 0 0 0 7px rgba(52,211,153,0); }}
}}

html, body, .stApp, [data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(900px 420px at 8% -10%, rgba(15,118,110,0.20), transparent 55%),
    radial-gradient(700px 380px at 100% 0%, rgba(225,29,72,0.10), transparent 50%),
    linear-gradient(180deg, #F4FAFB 0%, {MIST} 45%, #E3EEF2 100%) !important;
  color: var(--text);
  font-family: {FONT};
}}
.stApp, .stApp p, .stApp li {{ color: var(--text); }}
header[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, {INK} 0%, {INK_SOFT} 100%) !important;
}}
[data-testid="stSidebar"] * {{ color: #E8F1F4 !important; }}
[data-testid="stSidebar"] .stButton > button {{
  background: rgba(255,255,255,0.08) !important;
  color: #F8FAFC !important;
  border: 1px solid rgba(255,255,255,0.14) !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
  background: {SEA} !important;
  border-color: transparent !important;
}}

.g-hero {{
  animation: th-fade-up .55s ease both;
  padding: 1.35rem 1.5rem 1.2rem;
  border-radius: 1.15rem;
  background:
    linear-gradient(135deg, rgba(11,31,42,0.96) 0%, rgba(20,52,71,0.94) 55%, rgba(15,118,110,0.55) 140%);
  color: #F8FAFC;
  box-shadow: 0 18px 40px rgba(11,31,42,0.22);
  margin-bottom: 1.1rem;
}}
.g-hero h1 {{
  font-family: {DISPLAY};
  font-size: 1.85rem;
  margin: 0 0 .35rem;
  letter-spacing: -0.02em;
  color: #F8FAFC;
}}
.g-hero p {{ margin: 0; color: rgba(232,241,244,0.82); font-size: .95rem; max-width: 42rem; }}
.g-pill {{
  display: inline-flex; align-items: center; gap: .4rem;
  padding: .28rem .7rem; border-radius: 999px;
  background: rgba(255,255,255,0.1); font-size: .72rem;
  letter-spacing: .06em; text-transform: uppercase; margin-bottom: .75rem;
}}
.g-dot {{
  width: .55rem; height: .55rem; border-radius: 50%;
  background: #34D399; animation: th-pulse-dot 1.8s ease infinite;
}}
.g-dot.off {{ background: #F87171; animation: none; }}

.card {{
  animation: th-fade-up .45s ease both;
  background: rgba(255,255,255,0.78);
  border: 1px solid rgba(15,35,45,0.08);
  border-radius: 1rem;
  padding: 1rem 1.1rem;
  margin-bottom: .85rem;
  box-shadow: 0 8px 24px rgba(11,31,42,0.05);
}}
.card h4 {{
  margin: 0 0 .55rem; font-family: {DISPLAY}; font-size: .95rem; color: var(--ink);
}}
.muted {{ color: var(--muted); font-size: .85rem; }}
.kpi-row {{
  display: grid; grid-template-columns: repeat(4, 1fr); gap: .75rem; margin-bottom: 1rem;
}}
@media (max-width: 900px) {{
  .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
}}
.kpi {{
  animation: th-fade-up .5s ease both;
  background: rgba(255,255,255,0.85);
  border-radius: .95rem;
  padding: .95rem 1rem;
  border: 1px solid rgba(15,35,45,0.07);
}}
.kpi .label {{
  font-size: .68rem; letter-spacing: .1em; text-transform: uppercase; color: var(--muted);
}}
.kpi .value {{
  font-family: {DISPLAY}; font-size: 1.65rem; color: var(--ink); margin-top: .15rem;
}}
.badge {{
  display: inline-block; padding: .15rem .5rem; border-radius: 999px;
  font-size: .72rem; font-weight: 600;
}}
.badge.ok {{ background: var(--sea-soft); color: var(--sea); }}
.badge.warn {{ background: rgba(217,119,6,0.14); color: var(--amber); }}
.badge.bad {{ background: var(--coral-soft); color: var(--coral); }}
.mail-row {{
  display: grid; grid-template-columns: 1.1fr 1.4fr .7fr .7fr .9fr;
  gap: .6rem; padding: .7rem 0; border-bottom: 1px solid rgba(15,35,45,0.06);
  font-size: .88rem;
}}
.mail-row:last-child {{ border-bottom: none; }}
.flash {{
  padding: .75rem 1rem; border-radius: .85rem; margin-bottom: .9rem;
  background: var(--sea-soft); color: var(--sea); border: 1px solid rgba(15,118,110,0.2);
}}
.flash.err {{
  background: var(--coral-soft); color: var(--coral); border-color: rgba(225,29,72,0.22);
}}
.setup-step {{
  display: flex; gap: .75rem; margin-bottom: .7rem; align-items: flex-start;
}}
.setup-num {{
  flex: 0 0 1.6rem; height: 1.6rem; border-radius: 50%;
  background: var(--sea); color: white; display: flex; align-items: center;
  justify-content: center; font-size: .75rem; font-weight: 700;
}}
</style>
"""


def section(title: str) -> None:
    st.markdown(
        f'<div style="font-family:{DISPLAY};font-size:1.05rem;font-weight:600;'
        f'color:{INK};margin:.4rem 0 .65rem">{esc(title)}</div>',
        unsafe_allow_html=True,
    )


def render_status_card(status: dict[str, Any]) -> None:
    ready = bool(status.get("ready"))
    can = bool(status.get("can_connect"))
    email = str(status.get("connected_email") or "").strip()
    if ready:
        badge = '<span class="badge ok">Connected</span>'
        dot = "g-dot"
        line = (
            f"Signed in as <b>{esc(email)}</b>."
            if email
            else "OAuth token is valid. Ready to fetch and draft."
        )
    elif can:
        badge = '<span class="badge warn">Connect once</span>'
        dot = "g-dot off"
        line = "credentials.json found — click Connect to authorize (browser)."
    else:
        badge = '<span class="badge bad">Setup needed</span>'
        dot = "g-dot off"
        line = "Place OAuth Desktop credentials.json in the project root."

    st.markdown(
        f'<div class="card"><h4>Gmail connection {badge}</h4>'
        f'<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.35rem">'
        f'<span class="{dot}"></span><span class="muted">{line}</span></div>'
        f'<div class="muted">Scope: gmail.modify only · drafts never send<br>'
        f'Account: <code>{esc(email or "—")}</code><br>'
        f'Credentials: {"yes" if status.get("credentials_present") else "no"} · '
        f'Token: {esc(status.get("token_detail"))}<br>'
        f'Default query: <code>{esc(status.get("default_query"))}</code><br>'
        f'To switch account: delete <code>token.json</code>, then Connect again '
        f"and pick the Gmail you want in the browser.</div></div>",
        unsafe_allow_html=True,
    )


def render_setup() -> None:
    st.markdown(
        '<div class="card"><h4>First-time setup</h4>'
        '<div class="setup-step"><div class="setup-num">1</div>'
        "<div>Google Cloud Console → enable <b>Gmail API</b> → create OAuth "
        "<b>Desktop</b> client → download JSON as <code>credentials.json</code> "
        "in the project root.</div></div>"
        '<div class="setup-step"><div class="setup-num">2</div>'
        "<div>Click <b>Connect Gmail</b> below. A browser window opens once; "
        "<code>token.json</code> is saved locally (gitignored).</div></div>"
        '<div class="setup-step"><div class="setup-num">3</div>'
        "<div>Preview unread mail, then <b>Triage &amp; draft</b>. Replies appear "
        "as Gmail <b>Drafts</b> in the same thread — you review and send manually.</div></div>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_kpis(payload: dict[str, Any]) -> None:
    results = payload.get("results") or []
    n = int(payload.get("count") or len(results))
    drafts = int(payload.get("drafts_created") or 0)
    esc_n = int(payload.get("escalated") or sum(1 for r in results if r.get("escalate")))
    errs = int(payload.get("errors") or sum(1 for r in results if r.get("error")))
    st.markdown(
        f'<div class="kpi-row">'
        f'<div class="kpi"><div class="label">Processed</div><div class="value">{n}</div></div>'
        f'<div class="kpi"><div class="label">Drafts created</div><div class="value">{drafts}</div></div>'
        f'<div class="kpi"><div class="label">Escalated</div><div class="value">{esc_n}</div></div>'
        f'<div class="kpi"><div class="label">Errors</div><div class="value">{errs}</div></div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_results_table(results: list[dict[str, Any]]) -> None:
    if not results:
        st.markdown(
            '<div class="card muted">No Gmail run yet. Preview or triage from the sidebar.</div>',
            unsafe_allow_html=True,
        )
        return
    header = (
        '<div class="card"><h4>Last run</h4>'
        '<div class="mail-row" style="font-weight:600;color:var(--muted);font-size:.72rem;'
        'letter-spacing:.06em;text-transform:uppercase">'
        "<div>From</div><div>Subject</div><div>Category</div>"
        "<div>Priority</div><div>Draft</div></div>"
    )
    rows_html = []
    for r in results:
        draft = r.get("draft_id") or "—"
        if r.get("error"):
            draft = f"ERR"
        draft_short = esc(str(draft)[:18])
        badge = ""
        if r.get("escalate"):
            badge = ' <span class="badge bad">esc</span>'
        rows_html.append(
            '<div class="mail-row">'
            f'<div>{esc(r.get("from_name") or r.get("from_email"))}</div>'
            f'<div>{esc(r.get("subject"))}{badge}</div>'
            f'<div>{esc(r.get("category") or "—")}</div>'
            f'<div>{esc(r.get("priority") or "—")}</div>'
            f"<div>{draft_short}</div>"
            "</div>"
        )
    st.markdown(header + "".join(rows_html) + "</div>", unsafe_allow_html=True)


def render_detail(results: list[dict[str, Any]]) -> None:
    if not results:
        return
    ids = [str(r.get("email_id") or f"row-{i}") for i, r in enumerate(results)]
    choice = st.selectbox("Inspect message", ids, key="gmail_detail_id")
    row = next((r for r in results if str(r.get("email_id")) == choice), results[0])
    conf = row.get("confidence")
    conf_s = f"{float(conf):.2f}" if conf is not None else "—"
    st.markdown(
        f'<div class="card"><h4>{esc(row.get("subject"))}</h4>'
        f'<div class="muted">{esc(row.get("from_name"))} &lt;{esc(row.get("from_email"))}&gt;<br>'
        f'Category {esc(row.get("category"))} · Priority {esc(row.get("priority"))} · '
        f'Confidence {esc(conf_s)} · Escalate {esc(row.get("escalate"))}<br>'
        f'Gmail draft id: {esc(row.get("draft_id") or "—")}</div></div>',
        unsafe_allow_html=True,
    )
    if row.get("error"):
        st.markdown(
            f'<div class="flash err">{esc(row.get("error"))}</div>',
            unsafe_allow_html=True,
        )
    if row.get("reason"):
        st.markdown(
            f'<div class="card"><h4>Reason</h4><div>{esc(row.get("reason"))}</div></div>',
            unsafe_allow_html=True,
        )
    draft = str(row.get("draft_reply") or row.get("reply_draft") or "").strip()
    if draft:
        st.markdown(
            '<div class="card"><h4>Draft reply</h4>'
            '<div class="muted">Also saved under Gmail → <b>Drafts</b> '
           "(and as a draft reply inside the thread).</div></div>",
            unsafe_allow_html=True,
        )
        st.code(draft, language=None)
    else:
        st.markdown(
            '<div class="flash err">No draft text stored for this row. '
            "Earlier runs had a bug (empty body). Uncheck Dry run and "
            "click <b>Triage &amp; create drafts</b> again.</div>",
            unsafe_allow_html=True,
        )


def load_trace_tail(n: int = 40) -> list[dict[str, Any]]:
    if not GMAIL_TRACE_PATH.is_file():
        return []
    lines = GMAIL_TRACE_PATH.read_text(encoding="utf-8").splitlines()[-n:]
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> None:
    st.set_page_config(
        page_title=f"Real Gmail Mode · {TEAM_NAME}",
        page_icon="📬",
        layout="wide",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    status = gmail_status()
    payload = load_gmail_outbox()
    results: list[dict[str, Any]] = list(payload.get("results") or [])

    with st.sidebar:
        st.markdown(
            f"**{TEAM_NAME}**  \n"
            "Real Gmail Mode · drafts only"
        )
        st.caption("Nothing is ever sent. You review drafts in Gmail.")

        limit = st.number_input("Max emails", min_value=1, max_value=30, value=5, step=1)
        custom_q = st.text_input(
            "Gmail query (optional)",
            value="",
            placeholder="leave blank for default unread filter",
        )
        dry_run = st.checkbox("Dry run (triage only, no drafts)", value=False)

        if st.button("Connect Gmail", type="primary", key="btn_gmail_connect"):
            try:
                connect_gmail()
                from gmail_bridge import connected_gmail_address

                addr = connected_gmail_address() or "Gmail"
                st.session_state["gmail_flash"] = (
                    "ok",
                    f"Connected as {addr}. Token saved.",
                )
            except Exception as exc:  # noqa: BLE001
                st.session_state["gmail_flash"] = (
                    "err",
                    f"Connect failed: {type(exc).__name__}: {exc}",
                )
            st.rerun()

        if st.button("Switch account (re-auth)", key="btn_gmail_switch"):
            try:
                from src.config import TOKEN_PATH

                if TOKEN_PATH.is_file():
                    TOKEN_PATH.unlink()
                connect_gmail()
                from gmail_bridge import connected_gmail_address

                addr = connected_gmail_address() or "Gmail"
                st.session_state["gmail_flash"] = (
                    "ok",
                    f"Switched. Now connected as {addr}.",
                )
            except Exception as exc:  # noqa: BLE001
                st.session_state["gmail_flash"] = (
                    "err",
                    f"Switch failed: {type(exc).__name__}: {exc}",
                )
            st.rerun()

        if st.button("Preview inbox", key="btn_gmail_preview"):
            try:
                with st.spinner("Fetching from Gmail…"):
                    preview = preview_inbox(
                        limit=int(limit),
                        query=custom_q.strip() or None,
                    )
                # Must not share a key with any widget (btn_gmail_preview).
                st.session_state["gmail_preview_rows"] = preview
                st.session_state["gmail_flash"] = (
                    "ok",
                    f"Previewed {len(preview)} message(s). No drafts created.",
                )
            except Exception as exc:  # noqa: BLE001
                st.session_state["gmail_flash"] = (
                    "err",
                    f"Preview failed: {type(exc).__name__}: {exc}",
                )
            st.rerun()

        if st.button("Triage & create drafts", type="primary", key="btn_gmail_run"):
            try:
                with st.spinner("Triaging with helpdesk agent…"):
                    payload = process_gmail_batch(
                        limit=int(limit),
                        query=custom_q.strip() or None,
                        dry_run=bool(dry_run),
                    )
                tip = (
                    " (dry run — nothing in Gmail Drafts)"
                    if dry_run
                    else " · open Gmail → Drafts, or open each thread"
                )
                st.session_state["gmail_flash"] = (
                    "ok",
                    f"Processed {payload.get('count', 0)} · "
                    f"drafts {payload.get('drafts_created', 0)} · "
                    f"escalated {payload.get('escalated', 0)}{tip}",
                )
            except Exception as exc:  # noqa: BLE001
                st.session_state["gmail_flash"] = (
                    "err",
                    f"Run failed: {type(exc).__name__}: {exc}",
                )
            st.rerun()

        if st.button("Refresh status", key="btn_gmail_refresh"):
            st.rerun()

        st.divider()
        st.caption(f"Results → `{GMAIL_OUTBOX_PATH.name}`")
        st.caption("Uncheck Dry run to write real Gmail drafts.")
        st.caption("JSON inbox mode stays on the Home page.")

    # Hero
    ready = bool(status.get("ready"))
    st.markdown(
        f'<div class="g-hero">'
        f'<div class="g-pill"><span class="{"g-dot" if ready else "g-dot off"}"></span>'
        f'Real Gmail Mode</div>'
        f"<h1>{esc(TEAM_NAME)}</h1>"
        f"<p>Live inbox → same helpdesk agent loop → Gmail <b>drafts</b> in-thread. "
        f"You stay in control — nothing is sent automatically.</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    flash = st.session_state.pop("gmail_flash", None)
    if flash:
        kind, msg = flash
        cls = "flash err" if kind == "err" else "flash"
        st.markdown(f'<div class="{cls}">{esc(msg)}</div>', unsafe_allow_html=True)

    col_a, col_b = st.columns([1.05, 1])
    with col_a:
        render_status_card(status)
        if not status.get("credentials_present"):
            render_setup()
    with col_b:
        run_at = payload.get("run_at") or "—"
        st.markdown(
            f'<div class="card"><h4>Safety</h4>'
            f'<div class="muted">Scope is <code>gmail.modify</code> only. '
            f"This mode calls <code>users.drafts.create</code> — never "
            f"<code>users.messages.send</code>. Last run: {esc(run_at)}</div></div>",
            unsafe_allow_html=True,
        )
        if payload.get("run_at"):
            render_kpis(payload)

    tab_run, tab_preview, tab_detail, tab_trace = st.tabs(
        ["Last run", "Inbox preview", "Message detail", "Agent trace"]
    )

    with tab_run:
        section("Gmail triage results")
        # Reload in case a run just finished
        payload = load_gmail_outbox()
        results = list(payload.get("results") or [])
        empty_bodies = sum(
            1
            for r in results
            if r.get("draft_id")
            and not str(r.get("draft_id")).startswith("(")
            and not str(r.get("draft_reply") or r.get("reply_draft") or "").strip()
        )
        if empty_bodies:
            st.markdown(
                f'<div class="flash err">This last run stored {empty_bodies} empty '
                "draft body(ies) (fixed now). Uncheck <b>Dry run</b>, then "
                "<b>Triage &amp; create drafts</b> again. In Gmail open "
                "<b>Drafts</b> — older empty drafts can be deleted.</div>",
                unsafe_allow_html=True,
            )
        render_results_table(results)

    with tab_preview:
        section("Unread / matching messages")
        preview = st.session_state.get("gmail_preview_rows") or []
        if not preview:
            st.markdown(
                '<div class="card muted">Click <b>Preview inbox</b> in the sidebar.</div>',
                unsafe_allow_html=True,
            )
        else:
            for item in preview:
                st.markdown(
                    f'<div class="card"><h4>{esc(item.get("subject"))}</h4>'
                    f'<div class="muted">{esc(item.get("from_name"))} · '
                    f'{esc(item.get("from_email"))} · {esc(item.get("received_at"))}</div>'
                    f'<div style="margin-top:.5rem;white-space:pre-wrap;font-size:.88rem">'
                    f'{esc((item.get("body") or "")[:600])}'
                    f'{"…" if len(item.get("body") or "") > 600 else ""}</div></div>',
                    unsafe_allow_html=True,
                )

    with tab_detail:
        section("Draft & decision")
        render_detail(results)

    with tab_trace:
        section("PLAN → ACTION → OBSERVATION → DECISION")
        steps = load_trace_tail()
        if not steps:
            st.markdown(
                '<div class="card muted">Trace appears after a triage run '
                f"(<code>{esc(GMAIL_TRACE_PATH.name)}</code>).</div>",
                unsafe_allow_html=True,
            )
        else:
            for step in reversed(steps[-30:]):
                st.markdown(
                    f'<div class="card" style="padding:.65rem .9rem;margin-bottom:.45rem">'
                    f'<b>{esc(step.get("email_id"))}</b> · '
                    f'<span class="badge ok">{esc(step.get("step"))}</span> '
                    f'<span class="muted">{esc(step.get("detail"))}</span></div>',
                    unsafe_allow_html=True,
                )


main()
