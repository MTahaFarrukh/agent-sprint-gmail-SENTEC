# Student Helpdesk Triage Agent

**Team: Teen Haseen**
Muhammad Taha Farrukh, Muhammad Uzzam Siddiqui, Muhammad Bilal Rasheed

Agent Sprint, The Engineer's Code 2026 (SENTEC, NED University)

## What it does
Reads every email in `data/inbox/`, understands it, finds the matching rules in `data/policy.md`, decides category, priority and whether a human must handle it, writes a policy-grounded reply draft, and saves everything to `outbox.json`. Every step is logged. **Nothing is ever sent**; drafts only.

## Run
```bash
pip install -r requirements.txt

# Windows PowerShell
$env:GEMINI_API_KEY="your_key"
# Mac/Linux
export GEMINI_API_KEY="your_key"

python agent.py
```
The key is read from `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) first, then from a `.env` file. Optional `GEMINI_MODEL` / `LLM_MODEL` selects the model.

New emails: drop more `*.json` files into `data/inbox/` and run `python agent.py` again. No code change is needed. The inbox is re-scanned every run and `outbox.json` is rewritten completely.

Flags:
```
python agent.py --inbox data/inbox --policy data/policy.md --out outbox.json
python agent.py --limit 3
python agent.py --ids E003,E010 --out outbox_test.json
```
Output: `outbox.json` (format of `sample_outbox.json`), `logs/agent.log` (step-by-step reasoning), and a summary table in the console.

## How it decides
1. **Policy loading.** `policy.py` parses `policy.md` at runtime and extracts every policy code (FEE-1, HOSTEL-3, ESC-2, ...). Nothing is hardcoded to the sample emails; a different policy file with the same code style works.
2. **One LLM call per email** (`llm.py`) returns strict JSON: category, priority, escalate, reason, policy refs, reply, confidence, notes. The full policy text is part of the prompt, temperature is 0.
3. **Deterministic validator** (`validator.py`) checks the model output. It can only *add* safety, never remove it:
   - drops policy codes that do not exist in the policy
   - forces escalation for hazards (ESC-1), harassment (ESC-2), hopelessness/wellbeing (ESC-3), legal/media threats (ESC-4), and instructions aimed at the agent or requests for other students' data (ESC-6), including Roman Urdu wording
   - overdue escalation (ESC-5) requires the model to quote evidence from the email, and the validator checks that the quote really appears in the body
   - enforces reply rules: under 150 words, policy code cited, "Student Helpdesk" sign-off, no extra placeholders
   - lowers confidence whenever it had to fix something
4. **Failure handling.** Each email runs in its own try/except. If the AI service fails or times out, the agent retries with backoff and respects rate limits (429 handling, minimum gap between calls). If it still fails, the email gets a safe record: escalate = true, "agent error, needs human", polite holding reply, confidence 0. One bad email never stops the batch.

## Safety design
- Email text is treated as **untrusted data** (wrapped in delimiters). Instructions inside an email are never followed; they are flagged to IT Security (ESC-6).
- Replies never promise more than the policy allows, never reveal other students' data, never give medical advice (ESC-3), never argue with legal/media threats (ESC-4).
- Emails in Roman Urdu get replies in Roman Urdu. Emails with several problems cite the codes for all of them. Messages that make no sense get a polite request for details instead of a guess.
- If the policy does not cover something, the reply says so and names the office to contact.

## Files
```
agent.py        entry point, CLI, logging, outbox writer
policy.py       policy.md parser
llm.py          triage prompt and Gemini call
validator.py    safety net and reply rules
data/           policy.md, inbox/
logs/           agent.log
outbox.json     output
```

## Limitations (honest)
- Overdue detection depends on the email stating how long the student has waited.
- The free Gemini tier is rate limited (about 15 requests per minute), so a full run takes a few minutes.
- The confidence score is partly model-reported; the validator lowers it when it fixes something.
