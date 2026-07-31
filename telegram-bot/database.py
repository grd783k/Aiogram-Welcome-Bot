"""
SQLite registry for the Guardiola bot.

Tables
------
users
    user_id     INTEGER PRIMARY KEY   — Telegram user ID (unique, no duplicates)
    chat_id     INTEGER NOT NULL      — Telegram chat ID (same as user_id for private chats)
    first_name  TEXT                  — Telegram first name (may be empty)
    username    TEXT                  — Telegram @username (nullable)
    joined_at   TEXT NOT NULL         — ISO-8601 UTC timestamp of first /start

daily_messages
    id          INTEGER PRIMARY KEY AUTOINCREMENT
    chat_id     INTEGER NOT NULL      — Telegram chat ID the message was sent to
    message_id  INTEGER NOT NULL      — Telegram message_id (needed to delete it)
    sent_at     TEXT    NOT NULL      — ISO-8601 UTC timestamp of send
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sent_at    TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS visits (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                visited_at TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sent_at    TEXT    NOT NULL
            )
        """)
        conn.commit()


# ── Users ─────────────────────────────────────────────────────────────────────

def register_user(
    user_id: int,
    chat_id: int,
    first_name: str,
    username: str | None,
) -> bool:
    """
    Insert the user if not already registered.
    Returns True if newly inserted, False if they already existed.
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
        return cursor.rowcount > 0


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


# ── Visits ───────────────────────────────────────────────────────────────────

def log_visit(user_id: int) -> None:
    """Record every /start event (including repeat visits by the same user)."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO visits (user_id, visited_at) VALUES (?, ?)",
            (user_id, now),
        )
        conn.commit()


def visits_today() -> int:
    """Return the number of /start events since 00:00:00 UTC today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM visits WHERE visited_at >= ?",
            (today,),
        ).fetchone()[0]


# ── Broadcast messages ────────────────────────────────────────────────────────

def save_broadcast_message(chat_id: int, message_id: int) -> None:
    """Record a broadcast message_id so it can be deleted on demand."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO broadcast_messages (chat_id, message_id, sent_at) VALUES (?, ?, ?)",
            (chat_id, message_id, now),
        )
        conn.commit()


def get_all_broadcast_messages() -> list[sqlite3.Row]:
    """Return all saved broadcast message records."""
    with _connect() as conn:
        return conn.execute(
            "SELECT chat_id, message_id FROM broadcast_messages"
        ).fetchall()


def clear_broadcast_messages() -> int:
    """Delete all broadcast message records. Returns the number of rows deleted."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM broadcast_messages")
        conn.commit()
        return cursor.rowcount


# ── Daily messages ────────────────────────────────────────────────────────────

def save_daily_message(chat_id: int, message_id: int) -> None:
    """Record a daily shop message so it can be deleted at midnight."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO daily_messages (chat_id, message_id, sent_at) VALUES (?, ?, ?)",
            (chat_id, message_id, now),
        )
        conn.commit()


def get_all_daily_messages() -> list[sqlite3.Row]:
    """Return all saved daily message records."""
    with _connect() as conn:
        return conn.execute(
            "SELECT chat_id, message_id FROM daily_messages"
        ).fetchall()


def clear_daily_messages() -> int:
    """Delete all daily message records. Returns the number of rows deleted."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM daily_messages")
        conn.commit()
        return cursor.rowcount
