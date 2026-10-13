"""SQLite persistence for processed emails, decisions, and activity events."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from src.config import DATA_DIR, DB_PATH


def _utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path | None = None) -> None:
    """Create tables if they do not exist."""
    path = db_path or DB_PATH
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE,
                thread_id TEXT,
                sender TEXT,
                subject TEXT,
                body_snippet TEXT,
                received_at TEXT,
                status TEXT,
                processed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                category TEXT,
                urgency TEXT,
                sentiment TEXT,
                language TEXT,
                confidence REAL,
                summary TEXT,
                escalated INTEGER,
                escalation_reason TEXT,
                is_unusual INTEGER,
                draft_id TEXT,
                draft_text TEXT,
                latency_ms INTEGER,
                FOREIGN KEY (email_id) REFERENCES emails(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            );
            """
        )


@contextmanager
def _connect(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Open a connection with row factory; commit on success."""
    path = db_path or DB_PATH
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def is_processed(message_id: str, db_path: Path | None = None) -> bool:
    """Return True if this Gmail message ID was already saved."""
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM emails WHERE message_id = ? LIMIT 1",
            (message_id,),
        ).fetchone()
    return row is not None


def save_email(
    *,
    message_id: str,
    thread_id: str,
    sender: str,
    subject: str,
    body_snippet: str,
    received_at: str = "",
    status: str = "processed",
    db_path: Path | None = None,
) -> int:
    """Insert or replace an email row. Returns the row id."""
    init_db(db_path)
    processed_at = _utc_now()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO emails (
                message_id, thread_id, sender, subject, body_snippet,
                received_at, status, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                thread_id = excluded.thread_id,
                sender = excluded.sender,
                subject = excluded.subject,
                body_snippet = excluded.body_snippet,
                received_at = excluded.received_at,
                status = excluded.status,
                processed_at = excluded.processed_at
            """,
            (
                message_id,
                thread_id,
                sender,
                subject,
                body_snippet,
                received_at,
                status,
                processed_at,
            ),
        )
        row = conn.execute(
            "SELECT id FROM emails WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    return int(row["id"])


def save_decision(
    *,
    email_id: int,
    category: str,
    urgency: str,
    sentiment: str,
    language: str,
    confidence: float,
    summary: str,
    escalated: bool,
    escalation_reason: str = "",
    is_unusual: bool = False,
    draft_id: str = "",
    draft_text: str = "",
    latency_ms: int = 0,
    db_path: Path | None = None,
) -> int:
    """Insert a classification/draft decision. Returns the decision row id."""
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO decisions (
                email_id, category, urgency, sentiment, language, confidence,
                summary, escalated, escalation_reason, is_unusual,
                draft_id, draft_text, latency_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email_id,
                category,
                urgency,
                sentiment,
                language,
                confidence,
                summary,
                1 if escalated else 0,
                escalation_reason,
                1 if is_unusual else 0,
                draft_id,
                draft_text,
                latency_ms,
            ),
        )
        return int(cur.lastrowid)


def log_event(level: str, message: str, db_path: Path | None = None) -> None:
    """Append a row to the live activity feed."""
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO events (ts, level, message) VALUES (?, ?, ?)",
            (_utc_now(), level, message),
        )


def get_sender_count(sender: str, db_path: Path | None = None) -> int:
    """Count how many emails from this sender are already in the DB."""
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM emails WHERE sender = ?",
            (sender,),
        ).fetchone()
    return int(row["n"])
