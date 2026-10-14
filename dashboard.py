"""Streamlit control room for the Student Helpdesk Triage Agent.

Reads outbox.json, data/inbox, data/policy.md and logs/trace.jsonl.
Runs agent.py as a subprocess (drafts only — nothing is sent).

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
LOG_TAIL_LINES = 28
SHOWCASE_IDS = ["E005", "E010", "E013"]
DEMO_LIMIT = 5

# Ink + teal + coral — not purple-on-dark AI chrome
INK = "#0B1F2A"
INK_SOFT = "#143447"
MIST = "#E8F1F4"
FOG = "#D3E4EA"
SEA = "#0F766E"
SEA_SOFT = "rgba(15,118,110,0.14)"
CORAL = "#E11D48"
CORAL_SOFT = "rgba(225,29,72,0.12)"
AMBER = "#D97706"
TEXT = "#0F172A"
MUTED = "#5B6B76"
GRID = "rgba(15,35,45,0.08)"
FONT = "Figtree, 'Segoe UI', system-ui, sans-serif"
DISPLAY = "Sora, Figtree, system-ui, sans-serif"

STEP_ORDER = ("PLAN", "ACTION", "OBSERVATION", "DECISION")
PRIORITY_ORDER = ("high", "medium", "low")
CODE_RE = re.compile(r"^\s*([A-Z]{2,}-\d+)\s*:\s*(.+?)\s*$")
ESC_RE = re.compile(r"\bESC-\d+\b")
LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\w+\s+(.*)$"
)

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Sora:wght@500;600;700&display=swap');

:root {{
  --ink: {INK}; --ink-soft: {INK_SOFT}; --mist: {MIST}; --fog: {FOG};
  --sea: {SEA}; --sea-soft: {SEA_SOFT}; --coral: {CORAL}; --coral-soft: {CORAL_SOFT};
  --amber: {AMBER}; --text: {TEXT}; --muted: {MUTED};
}}

/* Premium motion — presence, not noise */
@keyframes th-fade-up {{
  from {{ opacity: 0; transform: translateY(14px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes th-fade-in {{
  from {{ opacity: 0; }}
  to {{ opacity: 1; }}
}}
@keyframes th-hero-glow {{
  0%, 100% {{ opacity: 0.55; transform: scale(1); }}
  50% {{ opacity: 0.9; transform: scale(1.06); }}
}}
@keyframes th-pulse-dot {{
  0%, 100% {{ box-shadow: 0 0 0 0 rgba(52,211,153,0.55); }}
  50% {{ box-shadow: 0 0 0 7px rgba(52,211,153,0); }}
}}
@keyframes th-bar-grow {{
  from {{ transform: scaleX(0); }}
  to {{ transform: scaleX(1); }}
}}
@keyframes th-shimmer {{
  0% {{ background-position: 0% 50%; }}
  100% {{ background-position: 100% 50%; }}
}}
@keyframes th-timeline-in {{
  from {{ opacity: 0; transform: translateX(-8px); }}
  to {{ opacity: 1; transform: translateX(0); }}
}}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }}
}}

html, body, .stApp, [data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(900px 420px at 8% -10%, rgba(15,118,110,0.18), transparent 55%),
    radial-gradient(700px 380px at 100% 0%, rgba(225,29,72,0.08), transparent 50%),
    linear-gradient(180deg, #F4FAFB 0%, {MIST} 45%, #E3EEF2 100%) !important;
  color: var(--text);
  font-family: {FONT};
}}
/* Do NOT force every span to dark text — that kills hero pills / badges. */
.stApp, .stApp p, .stApp li {{ color: var(--text); }}
header[data-testid="stHeader"] {{ background: transparent !important; }}
#MainMenu, footer, .stDeployButton, [data-testid="stDecoration"] {{ display: none !important; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1380px; }}

/* Main-area widget labels (light background) */
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] .stMarkdown p {{
  color: #334155 !important;
}}

[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, {INK} 0%, {INK_SOFT} 100%) !important;
  border-right: 1px solid rgba(255,255,255,0.06);
}}
[data-testid="stSidebar"] .side-title,
[data-testid="stSidebar"] .side-hint,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span {{
  color: #E8F1F4 !important;
}}
[data-testid="stSidebar"] .side-hint,
[data-testid="stSidebar"] .muted {{ color: #A8C0CC !important; }}
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stSidebar"] [data-baseweb="base-input"],
[data-testid="stSidebar"] [data-baseweb="textarea"],
[data-testid="stSidebar"] .stTextInput input,
[data-testid="stSidebar"] .stTextArea textarea {{
  background: rgba(255,255,255,0.12) !important;
  color: #F4FAFB !important;
  border: 1px solid rgba(125,211,199,0.35) !important;
  border-radius: 12px !important;
}}
[data-testid="stSidebar"] input::placeholder,
[data-testid="stSidebar"] textarea::placeholder {{
  color: #9BB0BC !important; opacity: 1 !important;
}}

[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="base-input"],
[data-baseweb="textarea"], .stTextInput input, .stTextArea textarea {{
  background: #fff !important; color: #0F172A !important;
  border-color: #B7CBD4 !important; border-radius: 12px !important;
}}
[data-baseweb="select"] > div:focus-within, [data-baseweb="input"]:focus-within,
[data-baseweb="textarea"]:focus-within {{ border-color: var(--sea) !important; box-shadow: 0 0 0 3px var(--sea-soft); }}

.stButton > button, [data-testid="stFormSubmitButton"] > button {{
  width: 100%; border-radius: 12px; border: 1px solid rgba(255,255,255,0.14);
  background: rgba(255,255,255,0.06); color: #E8F1F4; font-weight: 600;
  font-family: {FONT};
  transition: transform .22s cubic-bezier(.22,1,.36,1), background .22s ease,
              box-shadow .22s ease, border-color .22s ease, filter .22s ease;
}}
.stButton > button:hover {{
  background: rgba(255,255,255,0.12); border-color: var(--sea);
  transform: translateY(-2px); box-shadow: 0 10px 22px rgba(0,0,0,0.18);
}}
.stButton > button:active {{ transform: translateY(0); }}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] {{
  background: linear-gradient(135deg, #0F766E, #14B8A6); border: none; color: #fff !important;
  background-size: 160% 160%;
}}
.stButton > button[kind="primary"]:hover {{
  filter: brightness(1.08); color: #fff !important;
  box-shadow: 0 12px 28px rgba(15,118,110,0.35);
}}
[data-testid="stForm"] {{
  border: 1px solid rgba(255,255,255,0.1); border-radius: 16px;
  background: rgba(0,0,0,0.18); padding: .4rem;
}}
[data-testid="stExpander"] details {{
  background: #fff; border: 1px solid #C5D5DC; border-radius: 14px;
}}
div[data-testid="stTabs"] button {{
  font-family: {DISPLAY}; font-weight: 600; color: var(--muted);
}}
div[data-testid="stTabs"] button[aria-selected="true"] {{
  color: var(--sea) !important;
}}

.brand {{
  display: grid; grid-template-columns: 1.4fr 1fr; gap: 1.2rem; align-items: stretch;
  margin-bottom: 1.1rem;
  animation: th-fade-up .7s cubic-bezier(.22,1,.36,1) both;
}}
@media (max-width: 900px) {{ .brand {{ grid-template-columns: 1fr; }} }}
.brand-hero {{
  position: relative; overflow: hidden; border-radius: 24px; padding: 1.6rem 1.8rem 1.5rem;
  background:
    linear-gradient(135deg, rgba(11,31,42,0.96), rgba(20,52,71,0.92)),
    radial-gradient(600px 240px at 90% 10%, rgba(20,184,166,0.35), transparent 60%);
  color: #F4FAFB; min-height: 168px;
  box-shadow: 0 18px 40px rgba(11,31,42,0.18);
  transition: transform .35s cubic-bezier(.22,1,.36,1), box-shadow .35s ease;
}}
.brand-hero:hover {{
  transform: translateY(-2px);
  box-shadow: 0 24px 48px rgba(11,31,42,0.24);
}}
.brand-hero::after {{
  content:""; position:absolute; inset:auto -20% -40% 40%; height:160px;
  background: radial-gradient(circle, rgba(225,29,72,0.25), transparent 70%);
  pointer-events:none;
  animation: th-hero-glow 5.5s ease-in-out infinite;
}}
.brand-hero::before {{
  content:""; position:absolute; inset:0; pointer-events:none; opacity:0.35;
  background: linear-gradient(110deg, transparent 30%, rgba(255,255,255,0.08) 48%, transparent 62%);
  background-size: 220% 100%;
  animation: th-shimmer 7s linear infinite;
}}
.brand-kicker {{
  font-size: .72rem; letter-spacing: .18em; text-transform: uppercase;
  color: #7DD3C7; font-weight: 700; margin-bottom: .55rem;
  animation: th-fade-in .8s ease both .15s;
}}
.brand-name {{
  font-family: {DISPLAY}; font-size: clamp(1.8rem, 3vw, 2.45rem); font-weight: 700;
  letter-spacing: -0.04em; line-height: 1.05; margin: 0;
  animation: th-fade-up .75s cubic-bezier(.22,1,.36,1) both .05s;
}}
.brand-tag {{
  margin-top: .55rem; max-width: 34rem; color: #B7CBD4; font-size: .95rem; line-height: 1.45;
  animation: th-fade-up .75s cubic-bezier(.22,1,.36,1) both .12s;
}}
.brand-meta {{
  margin-top: 1rem; display:flex; flex-wrap:wrap; gap: .5rem;
  animation: th-fade-up .75s cubic-bezier(.22,1,.36,1) both .2s;
}}
.brand-hero .pill,
.pill {{
  display:inline-flex !important; align-items:center; gap:.4rem; padding:.4rem .8rem;
  border-radius:999px; font-size:.72rem; font-weight:700; letter-spacing:.05em;
  border:1px solid rgba(125,211,199,0.45) !important;
  background: rgba(15,118,110,0.28) !important;
  color: #F4FAFB !important;
  transition: transform .2s ease, background .2s ease, border-color .2s ease;
}}
.brand-hero .pill:hover {{
  transform: translateY(-1px);
  background: rgba(20,184,166,0.38) !important;
  border-color: rgba(125,211,199,0.7) !important;
}}
.brand-hero .pill,
.brand-hero .pill * {{
  color: #F4FAFB !important;
}}
.pill .dot {{
  width:7px; height:7px; border-radius:50%; flex-shrink:0;
  background:#34D399 !important; box-shadow:0 0 10px #34D399;
  animation: th-pulse-dot 2.2s ease-out infinite;
}}
.brand-side {{
  border-radius: 24px; padding: 1.25rem 1.35rem;
  background: rgba(255,255,255,0.88); border: 1px solid #C9DCE3;
  backdrop-filter: blur(8px);
  animation: th-fade-up .75s cubic-bezier(.22,1,.36,1) both .18s;
  transition: transform .3s ease, box-shadow .3s ease;
}}
.brand-side:hover {{
  transform: translateY(-2px);
  box-shadow: 0 16px 36px rgba(11,31,42,0.08);
}}
.brand-side h3 {{
  font-family: {DISPLAY}; font-size: 1rem; margin: 0 0 .55rem; letter-spacing: -0.02em;
  color: #0B1F2A !important;
}}
.brand-side p {{ margin: 0; color: #5B6B76 !important; font-size: .86rem; line-height: 1.5; }}
.brand-side .steps {{
  margin-top: .85rem; display:grid; gap: .45rem;
}}
.brand-side .step {{
  display:flex; gap:.55rem; align-items:flex-start; font-size:.82rem;
  color: #334155 !important;
  animation: th-timeline-in .45s ease both;
  transition: transform .2s ease, background .2s ease;
  padding: .25rem .35rem; border-radius: 8px;
}}
.brand-side .step:nth-child(1) {{ animation-delay: .25s; }}
.brand-side .step:nth-child(2) {{ animation-delay: .35s; }}
.brand-side .step:nth-child(3) {{ animation-delay: .45s; }}
.brand-side .step:nth-child(4) {{ animation-delay: .55s; }}
.brand-side .step:hover {{ background: rgba(15,118,110,0.06); transform: translateX(3px); }}
.brand-side .step span {{ color: #334155 !important; }}
.brand-side .step b {{
  font-size:.68rem; letter-spacing:.08em; color: #0F766E !important; min-width: 4.6rem;
}}

.kpi {{
  background: rgba(255,255,255,0.78); border:1px solid #C9DCE3; border-radius:18px;
  padding:1rem 1.1rem; height:100%; box-shadow: 0 8px 24px rgba(11,31,42,0.04);
  animation: th-fade-up .65s cubic-bezier(.22,1,.36,1) both;
  transition: transform .28s cubic-bezier(.22,1,.36,1), box-shadow .28s ease, border-color .28s ease;
}}
div[data-testid="stHorizontalBlock"] > div:nth-child(1) .kpi {{ animation-delay: .05s; }}
div[data-testid="stHorizontalBlock"] > div:nth-child(2) .kpi {{ animation-delay: .1s; }}
div[data-testid="stHorizontalBlock"] > div:nth-child(3) .kpi {{ animation-delay: .15s; }}
div[data-testid="stHorizontalBlock"] > div:nth-child(4) .kpi {{ animation-delay: .2s; }}
div[data-testid="stHorizontalBlock"] > div:nth-child(5) .kpi {{ animation-delay: .25s; }}
.kpi:hover {{
  transform: translateY(-4px);
  box-shadow: 0 18px 36px rgba(11,31,42,0.1);
  border-color: rgba(15,118,110,0.35);
}}
.kpi .lbl {{ color: var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.1em; font-weight:700; }}
.kpi .val {{ font-family: {DISPLAY}; font-size:1.85rem; font-weight:700; margin-top:.3rem; letter-spacing:-0.03em; }}
.kpi .hint {{ color: var(--muted); font-size:.75rem; margin-top:.1rem; }}
.kpi.accent .val {{ color: var(--sea); }}
.kpi.danger {{ border-color: rgba(225,29,72,.28); }}
.kpi.danger .val {{ color: var(--coral); }}

.card {{
  background: rgba(255,255,255,0.82); border:1px solid #C9DCE3; border-radius:18px;
  padding:1rem 1.15rem; margin-bottom: .85rem; box-shadow: 0 8px 24px rgba(11,31,42,0.04);
  animation: th-fade-up .6s cubic-bezier(.22,1,.36,1) both;
  transition: transform .28s ease, box-shadow .28s ease, border-color .28s ease;
}}
.card:hover {{
  transform: translateY(-2px);
  box-shadow: 0 16px 32px rgba(11,31,42,0.08);
  border-color: rgba(15,118,110,0.28);
}}
.card h4 {{
  margin:0 0 .55rem 0; font-size:.72rem; color:var(--muted); text-transform:uppercase;
  letter-spacing:.1em; font-weight:700; padding:0;
}}
[class*="st-key-chartcard_"] {{
  background: rgba(255,255,255,0.82); border:1px solid #C9DCE3; border-radius:18px;
  padding:1rem 1.1rem .35rem; box-shadow: 0 8px 24px rgba(11,31,42,0.04);
  animation: th-fade-up .65s cubic-bezier(.22,1,.36,1) both;
  transition: transform .28s ease, box-shadow .28s ease;
}}
[class*="st-key-chartcard_"]:hover {{
  transform: translateY(-3px);
  box-shadow: 0 16px 34px rgba(11,31,42,0.09);
}}
.card-title {{
  font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-weight:700;
}}
.section {{
  font-family: {DISPLAY}; font-size:1.05rem; font-weight:650; margin: 1.35rem 0 .65rem;
  color: var(--text); display:flex; align-items:center; gap:.55rem; letter-spacing:-0.02em;
  animation: th-fade-in .5s ease both;
}}
.section .bar {{
  width:4px; height:18px; border-radius:4px; background: var(--sea); display:inline-block;
  transform-origin: center bottom;
  animation: th-bar-grow .55s cubic-bezier(.22,1,.36,1) both;
}}
.section.danger .bar {{ background: var(--coral); }}
.muted {{ color: var(--muted); font-size:.85rem; }}

.bdg {{
  display:inline-block; padding:.16rem .5rem; border-radius:999px; font-size:.72rem; font-weight:600;
  background: #EAF4F6; border:1px solid #C9DCE3; color: #0B1F2A !important;
  margin: 0 .22rem .18rem 0; white-space:nowrap;
  transition: transform .18s ease, box-shadow .18s ease;
}}
.bdg:hover {{ transform: translateY(-1px); box-shadow: 0 4px 10px rgba(11,31,42,0.08); }}
.bdg.accent {{ background: var(--sea-soft); border-color: transparent; color: #0F766E !important; }}
.bdg.danger {{ background: var(--coral-soft); border-color: transparent; color: #BE123C !important; }}
.bdg.code {{ font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; color: #0B1F2A !important; }}

.esc {{
  background: #fff; border:1px solid #C9DCE3; border-left: 4px solid var(--coral);
  border-radius: 14px; padding: .75rem 1rem; margin-bottom:.55rem;
  animation: th-fade-up .5s cubic-bezier(.22,1,.36,1) both;
  transition: transform .25s ease, box-shadow .25s ease, border-color .25s ease;
}}
.esc:hover {{
  transform: translateX(4px);
  box-shadow: 0 12px 28px rgba(225,29,72,0.08);
  border-color: rgba(225,29,72,0.35);
}}
.esc .top {{ display:flex; justify-content:space-between; gap:.6rem; flex-wrap:wrap; align-items:center; }}
.esc .id {{ font-weight:700; color: #BE123C !important; margin-right:.45rem; }}
.esc .subj {{ font-weight:600; color: #0B1F2A !important; }}
.esc .muted {{ color: #5B6B76 !important; }}
.esc .reason {{ color: #5B6B76 !important; font-size:.86rem; margin-top:.3rem; }}

.tbl-wrap {{
  max-height: 460px; overflow:auto; border:1px solid #C9DCE3; border-radius:16px;
  background: rgba(255,255,255,0.95);
  animation: th-fade-up .55s cubic-bezier(.22,1,.36,1) both;
}}
table.tbl {{ width:100%; border-collapse: collapse; font-size:.86rem; }}
table.tbl th {{
  position: sticky; top:0; background: #EFF6F8; color: #5B6B76 !important; text-align:left;
  font-weight:700; font-size:.68rem; text-transform:uppercase; letter-spacing:.08em;
  padding:.7rem .8rem; z-index:1;
}}
table.tbl td {{
  padding:.65rem .8rem; border-top:1px solid #D7E5EA; vertical-align: top;
  color: #0B1F2A !important;
  transition: background .2s ease;
}}
table.tbl td b {{ color: #0B1F2A !important; font-family: {DISPLAY}; }}
table.tbl .muted {{ color: #5B6B76 !important; font-size: .78rem; }}
table.tbl tr:hover td {{ background: rgba(15,118,110,0.07); }}
.conf {{ display:flex; align-items:center; gap:.45rem; color: #334155 !important; }}
.conf .track {{ width:58px; height:6px; background: #D7E5EA; border-radius:6px; overflow:hidden; }}
.conf .fill {{
  height:100%; background: var(--sea); border-radius:6px;
  transform-origin: left center;
  animation: th-bar-grow .7s cubic-bezier(.22,1,.36,1) both;
}}
.conf.low .fill {{ background: var(--coral); }}

.card {{ color: #0B1F2A; }}
.card h4 {{ color: #5B6B76 !important; }}
.card .muted {{ color: #5B6B76 !important; }}
.card .bdg.accent {{ color: #0F766E !important; }}
.card .bdg.danger {{ color: #BE123C !important; }}
.card .bdg:not(.accent):not(.danger) {{ color: #0B1F2A !important; }}
.brand-hero h1, .brand-hero .brand-name {{ color: #F4FAFB !important; }}
.brand-hero .brand-kicker {{ color: #7DD3C7 !important; }}
.brand-hero .brand-tag {{ color: #B7CBD4 !important; }}

.reply {{
  white-space: pre-wrap; line-height:1.65; font-size:.92rem; color: #1E293B !important;
  background: #F4FAFB; border-radius: 14px; padding: 1rem 1.05rem; border:1px solid #C9DCE3;
}}
.body {{ white-space: pre-wrap; line-height:1.55; font-size:.88rem; color: #334155 !important; }}
.rule {{
  padding:.55rem .7rem; border-radius:12px; background: #F4FAFB; margin-bottom:.4rem;
  font-size:.86rem; line-height:1.5; border:1px solid #D7E5EA; color: #334155 !important;
}}
.rule .c {{ font-weight:700; color: #0F766E !important; margin-right:.35rem; font-family: ui-monospace, Consolas, monospace; }}
.rule.esc-rule .c {{ color: #BE123C !important; }}

.tl {{ position:relative; padding-left: 1.35rem; }}
.tl::before {{ content:""; position:absolute; left:.42rem; top:.3rem; bottom:.3rem; width:2px; background: #C9DCE3; }}
.tl .st {{
  position:relative; margin-bottom: .75rem;
  animation: th-timeline-in .4s ease both;
}}
.tl .st:nth-child(1) {{ animation-delay: .05s; }}
.tl .st:nth-child(2) {{ animation-delay: .1s; }}
.tl .st:nth-child(3) {{ animation-delay: .15s; }}
.tl .st:nth-child(4) {{ animation-delay: .2s; }}
.tl .st:nth-child(5) {{ animation-delay: .25s; }}
.tl .st:nth-child(n+6) {{ animation-delay: .3s; }}
.tl .st::before {{
  content:""; position:absolute; left:-1.15rem; top:.35rem; width:10px; height:10px; border-radius:50%;
  background: #fff; border:2px solid var(--sea);
  transition: transform .2s ease, background .2s ease, box-shadow .2s ease;
}}
.tl .st:hover::before {{
  transform: scale(1.25);
  box-shadow: 0 0 0 4px rgba(15,118,110,0.15);
}}
.tl .st.DECISION::before {{ background: var(--sea); }}
.tl .kind {{ font-size:.66rem; font-weight:700; letter-spacing:.1em; color: #0F766E !important; }}
.tl .ts {{ color: #64748B !important; font-size:.7rem; margin-left:.35rem; }}
.tl .txt {{ font-size:.85rem; margin-top:.08rem; word-break: break-word; color: #334155 !important; }}

.logtail {{
  background:#0B1F2A; border:1px solid #1F3A4A; border-radius:14px; padding:.85rem 1rem;
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-size:.74rem; color:#B7CBD4;
  white-space: pre-wrap; max-height: 380px; overflow:auto;
  animation: th-fade-in .35s ease both;
}}
.flash {{
  border-radius:14px; padding:.75rem 1rem; margin: .7rem 0; font-size:.88rem;
  border:1px solid rgba(15,118,110,.35); background: var(--sea-soft); color: var(--text);
  animation: th-fade-up .45s cubic-bezier(.22,1,.36,1) both;
}}
.flash.err {{ border-color: rgba(225,29,72,.35); background: var(--coral-soft); }}
.side-title {{
  font-family: {DISPLAY}; font-weight:700; font-size: .95rem; margin: .85rem 0 .35rem;
  letter-spacing: -0.02em;
}}
.side-hint {{ color: #9BB0BC !important; font-size: .78rem; line-height: 1.4; margin-bottom: .55rem; }}
.demo-box {{
  border: 1px dashed rgba(125,211,199,0.45); border-radius: 14px;
  padding: .75rem .8rem; background: rgba(15,118,110,0.12); margin: .4rem 0 .8rem;
}}
</style>
"""


def esc(value: Any) -> str:
    """HTML-escape untrusted values."""
    return html.escape(str(value if value is not None else ""))


def section(title: str, danger: bool = False) -> None:
    cls = "section danger" if danger else "section"
    st.markdown(
        f'<div class="{cls}"><span class="bar"></span>{esc(title)}</div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _to_float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _to_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "y"}
    return bool(value)


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
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
    if not OUTBOX_PATH.exists():
        return [], "outbox.json not found yet. Use Run agent in the sidebar."
    data = _read_json(OUTBOX_PATH)
    if data is None:
        return [], "outbox.json could not be parsed. Showing nothing until it is valid."
    if isinstance(data, dict):
        data = [
            dict(v, email_id=v.get("email_id", k))
            for k, v in data.items()
            if isinstance(v, dict)
        ]
    if not isinstance(data, list):
        return [], "outbox.json has an unexpected shape."
    return [normalize_row(r) for r in data if isinstance(r, dict)], ""


def load_inbox() -> dict[str, dict[str, Any]]:
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
            steps[email_id] = []
        steps.setdefault(email_id, []).append({"kind": kind, "ts": ts, "text": detail})
    return steps


def _classify_log_message(msg: str) -> tuple[str, str, str] | None:
    loaded = re.match(r"^(\S+?)\.json loaded id=(\S+) subject=(.*?) body_len=(\d+)", msg)
    if loaded:
        return (
            loaded.group(2),
            "PLAN",
            f"Read email {loaded.group(3)} ({loaded.group(4)} chars).",
        )
    failed_load = re.match(r"^(\S+?)\.json loaded=fail (.*)$", msg)
    if failed_load:
        return failed_load.group(1), "OBSERVATION", f"Could not load: {failed_load.group(2)}"
    parts = msg.split(" ", 1)
    if len(parts) < 2:
        return None
    email_id, rest = parts
    if rest.startswith("llm_call=start"):
        return email_id, "ACTION", "LLM triage call started."
    if rest.startswith("llm_call=ok"):
        return email_id, "OBSERVATION", "LLM proposed " + rest.replace("llm_call=ok", "").strip()
    if rest.startswith("validator_fixes="):
        fixes = rest.split("=", 1)[1]
        text = "Validator: no fixes." if fixes == "none" else f"Validator: {fixes}"
        return email_id, "OBSERVATION", text
    if rest.startswith("final=safe_failure"):
        return email_id, "DECISION", "Safe failure: " + rest.split(" ", 1)[-1]
    if rest.startswith("final "):
        return email_id, "DECISION", "Final: " + rest[len("final ") :]
    return None


def _trace_from_log(path: Path) -> dict[str, list[dict[str, str]]]:
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
            current = []
        if kind == "PLAN":
            current = []
        current.append({"kind": kind, "ts": match.group(1), "text": text})
        steps[email_id] = current
    return steps


def load_trace() -> tuple[dict[str, list[dict[str, str]]], str]:
    if TRACE_PATH.exists():
        steps = _trace_from_jsonl(TRACE_PATH)
        if steps:
            return steps, "logs/trace.jsonl"
    if LOG_PATH.exists():
        return _trace_from_log(LOG_PATH), "derived from logs/agent.log"
    return {}, "no trace or log file found"


# --------------------------------------------------------------------------
# Agent subprocess
# --------------------------------------------------------------------------


def _agent_env() -> dict[str, str]:
    """Environment for the agent subprocess: unbuffered UTF-8 output."""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_agent_live(extra_args: list[str], tail_box: Any) -> tuple[int, list[str]]:
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
        tail_box.markdown(
            f'<div class="logtail">{esc(chr(10).join(tail))}</div>',
            unsafe_allow_html=True,
        )
    return proc.wait(), all_lines


def merge_into_outbox(new_rows: list[dict[str, Any]]) -> None:
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
    fd, tmp_out = tempfile.mkstemp(prefix="outbox_partial_", suffix=".json")
    os.close(fd)
    try:
        code, _ = run_agent_live(["--ids", ",".join(ids), "--out", tmp_out], tail_box)
        rows = _read_json(Path(tmp_out))
        if code != 0 or not isinstance(rows, list) or not rows:
            return False, f"Agent exited with code {code}; outbox.json unchanged."
        merge_into_outbox(rows)
        return True, f"Processed {len(rows)} email(s): {', '.join(ids)}. Merged into outbox.json."
    finally:
        try:
            os.remove(tmp_out)
        except OSError:
            pass


def run_demo_failures(tail_box: Any) -> tuple[bool, str]:
    """Run --demo-failures into a temp outbox so the main outbox is not wiped."""
    fd, tmp_out = tempfile.mkstemp(prefix="outbox_demo_", suffix=".json")
    os.close(fd)
    try:
        code, lines = run_agent_live(
            ["--demo-failures", "--limit", str(DEMO_LIMIT), "--out", tmp_out],
            tail_box,
        )
        summary = next(
            (ln for ln in reversed(lines) if "DEMO recovery summary" in ln),
            "",
        )
        if code != 0:
            return False, f"Demo run failed (exit {code}). {summary}".strip()
        rows = _read_json(Path(tmp_out))
        if isinstance(rows, list) and rows:
            merge_into_outbox(rows)
        msg = (
            f"Demo failures finished on {DEMO_LIMIT} emails. "
            f"{summary or 'See live log + logs/trace.jsonl.'} "
            "Results merged into outbox.json."
        )
        return True, msg
    finally:
        try:
            os.remove(tmp_out)
        except OSError:
            pass


def next_email_id(inbox: dict[str, dict[str, Any]]) -> str:
    numbers = [0]
    for email_id in inbox:
        match = re.fullmatch(r"E(\d+)", email_id)
        if match:
            numbers.append(int(match.group(1)))
    n = max(numbers) + 1
    while (INBOX_DIR / f"E{n:03d}.json").exists():
        n += 1
    return f"E{n:03d}"


def save_new_email(
    name: str,
    sender_email: str,
    subject: str,
    body: str,
    inbox: dict[str, Any],
) -> str:
    email_id = next_email_id(inbox)
    record = {
        "id": email_id,
        "from_name": name.strip() or "Student",
        "from_email": sender_email.strip(),
        "subject": subject.strip(),
        "body": body.strip(),
        "received_at": "",
    }
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = INBOX_DIR / f"{email_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return email_id


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------


def render_sidebar(inbox: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    with st.sidebar:
        st.markdown(
            f'<div class="side-title">{esc(TEAM_NAME)}</div>'
            f'<div class="side-hint">Control room · drafts only · nothing is sent</div>',
            unsafe_allow_html=True,
        )

        if st.button("Run agent · full inbox", type="primary", key="run_all"):
            st.session_state["pending"] = {"mode": "all", "ids": []}

        processed = {r["email_id"] for r in rows}
        new_ids = sorted(i for i in inbox if i not in processed)
        label = f"Process new emails only ({len(new_ids)})"
        if st.button(label, key="run_new", disabled=not new_ids):
            st.session_state["pending"] = {"mode": "ids", "ids": new_ids}
        if new_ids:
            st.markdown(
                f'<div class="side-hint">Waiting: {esc(", ".join(new_ids[:8]))}'
                f'{"…" if len(new_ids) > 8 else ""}</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="side-title">Judge demo</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="demo-box">'
            '<div class="side-hint" style="margin:0 0 .55rem">'
            "One-click paths for the presentation — live PLAN/ACTION log below."
            "</div></div>",
            unsafe_allow_html=True,
        )
        if st.button("Showcase · E005 / E010 / E013", key="run_showcase"):
            present = [i for i in SHOWCASE_IDS if i in inbox]
            if present:
                st.session_state["pending"] = {"mode": "ids", "ids": present}
            else:
                st.session_state["flash"] = ("err", "Showcase ids not found in data/inbox.")
                st.rerun()
        if st.button(f"Demo failures · limit {DEMO_LIMIT}", key="run_demo"):
            st.session_state["pending"] = {"mode": "demo", "ids": []}
        st.markdown(
            '<div class="side-hint">Demo failures injects timeout, bad JSON and a bad draft '
            "(labelled DEMO: simulated failure), then shows recovery.</div>",
            unsafe_allow_html=True,
        )

        st.markdown('<div class="side-title">Add a new email</div>', unsafe_allow_html=True)
        with st.form("new_email", clear_on_submit=True):
            name = st.text_input("Sender name", placeholder="e.g. Ayesha Khan")
            sender_email = st.text_input("Sender email (optional)", placeholder="name@example.com")
            subject = st.text_input("Subject")
            body = st.text_area("Body", height=140, placeholder="Paste the email text")
            after = st.selectbox(
                "After saving",
                ["Process only this new email", "Just save to inbox"],
            )
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
                st.session_state["pending"] = {
                    "mode": "ids",
                    "ids": [new_id],
                    "saved": new_id,
                }
            else:
                st.session_state["flash"] = ("ok", f"Saved data/inbox/{new_id}.json.")
                st.rerun()


def handle_pending_run() -> None:
    pending = st.session_state.pop("pending", None)
    if not pending:
        return
    mode = pending["mode"]
    if mode == "all":
        title = "Running agent on full inbox"
    elif mode == "demo":
        title = f"DEMO failures · {DEMO_LIMIT} emails"
    else:
        title = f"Processing {', '.join(pending['ids'])}"

    with st.status(title + "…", expanded=True) as status:
        tail_box = st.empty()
        if mode == "all":
            code, _ = run_agent_live([], tail_box)
            ok = code == 0
            msg = (
                "Agent finished; outbox.json rewritten."
                if ok
                else f"Agent exited with code {code}."
            )
        elif mode == "demo":
            ok, msg = run_demo_failures(tail_box)
        else:
            ok, msg = run_partial(pending["ids"], tail_box)
        if pending.get("saved"):
            msg = f"Saved data/inbox/{pending['saved']}.json. " + msg
        status.update(label=msg, state="complete" if ok else "error")
    st.session_state["flash"] = ("ok" if ok else "err", msg)
    st.rerun()


def render_brand(rows: list[dict[str, Any]]) -> None:
    escalated = sum(1 for r in rows if r["escalate"])
    st.markdown(
        f"""
<div class="brand">
  <div class="brand-hero">
    <div class="brand-kicker">Agent Sprint · Engineer's Code 2026</div>
    <h1 class="brand-name">{esc(TEAM_NAME)}</h1>
    <div class="brand-tag">
      Student Helpdesk Triage Agent — reads policy, decides, drafts, escalates.
      Humans see every step. Nothing is ever sent.
    </div>
    <div class="brand-meta">
      <span class="pill"><span class="dot"></span>DRAFTS ONLY</span>
      <span class="pill">{len(rows)} in outbox</span>
      <span class="pill">{escalated} escalated</span>
    </div>
  </div>
  <div class="brand-side">
    <h3>How the agent thinks</h3>
    <p>Each email is an explicit loop grounded in <code>policy.md</code>.</p>
    <div class="steps">
      <div class="step"><b>PLAN</b><span>Decide the path for this email</span></div>
      <div class="step"><b>ACTION</b><span>Triage → lookup policy → validate / repair</span></div>
      <div class="step"><b>OBSERVE</b><span>Category, codes, draft issues</span></div>
      <div class="step"><b>DECIDE</b><span>Final escalate + reply draft</span></div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def needs_human(row: dict[str, Any]) -> bool:
    return (
        row["escalate"]
        or row["confidence"] < LOW_CONFIDENCE
        or "agent error" in row["escalation_reason"]
    )


def render_kpis(rows: list[dict[str, Any]]) -> None:
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
    fig.update_layout(
        height=height,
        margin=dict(l=6, r=6, t=6, b=6),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=MUTED, size=12),
        showlegend=False,
        bargap=0.38,
        barcornerradius=6,
        hoverlabel=dict(
            bgcolor="#FFFFFF",
            bordercolor="#C9DCE3",
            font=dict(color=TEXT, family=FONT),
        ),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def _chart_card(title: str, fig: go.Figure | None, key: str) -> None:
    with st.container(key=f"chartcard_{key}"):
        st.markdown(f'<div class="card-title">{esc(title)}</div>', unsafe_allow_html=True)
        if fig is None:
            st.markdown('<div class="muted">No data yet.</div>', unsafe_allow_html=True)
        else:
            st.plotly_chart(fig, theme=None, key=key, config={"displayModeBar": False})


def render_charts(rows: list[dict[str, Any]]) -> None:
    c1, c2, c3 = st.columns([1.1, 0.8, 1.3])
    with c1:
        counts = Counter(r["category"] for r in rows).most_common()
        fig = None
        if counts:
            labels = [c for c, _ in counts][::-1]
            values = [n for _, n in counts][::-1]
            fig = _style_fig(
                go.Figure(
                    go.Bar(
                        x=values,
                        y=labels,
                        orientation="h",
                        marker_color=SEA,
                        hovertemplate="%{y}: %{x}<extra></extra>",
                    )
                )
            )
        _chart_card("Category distribution", fig, "cat_chart")
    with c2:
        pcount = Counter(r["priority"] for r in rows)
        labels = [p for p in PRIORITY_ORDER if pcount.get(p)] + sorted(
            p for p in pcount if p not in PRIORITY_ORDER
        )
        fig = None
        if labels:
            colors = [
                CORAL if p == "high" else SEA if p == "medium" else "#94A3B8"
                for p in labels
            ]
            fig = _style_fig(
                go.Figure(
                    go.Bar(
                        x=labels,
                        y=[pcount[p] for p in labels],
                        marker_color=colors,
                        hovertemplate="%{x}: %{y}<extra></extra>",
                    )
                )
            )
        _chart_card("Priority distribution", fig, "prio_chart")
    with c3:
        refs = Counter(code for r in rows for code in r["policy_refs"])
        fig = None
        if refs:
            codes = sorted(refs, key=lambda c: (-refs[c], c))
            colors = [CORAL if c.startswith("ESC-") else SEA for c in codes]
            fig = _style_fig(
                go.Figure(
                    go.Bar(
                        x=codes,
                        y=[refs[c] for c in codes],
                        marker_color=colors,
                        hovertemplate="%{x}: cited %{y}x<extra></extra>",
                    )
                )
            )
        _chart_card("Policy code usage", fig, "refs_chart")


def esc_codes(row: dict[str, Any]) -> list[str]:
    codes = [c for c in row["policy_refs"] if c.startswith("ESC-")]
    codes += [c for c in ESC_RE.findall(row["escalation_reason"]) if c not in codes]
    return codes


def render_escalation_queue(
    rows: list[dict[str, Any]], inbox: dict[str, dict[str, Any]]
) -> None:
    queue = [r for r in rows if r["escalate"]]
    section(f"Escalation queue · {len(queue)}", danger=True)
    if not queue:
        st.markdown(
            '<div class="card muted">Nothing escalated.</div>',
            unsafe_allow_html=True,
        )
        return
    rank = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    queue.sort(key=lambda r: (rank.get(r["priority"], 9), r["email_id"]))
    parts = []
    for r in queue:
        email = inbox.get(r["email_id"], {})
        codes = esc_codes(r)
        code_badges = (
            "".join(f'<span class="bdg danger code">{esc(c)}</span>' for c in codes)
            or '<span class="bdg">no ESC code</span>'
        )
        parts.append(
            f'<div class="esc"><div class="top"><div><span class="id">{esc(r["email_id"])}</span>'
            f'<span class="subj">{esc(email.get("subject") or "(no subject)")}</span>'
            f'<span class="muted"> · {esc(email.get("from_name") or "unknown")}</span></div>'
            f'<div>{code_badges}<span class="bdg">{esc(r["priority"])}</span></div></div>'
            f'<div class="reason">{esc(r["escalation_reason"] or "No reason given.")}</div></div>'
        )
    st.markdown(
        '<div style="max-height:420px;overflow:auto;padding-right:4px">'
        + "".join(parts)
        + "</div>",
        unsafe_allow_html=True,
    )


def filter_rows(
    rows: list[dict[str, Any]], inbox: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    c1, c2, c3, c4 = st.columns([1.2, 1, 0.8, 1.6])
    cats = sorted({r["category"] for r in rows})
    prios = [p for p in PRIORITY_ORDER if any(r["priority"] == p for r in rows)]
    prios += sorted({r["priority"] for r in rows} - set(prios))
    sel_cats = c1.multiselect("Category", cats, placeholder="All categories")
    sel_prios = c2.multiselect("Priority", prios, placeholder="All priorities")
    sel_esc = c3.selectbox("Escalate", ["All", "Yes", "No"])
    query = c4.text_input(
        "Search", placeholder="id, subject, sender, reply, notes, code…"
    ).strip().lower()

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
            hay = " ".join(
                [
                    r["email_id"],
                    r["category"],
                    r["reply_draft"],
                    r["agent_notes"],
                    r["escalation_reason"],
                    " ".join(r["policy_refs"]),
                    str(email.get("subject", "")),
                    str(email.get("from_name", "")),
                    str(email.get("from_email", "")),
                    str(email.get("body", "")),
                ]
            ).lower()
            if query not in hay:
                continue
        out.append(r)
    return out


def _priority_badge(priority: str) -> str:
    cls = (
        "bdg danger"
        if priority == "high"
        else "bdg accent"
        if priority == "medium"
        else "bdg"
    )
    return f'<span class="{cls}">{esc(priority)}</span>'


def render_table(
    rows: list[dict[str, Any]], inbox: dict[str, dict[str, Any]]
) -> None:
    if not rows:
        st.markdown(
            '<div class="card muted">No emails match these filters.</div>',
            unsafe_allow_html=True,
        )
        return
    body = []
    for r in rows:
        email = inbox.get(r["email_id"], {})
        refs = (
            "".join(
                f'<span class="bdg code {"danger" if c.startswith("ESC-") else ""}">{esc(c)}</span>'
                for c in r["policy_refs"]
            )
            or '<span class="muted">none</span>'
        )
        esc_cell = (
            '<span class="bdg danger">yes</span>'
            if r["escalate"]
            else '<span class="muted">no</span>'
        )
        low = " low" if r["confidence"] < LOW_CONFIDENCE else ""
        conf = (
            f'<div class="conf{low}"><div class="track"><div class="fill" '
            f'style="width:{r["confidence"] * 100:.0f}%"></div></div>'
            f'{r["confidence"]:.2f}</div>'
        )
        body.append(
            f'<tr><td><b>{esc(r["email_id"])}</b></td>'
            f'<td>{esc(email.get("subject") or "(not in inbox)")}'
            f'<div class="muted">{esc(email.get("from_name", ""))}</div></td>'
            f'<td><span class="bdg accent">{esc(r["category"])}</span></td>'
            f'<td>{_priority_badge(r["priority"])}</td><td>{esc_cell}</td>'
            f"<td>{refs}</td><td>{conf}</td></tr>"
        )
    st.markdown(
        '<div class="tbl-wrap"><table class="tbl"><thead><tr>'
        "<th>ID</th><th>Subject / sender</th><th>Category</th>"
        "<th>Priority</th><th>Escalate</th><th>Policy refs</th><th>Confidence</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="muted" style="margin-top:.4rem">{len(rows)} email(s) shown</div>',
        unsafe_allow_html=True,
    )


def _timeline_html(steps: list[dict[str, str]]) -> str:
    items = []
    for s in steps:
        kind = s["kind"] if s["kind"] in STEP_ORDER else "ACTION"
        # Map kinds that start with ACTION / OBSERVATION etc.
        css_kind = "ACTION"
        for name in STEP_ORDER:
            if kind.startswith(name) or name in kind:
                css_kind = name
                break
        items.append(
            f'<div class="st {css_kind}"><span class="kind">{esc(s["kind"])}</span>'
            f'<span class="ts">{esc(s["ts"])}</span>'
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
    if not rows:
        return
    labels = {
        r["email_id"]: (
            f'{r["email_id"]} · '
            f'{inbox.get(r["email_id"], {}).get("subject") or "(no subject)"}'
        )
        for r in rows
    }
    chosen = st.selectbox(
        "Select an email", list(labels), format_func=lambda i: labels[i]
    )
    row = next(r for r in rows if r["email_id"] == chosen)
    email = inbox.get(chosen, {})

    sender = email.get("from_name") or "Unknown sender"
    addr = f' &lt;{esc(email["from_email"])}&gt;' if email.get("from_email") else ""
    badges = (
        f'<span class="bdg accent">{esc(row["category"])}</span>'
        f'{_priority_badge(row["priority"])}'
        + ('<span class="bdg danger">escalated</span>' if row["escalate"] else "")
        + f'<span class="bdg">confidence {row["confidence"]:.2f}</span>'
    )
    st.markdown(
        f'<div class="card"><div style="font-family:{DISPLAY};font-size:1.15rem;font-weight:650">'
        f'{esc(email.get("subject") or "(no subject)")}</div>'
        f'<div class="muted" style="margin:.2rem 0 .6rem">From {esc(sender)}{addr} · '
        f'{esc(email.get("received_at", ""))}</div>{badges}</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.25, 1])
    with left:
        st.markdown(
            f'<div class="card"><h4>Reply draft (not sent)</h4><div class="reply">'
            f'{esc(row["reply_draft"] or "No draft.")}</div></div>',
            unsafe_allow_html=True,
        )
        notes = esc(row["agent_notes"] or "No notes.")
        reason = (
            f'<div style="margin-top:.6rem"><span class="bdg danger">escalation reason</span> '
            f'{esc(row["escalation_reason"])}</div>'
            if row["escalate"]
            else ""
        )
        st.markdown(
            f'<div class="card"><h4>Agent notes</h4><div>{notes}</div>{reason}</div>',
            unsafe_allow_html=True,
        )
        with st.expander("Original email body"):
            st.markdown(
                f'<div class="body">{esc(email.get("body") or "(not in data/inbox)")}</div>',
                unsafe_allow_html=True,
            )
    with right:
        cited = []
        for code in row["policy_refs"]:
            cls = "rule esc-rule" if code.startswith("ESC-") else "rule"
            text = rules.get(code, "Code not found in data/policy.md.")
            cited.append(
                f'<div class="{cls}"><span class="c">{esc(code)}</span>{esc(text)}</div>'
            )
        st.markdown(
            '<div class="card"><h4>Policy rules cited</h4>'
            + ("".join(cited) or '<div class="muted">No policy codes cited.</div>')
            + "</div>",
            unsafe_allow_html=True,
        )
        steps = trace.get(chosen, [])
        # Also show RUN-level demo summary if present
        run_steps = trace.get("RUN", [])
        timeline = (
            _timeline_html(steps)
            if steps
            else '<div class="muted">No trace recorded for this email yet. Run the agent from the sidebar.</div>'
        )
        extra = ""
        if run_steps:
            extra = (
                '<div style="margin-top:.8rem"><h4 style="margin:0 0 .4rem;font-size:.72rem;'
                'color:var(--muted);letter-spacing:.1em;text-transform:uppercase">Run-level</h4>'
                + _timeline_html(run_steps)
                + "</div>"
            )
        st.markdown(
            f'<div class="card"><h4>Agent steps</h4>{timeline}{extra}'
            f'<div class="muted" style="margin-top:.4rem;font-size:.75rem">'
            f"Source: {esc(trace_source)}</div></div>",
            unsafe_allow_html=True,
        )


def main() -> None:
    st.set_page_config(
        page_title=f"Helpdesk Triage · {TEAM_NAME}",
        page_icon="✉️",
        layout="wide",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    rows, outbox_warning = load_outbox()
    inbox = load_inbox()
    render_sidebar(inbox, rows)
    handle_pending_run()
    render_brand(rows)

    flash = st.session_state.pop("flash", None)
    if flash:
        kind, msg = flash
        cls = "flash err" if kind == "err" else "flash"
        st.markdown(f'<div class="{cls}">{esc(msg)}</div>', unsafe_allow_html=True)

    if outbox_warning:
        st.markdown(
            f'<div class="flash err">{esc(outbox_warning)}</div>',
            unsafe_allow_html=True,
        )

    tab_overview, tab_queue, tab_inbox, tab_detail = st.tabs(
        ["Overview", "Escalations", "All emails", "Email detail"]
    )

    with tab_overview:
        render_kpis(rows)
        section("Overview")
        render_charts(rows)

    with tab_queue:
        render_escalation_queue(rows, inbox)

    with tab_inbox:
        section("All emails")
        filtered = filter_rows(rows, inbox)
        render_table(filtered, inbox)

    with tab_detail:
        section("Email detail")
        # Use unfiltered rows so selection works even if overview filters differ
        if rows:
            trace, trace_source = load_trace()
            render_detail(rows, inbox, load_policy_rules(), trace, trace_source)
        else:
            st.markdown(
                '<div class="card muted">Run the agent from the sidebar to populate outbox.json.</div>',
                unsafe_allow_html=True,
            )


main()
