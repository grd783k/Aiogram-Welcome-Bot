"""
SQLite user registry for the Guardiola bot.

Tables
------
users
    user_id     INTEGER PRIMARY KEY   — Telegram user ID (unique, no duplicates)
    chat_id     INTEGER NOT NULL      — Telegram chat ID (same as user_id for private chats)
    first_name  TEXT                  — Telegram first name (may be empty)
    username    TEXT                  — Telegram @username (nullable)
    joined_at   TEXT NOT NULL         — ISO-8601 UTC timestamp of first /start
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "users.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                chat_id    INTEGER NOT NULL,
                first_name TEXT    NOT NULL DEFAULT '',
                username   TEXT,
                joined_at  TEXT    NOT NULL
            )
        """)
        conn.commit()


def register_user(
    user_id: int,
    chat_id: int,
    first_name: str,
    username: str | None,
) -> bool:
    """
    Insert the user if not already registered.
    Returns True if the user was newly inserted, False if they already existed.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO users (user_id, chat_id, first_name, username, joined_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, chat_id, first_name or "", username, now),
        )
        conn.commit()
        return cursor.rowcount > 0  # True → new user


def get_all_users() -> list[sqlite3.Row]:
    """Return all registered users (for broadcast use)."""
    with _connect() as conn:
        return conn.execute(
            "SELECT user_id, chat_id, first_name, username, joined_at FROM users ORDER BY joined_at"
        ).fetchall()


def user_count() -> int:
    """Return the total number of registered users."""
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
