"""Load environment variables and project constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root (parent of src/) — always absolute
ROOT_DIR: Path = Path(__file__).resolve().parent.parent

# Load .env from project root regardless of cwd.
# Does not override variables already set in the process environment.
load_dotenv(ROOT_DIR / ".env")


def _env_key(*names: str) -> str:
    """First non-empty env var among names, stripped of quotes."""
    for name in names:
        value = (os.environ.get(name) or "").strip().strip('"').strip("'")
        if value:
            return value
    return ""


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
# Prefer live env, then values loaded from .env (GEMINI_API_KEY or GOOGLE_API_KEY).
GEMINI_API_KEY: str = _env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
ANTHROPIC_API_KEY: str = _env_key("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str = _env_key("OPENAI_API_KEY")
LLM_MODEL: str = os.getenv("LLM_MODEL", "").strip() or DEFAULT_GEMINI_MODEL

# Loop
POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))

# Body truncation for long emails
MAX_BODY_CHARS: int = 6000
