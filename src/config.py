"""Load environment variables and project constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root (parent of src/)
ROOT_DIR: Path = Path(__file__).resolve().parent.parent

load_dotenv(ROOT_DIR / ".env")

# Paths
CREDENTIALS_PATH: Path = ROOT_DIR / "credentials.json"
TOKEN_PATH: Path = ROOT_DIR / "token.json"
DATA_DIR: Path = ROOT_DIR / "data"
DB_PATH: Path = DATA_DIR / "agent.db"
POLICY_PATH: Path = DATA_DIR / "policy.json"

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
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "")

# Loop
POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))

# Body truncation for long emails
MAX_BODY_CHARS: int = 6000
