"""Load environment variables and project constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root (parent of src/) — always absolute
ROOT_DIR: Path = Path(__file__).resolve().parent.parent

# Load .env from project root regardless of cwd
load_dotenv(ROOT_DIR / ".env")

# Paths (absolute)
CREDENTIALS_PATH: Path = ROOT_DIR / "credentials.json"
TOKEN_PATH: Path = ROOT_DIR / "token.json"
DATA_DIR: Path = ROOT_DIR / "data"
DB_PATH: Path = DATA_DIR / "agent.db"
POLICY_PATH: Path = DATA_DIR / "policy.json"
TEST_EMAILS_PATH: Path = DATA_DIR / "test_emails.json"

# Gmail — drafts only; never request gmail.send
GMAIL_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.modify",
]
GMAIL_QUERY: str = os.getenv(
    "GMAIL_QUERY",
    "in:inbox -label:AGENT_PROCESSED",
)

# Agent labels
LABEL_PROCESSED: str = "AGENT_PROCESSED"
LABEL_ESCALATED: str = "ESCALATED"
LABEL_NEEDS_REVIEW: str = "NEEDS_REVIEW"

# LLM
# gemini-2.0-flash is shut down; gemini-2.5-flash is blocked for many new keys.
# gemini-3.5-flash-lite is currently available and reliable for generateContent.
DEFAULT_GEMINI_MODEL: str = "gemini-3.5-flash-lite"
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").strip() or "gemini"
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "").strip().strip('"').strip("'")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip().strip('"').strip("'")
LLM_MODEL: str = os.getenv("LLM_MODEL", "").strip() or DEFAULT_GEMINI_MODEL

# Loop
POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))

# Body truncation for long emails
MAX_BODY_CHARS: int = 6000
