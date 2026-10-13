# Agent Sprint: Live Gmail Automation

Gmail complaint-handling agent that classifies emails, drafts policy-based replies, flags escalations, and shows live status on a dashboard.

**Safety:** drafts only — nothing is auto-sent. Never requests `gmail.send`.

## Setup

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Place Google OAuth `credentials.json` in the project root, then run the Gmail test script (see below).

## Project layout

See `docs/TECH_SPEC.md` for the full stack, pipeline, and build order.

## Status

Step 1–2: project scaffold + Gmail client (auth, fetch, drafts, labels).
