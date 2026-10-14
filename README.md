# Student Helpdesk Triage Agent

**Team: Teen Haseen**  
Muhammad Taha Farrukh, Muhammad Uzzam Siddiqui, Muhammad Bilal Rasheed

Agent Sprint, The Engineer's Code 2026 (SENTEC, NED University)

## What it does

Reads every email in `data/inbox/`, understands it, looks up the matching rules in `data/policy.md`, decides category / priority / whether a human must handle it, drafts a policy-grounded reply, and saves everything to `outbox.json`.

Every email is processed as an explicit agent loop (**PLAN → ACTION → OBSERVATION → DECISION**), logged to the console and to `logs/trace.jsonl`. **Nothing is ever sent** — drafts only.

## Setup

```bash
pip install -r requirements.txt
python check_env.py
```

Set your key (either works):

```bash
# Windows PowerShell
$env:GEMINI_API_KEY="your_key"

# Mac/Linux
export GEMINI_API_KEY="your_key"
```

Or copy `.env.example` → `.env` and fill `GEMINI_API_KEY=`.  
The agent reads `GEMINI_API_KEY` / `GOOGLE_API_KEY` from the environment first, then from `.env`.

**Model selection:** optional `GEMINI_MODEL` or `LLM_MODEL`. If unset, the agent lists available Gemini models, prefers a **flash** model, and logs the choice. If that model returns **404**, it tries the next flash candidate once.

## Run

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

`--demo-failures` is **off by default**. When on, it injects simulated timeouts, invalid JSON, and bad drafts (clearly labelled `DEMO: simulated failure`) so retry / repair paths can be shown live. At the end it prints a recovery summary (also written to `logs/trace.jsonl`).

### Dashboard

```bash
streamlit run dashboard.py
```

Reads `outbox.json`, inbox, policy, and the agent trace so you can see what the agent decided and why.

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



## Safety design

- Email content is **untrusted data** (wrapped in `<email_data>`). Instructions inside an email are never followed; they are flagged (ESC-6).
- Replies promise only what the policy allows, never reveal other students’ data, give no medical advice (ESC-3), and do not argue with legal/media threats (ESC-4).
- Roman Urdu emails get Roman Urdu replies where possible. Multi-issue emails cite codes for each issue. Nonsense messages get a polite “not covered / need details” reply instead of a guess.
- If the topic is not in the policy, the reply says so and tells the student to contact the relevant university office — **no invented office names**.



## Categories

`fee`, `hostel`, `academic`, `technical`, plus `harassment`, `wellbeing`, `suspicious`, and `other`.

## Output

One object per email in `outbox.json` (same shape as `sample_outbox.json`):

`email_id`, `category`, `priority`, `escalate`, `escalation_reason`, `policy_refs`, `reply_draft`, `confidence`, `agent_notes`

Also written each run:

- `logs/agent.log` — file log  
- `logs/trace.jsonl` — one JSON object per step (`email_id`, `step`, `detail`, `timestamp`); overwritten at the start of each run  
- Console summary table



## Files

```
agent.py           entry point, agent loop, CLI, outbox writer
policy.py          policy.md parser
llm.py             triage + repair prompts, Gemini client (self-contained)
validator.py       escalation safety net + reply checks
dashboard.py       Streamlit status UI
eval.py            score outbox vs expected labels
check_env.py       API key / package check
make_zip.py        build submission zip + smoke test
requirements.txt   dependencies
.env.example       GEMINI_API_KEY= (empty)
data/policy.md     helpdesk policy
data/inbox/        sample emails
data/inbox_extra/  extra evaluation emails
data/expected_extra.json
outbox.json        agent output
logs/              agent.log, trace.jsonl
```



## Approach (short)

We treat triage as a **small tool-using agent**, not a single opaque LLM call: plan, call the model, look up policy codes, validate, repair if needed, then decide. A deterministic validator sits after the model so safety rules do not depend on the LLM being perfect. The package runs without the old Gmail/`src` code — only the root modules above.

## Limitations (honest)

- Overdue detection needs the student to state how long they have been waiting.
- Free Gemini tier is rate-limited, so a full inbox run takes a few minutes.
- Confidence is partly model-reported; we lower it when material fields are corrected.
- Multi-issue emails can be ambiguous on a single “primary” category (escalate and policy refs still cover each issue).

