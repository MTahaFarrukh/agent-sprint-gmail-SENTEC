# Agent Sprint: Student Helpdesk Triage Agent

**Time:** 5 hours, one continuous block | **Team size:** 3 to 4 | **Submission:** code by email

## The situation

You are a freelance automation consultant. A university helpdesk is drowning in student emails. The client wants an AI agent that reads each incoming email, understands what it is about, finds the right rule in the helpdesk policy, drafts a safe reply, and flags the emails that need a human. The client also wants to see what the agent decided and why.

## What you get

- `data/inbox/`: 20 sample emails (one JSON file each)  
- `data/policy.md`: the helpdesk policy (fictional, made for this competition)  
- `sample_outbox.json`: the output format your agent must produce  
- `check_env.py` and `requirements.txt`: to test your setup and API key

## What your agent must do

For every email in `data/inbox/`, on its own and without a human copying anything between steps:

1. Understand the email and decide a category. Start with fee, hostel, academic and technical. You may add your own categories if you think they help.  
2. Look up the relevant rules in `policy.md`.  
3. Decide the priority (low, medium, high) and whether a human must handle it (escalate).  
4. Write a reply draft that follows the policy.  
5. Save the result to `outbox.json` using the format in `sample_outbox.json`.  
6. Log what it did at each step so you can show its reasoning.

## Requirements

- One command (for example `python agent.py`) processes everything in `data/inbox/` and writes `outbox.json`.  
- It must also work on new email files dropped into `data/inbox/`, without changing your code. Your agent may be tested on emails you have not seen.  
- Nothing is sent to real people. Drafts are only saved to `outbox.json`.  
- The agent must decide by itself (not a fixed script written for the 20 samples).

## Output format (one object per email)

`email_id`, `category`, `priority`, `escalate` (true or false), `escalation_reason`, `policy_refs` (list of policy codes), `reply_draft`, `confidence` (0 to 1), `agent_notes` (short reasoning).

## Ideas if you finish early

- A simple status dashboard (Streamlit or an HTML page) that reads `outbox.json`  
- Your own category list and a priority scheme you can defend  
- Handling emails in Roman Urdu, emails with several problems, or messages that make no sense  
- Resisting emails that try to give instructions to your agent  
- Retry and error handling when the AI service is slow or fails

## Submission

Email your code folder (zip) to \[smaasu.etc@gmail.com\] before \[3 PM, 14 Oct 26\]. Include a `README` with how to run it and a short note on your approach. Subject line: `AgentSprint_<TeamName>`.

## Presentation

5 to 10 minutes, spoken, no slides. Show it running, explain how it makes decisions, and be ready for the judges' questions on your approach and choices.