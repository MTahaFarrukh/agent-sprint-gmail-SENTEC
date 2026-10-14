# Student Helpdesk Triage Agent

**Team: Teen Haseen**  
Muhammad Taha Farrukh, Muhammad Uzzam Siddiqui, Muhammad Bilal Rasheed

Agent Sprint, The Engineer's Code 2026 (SENTEC, NED University)

## What it does

Two ways to run the same helpdesk agent:

1. **JSON inbox mode** — reads every email in `data/inbox/`, looks up `data/policy.md`, decides category / priority / escalation, drafts a policy-grounded reply, writes `outbox.json`.
2. **Live Gmail mode** — fetches real unread mail via the Gmail API, runs the **same** agent loop, and creates **in-thread Gmail drafts**. Labels processed mail. **Nothing is ever sent.**

Every email is processed as an explicit agent loop (**PLAN → ACTION → OBSERVATION → DECISION**), logged to the console and to `logs/trace.jsonl` (Gmail runs use `logs/gmail_trace.jsonl`).

**Safety:** drafts only. Scope is `gmail.modify` only — never `gmail.send`, never `messages.send`.

## Setup

```bash
pip install -r requirements.txt
python check_env.py
```

Set your Gemini key (either works):

```bash
# Windows PowerShell
$env:GEMINI_API_KEY="your_key"

# Mac/Linux
export GEMINI_API_KEY="your_key"
```

Or copy `.env.example` → `.env` and fill `GEMINI_API_KEY=`.  
The agent reads `GEMINI_API_KEY` / `GOOGLE_API_KEY` from the environment first, then from `.env`.

**Model selection:** optional `GEMINI_MODEL` or `LLM_MODEL`. If unset, the agent lists available Gemini models, prefers a **flash** model, and logs the choice. If that model returns **404**, it tries the next flash candidate once.

## Run — JSON inbox (offline / sample set)

```bash
python agent.py
```

Drop new `*.json` emails into `data/inbox/` and run again — **no code change**. The inbox is re-scanned every run and `outbox.json` is rewritten completely.

### Useful flags

```bash
python agent.py --inbox data/inbox --policy data/policy.md --out outbox.json
python agent.py --limit 3
python agent.py --ids E005,E010,E013 --out outbox_live.json
python agent.py --demo-failures --limit 5 --out outbox_demo.json
```

`--demo-failures` is **off by default**. When on, it injects simulated timeouts, invalid JSON, and bad drafts (clearly labelled `DEMO: simulated failure`) so retry / repair paths can be shown live.

## Run — Live Gmail Mode (for judges / demo)

Uses the real Gmail inbox → same triage agent → **Gmail Drafts** in the same thread.

### 1. Gmail API credentials (once)

1. Google Cloud Console → enable **Gmail API**.
2. Create OAuth client type **Desktop app**.
3. Download the JSON and save it as **`credentials.json`** in the project root  
   (this file is gitignored and **not** in the submission zip — place it locally for the demo).
4. First connect opens a browser; **`token.json`** is saved locally (also not in the zip).

Scope requested: `https://www.googleapis.com/auth/gmail.modify` only.

### 2. Dashboard (recommended for judges)

```bash
streamlit run dashboard.py
```

- **Home** — JSON inbox control room (`outbox.json`, charts, demo buttons).
- Sidebar → **Open Real Gmail Mode** — live Gmail control room:
  - shows which account is connected
  - **Connect** / **Switch account**
  - **Preview inbox**
  - **Triage & create drafts** (uncheck Dry run for real drafts)
  - last-run table, draft text, agent trace

### 3. CLI (same pipeline)

```bash
python gmail_bridge.py --status
python gmail_bridge.py --preview --limit 5
python gmail_bridge.py --dry-run --limit 1
python gmail_bridge.py --limit 3
```

- Results → `data/gmail_outbox.json`
- Trace → `logs/gmail_trace.jsonl`
- Labels: `AGENT_PROCESSED`, `ESCALATED`, `NEEDS_REVIEW`
- Optional query override: `GMAIL_QUERY` in `.env` (default: `in:inbox -label:AGENT_PROCESSED`)

After a run, open **Gmail → Drafts** (or the email thread) to review replies. Nothing is auto-sent.

### Evaluate on the extra set

```bash
python agent.py --inbox data/inbox_extra --out outbox_extra.json
python eval.py --outbox outbox_extra.json --expected data/expected_extra.json
```

## How it decides

1. **Policy loading** (`policy.py`) — parses `policy.md` at runtime into codes (`FEE-1`, `HOSTEL-3`, `ESC-2`, …). Nothing is hardcoded to the 20 sample emails.
2. **Agent loop** (`agent.py`) — for each email:
  - **PLAN** what will happen
  - **ACTION triage** — LLM classifies and drafts (temperature 0, strict JSON)
  - **ACTION lookup_policy** — grounds each cited code in the real policy text (unknown codes dropped)
  - **ACTION validate_draft** — reply quality checks; if needed **ACTION repair_draft** (max 2)
  - **DECISION** — final category, priority, escalate, reason
3. **Deterministic validator** (`validator.py`) — safety net after the model. It may only **add** escalation, never remove it:
  - drops policy codes that do not exist in the policy
  - forces escalation for hazards (ESC-1), harassment (ESC-2), wellbeing (ESC-3), legal/media threats (ESC-4), and prompt-injection / phishing / other-students’ data (ESC-6), including Roman Urdu wording
  - overdue escalation (ESC-5) requires the model to quote evidence from the email; the validator checks the quote really appears in the body
  - enforces reply rules: under 150 words, policy codes in the body, exact `Student Helpdesk` sign-off, `Next step:` line, offices only from the policy
  - logs honesty tags: `confirmed ESC-x` vs `overrode: escalate false->true (ESC-x)`
  - lowers confidence only when escalate / category / policy_refs actually changed
4. **Failure handling** — retries with backoff and rate-limit respect (429). If it still fails, that email gets a safe record (`escalate=true`, holding reply, `confidence=0`). One bad email never stops the batch.
5. **Live Gmail** (`gmail_bridge.py` + `src/gmail_client.py`) — fetch → same `process_email` → `users.drafts.create` → label. Never send.

## Safety design

- Email content is **untrusted data** (wrapped in `<email_data>`). Instructions inside an email are never followed; they are flagged (ESC-6).
- Replies promise only what the policy allows, never reveal other students’ data, give no medical advice (ESC-3), and do not argue with legal/media threats (ESC-4).
- Roman Urdu emails get Roman Urdu replies where possible. Multi-issue emails cite codes for each issue. Nonsense messages get a polite “not covered / need details” reply instead of a guess.
- If the topic is not in the policy, the reply says so and tells the student to contact the relevant university office — **no invented office names**.
- Live Gmail path: drafts only; `credentials.json` / `token.json` / `.env` are never packaged in the submission zip.

## Categories

`fee`, `hostel`, `academic`, `technical`, plus `harassment`, `wellbeing`, `suspicious`, and `other`.

## Output

**JSON inbox** — one object per email in `outbox.json` (same shape as `sample_outbox.json`):

`email_id`, `category`, `priority`, `escalate`, `escalation_reason`, `policy_refs`, `reply_draft`, `confidence`, `agent_notes`

**Live Gmail** — `data/gmail_outbox.json` plus a real draft in Gmail (`draft_id`, `draft_reply` / `reply_draft`).

Also written each run:

- `logs/agent.log` / `logs/gmail_agent.log`
- `logs/trace.jsonl` / `logs/gmail_trace.jsonl`
- Console summary table

## Files

```
agent.py                    entry point, agent loop, CLI, outbox writer
policy.py                   policy.md parser
llm.py                      triage + repair prompts, Gemini client
validator.py                escalation safety net + reply checks
dashboard.py                Streamlit Home (JSON inbox)
pages/2_Real_Gmail_Mode.py  Streamlit Real Gmail Mode UI
gmail_bridge.py             live Gmail fetch → triage → draft
src/gmail_client.py         OAuth, fetch, labels, create_draft
src/config.py               paths, gmail.modify scope
eval.py                     score outbox vs expected labels
check_env.py                API key / package check
make_zip.py                 build submission zip + smoke test
requirements.txt            dependencies (incl. Gmail client libs)
.env.example                GEMINI_API_KEY= (empty); optional GMAIL_QUERY
data/policy.md              helpdesk policy
data/inbox/                 sample emails
data/inbox_extra/           extra evaluation emails
data/expected_extra.json
outbox.json                 JSON-mode agent output
logs/                       agent.log, trace.jsonl
```

Place locally for Gmail demo (not in zip): `credentials.json`, `token.json`, `.env`.

## Approach (short)

We treat triage as a **small tool-using agent**, not a single opaque LLM call: plan, call the model, look up policy codes, validate, repair if needed, then decide. A deterministic validator sits after the model so safety rules do not depend on the LLM being perfect. The same loop powers both the JSON inbox and live Gmail drafts UI.

## Limitations (honest)

- Overdue detection needs the student to state how long they have been waiting.
- Free Gemini tier is rate-limited, so a full inbox run takes a few minutes.
- Confidence is partly model-reported; we lower it when material fields are corrected.
- Multi-issue emails can be ambiguous on a single “primary” category (escalate and policy refs still cover each issue).
- Live Gmail needs a one-time OAuth browser login per machine/account (`credentials.json` from Google Cloud).
