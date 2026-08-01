"""
PostgreSQL registry for the Guardiola bot.

Tables
------
users
    user_id     BIGINT PRIMARY KEY    — Telegram user ID (unique, no duplicates)
    chat_id     BIGINT NOT NULL       — Telegram chat ID (same as user_id for private chats)
    first_name  TEXT                  — Telegram first name (may be empty)
    username    TEXT                  — Telegram @username (nullable)
    joined_at   TEXT NOT NULL         — ISO-8601 UTC timestamp of first /start

daily_messages
    id          SERIAL PRIMARY KEY
    chat_id     BIGINT NOT NULL       — Telegram chat ID the message was sent to
    message_id  BIGINT NOT NULL       — Telegram message_id (needed to delete it)
    sent_at     TEXT   NOT NULL       — ISO-8601 UTC timestamp of send

visits
    id          SERIAL PRIMARY KEY
    user_id     BIGINT NOT NULL
    visited_at  TEXT   NOT NULL       — ISO-8601 UTC timestamp

broadcast_messages
    id          SERIAL PRIMARY KEY
    chat_id     BIGINT NOT NULL
    message_id  BIGINT NOT NULL
    sent_at     TEXT   NOT NULL

config
    key         TEXT PRIMARY KEY
    value       TEXT NOT NULL

pending_deletions
    id          SERIAL PRIMARY KEY
    chat_id     BIGINT NOT NULL       — chat where the bot message lives
    message_id  BIGINT NOT NULL       — message to delete
    delete_at   TEXT   NOT NULL       — ISO-8601 UTC timestamp of scheduled deletion
    UNIQUE (chat_id, message_id)      — one row per message

loyalty_accounts
    user_id     BIGINT PRIMARY KEY    — Telegram user ID (unique per user)
    first_name  TEXT   NOT NULL       — Telegram first name at account creation
    last_name   TEXT                  — Telegram last name (nullable)
    username    TEXT                  — Telegram @username (nullable)
    created_at  TEXT   NOT NULL       — ISO-8601 UTC timestamp of account creation
    points      INTEGER NOT NULL      — loyalty points balance (default 0)
"""

import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["DATABASE_URL"]


def _connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id    BIGINT PRIMARY KEY,
                    chat_id    BIGINT NOT NULL,
                    first_name TEXT   NOT NULL DEFAULT '',
                    username   TEXT,
                    joined_at  TEXT   NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_messages (
                    id         SERIAL PRIMARY KEY,
                    chat_id    BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    sent_at    TEXT   NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS visits (
                    id         SERIAL PRIMARY KEY,
                    user_id    BIGINT NOT NULL,
                    visited_at TEXT   NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_messages (
                    id         SERIAL PRIMARY KEY,
                    chat_id    BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    sent_at    TEXT   NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            # Coordination lock: prevents dev and production from polling simultaneously.
            # Production writes a heartbeat every 30 s; dev checks it before starting polling.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_heartbeat (
                    env       TEXT PRIMARY KEY,
                    last_seen TEXT NOT NULL
                )
            """)
            # Persistent auto-deletion queue — survives bot restarts.
            # One row per scheduled message; deleted after the message is removed.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_deletions (
                    id         SERIAL PRIMARY KEY,
                    chat_id    BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    delete_at  TEXT   NOT NULL,
                    UNIQUE (chat_id, message_id)
                )
            """)
            # Loyalty programme — one account per Telegram user, created on first visit.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_accounts (
                    user_id    BIGINT  PRIMARY KEY,
                    first_name TEXT    NOT NULL DEFAULT '',
                    last_name  TEXT,
                    username   TEXT,
                    created_at TEXT    NOT NULL,
                    points     INTEGER NOT NULL DEFAULT 0
                )
            """)
            # Loyalty history — one row per point movement, never deleted.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_history (
                    id         SERIAL  PRIMARY KEY,
                    user_id    BIGINT  NOT NULL,
                    delta      INTEGER NOT NULL,
                    reason     TEXT    NOT NULL DEFAULT '',
                    created_at TEXT    NOT NULL
                )
            """)
        conn.commit()


# ── Users ─────────────────────────────────────────────────────────────────────

def register_user_atomic(
    user_id: int,
    chat_id: int,
    first_name: str,
    username: str | None,
) -> tuple[bool, int]:
    """
    Atomically insert the user (if new) AND read the total count in one
    transaction.  Returns (is_new, total_users).

    Using a single transaction guarantees that the count returned is exactly
    consistent with the insertion — no race window between two separate DB
    calls, no possibility of returning a stale or inflated count.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, chat_id, first_name, username, joined_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, chat_id, first_name or "", username, now),
            )
            is_new = cur.rowcount > 0
            cur.execute("SELECT COUNT(*) AS cnt FROM users")
            total = cur.fetchone()["cnt"]
        conn.commit()
        return is_new, total


def get_all_users() -> list[dict]:
    """Return all registered users (for broadcast use)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, chat_id, first_name, username, joined_at "
                "FROM users ORDER BY joined_at"
            )
            return cur.fetchall()


def user_count() -> int:
    """Return the total number of registered users."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM users")
            return cur.fetchone()["cnt"]


# ── Visits ───────────────────────────────────────────────────────────────────

def log_visit(user_id: int) -> None:
    """Record every /start event (including repeat visits by the same user)."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO visits (user_id, visited_at) VALUES (%s, %s)",
                (user_id, now),
            )
        conn.commit()


def visits_today() -> int:
    """Return the number of /start events since 00:00:00 UTC today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM visits WHERE visited_at >= %s",
                (today,),
            )
            return cur.fetchone()["cnt"]


# ── Broadcast messages ────────────────────────────────────────────────────────

def save_broadcast_message(chat_id: int, message_id: int) -> None:
    """Record a broadcast message_id so it can be deleted on demand."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO broadcast_messages (chat_id, message_id, sent_at) "
                "VALUES (%s, %s, %s)",
                (chat_id, message_id, now),
            )
        conn.commit()


def get_all_broadcast_messages() -> list[dict]:
    """Return all saved broadcast message records."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, message_id FROM broadcast_messages")
            return cur.fetchall()


def clear_broadcast_messages() -> int:
    """Delete all broadcast message records. Returns the number of rows deleted."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM broadcast_messages")
            count = cur.rowcount
        conn.commit()
        return count


# ── Daily messages ────────────────────────────────────────────────────────────

def save_daily_message(chat_id: int, message_id: int) -> None:
    """Record a daily shop message so it can be deleted at midnight."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO daily_messages (chat_id, message_id, sent_at) "
                "VALUES (%s, %s, %s)",
                (chat_id, message_id, now),
            )
        conn.commit()


def get_all_daily_messages() -> list[dict]:
    """Return all saved daily message records."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, message_id FROM daily_messages")
            return cur.fetchall()


def clear_daily_messages() -> int:
    """Delete all daily message records. Returns the number of rows deleted."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM daily_messages")
            count = cur.rowcount
        conn.commit()
        return count


# ── Pending deletions ─────────────────────────────────────────────────────────

def add_pending_deletion(chat_id: int, message_id: int, delete_at: str) -> None:
    """Persist a scheduled deletion (ISO-8601 UTC timestamp). Idempotent."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pending_deletions (chat_id, message_id, delete_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_id, message_id) DO NOTHING
                """,
                (chat_id, message_id, delete_at),
            )
        conn.commit()


def remove_pending_deletion(chat_id: int, message_id: int) -> None:
    """Remove the deletion record once the message has been deleted."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pending_deletions WHERE chat_id = %s AND message_id = %s",
                (chat_id, message_id),
            )
        conn.commit()


def get_all_pending_deletions() -> list[dict]:
    """Return all scheduled deletions ordered by due time (oldest first)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chat_id, message_id, delete_at "
                "FROM pending_deletions ORDER BY delete_at"
            )
            return cur.fetchall()


# ── Bot heartbeat (dev/production conflict prevention) ────────────────────────

HEARTBEAT_STALE_SECS = 90  # heartbeat older than this means the instance is gone

def set_bot_heartbeat(env: str) -> None:
    """Upsert a heartbeat timestamp for *env* ('production' or 'development')."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bot_heartbeat (env, last_seen) VALUES (%s, %s)
                ON CONFLICT (env) DO UPDATE SET last_seen = EXCLUDED.last_seen
                """,
                (env, now),
            )
        conn.commit()


def get_bot_heartbeat(env: str) -> "datetime | None":
    """Return the last heartbeat datetime for *env*, or None if absent."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT last_seen FROM bot_heartbeat WHERE env = %s", (env,))
            row = cur.fetchone()
            if not row:
                return None
            return datetime.fromisoformat(row["last_seen"])


def clear_bot_heartbeat(env: str) -> None:
    """Remove the heartbeat row for *env* (called on clean shutdown)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bot_heartbeat WHERE env = %s", (env,))
        conn.commit()


# ── Config ────────────────────────────────────────────────────────────────────

def get_config(key: str) -> str | None:
    """Return the value for *key* from the config table, or None if absent."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM config WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else None


def set_config(key: str, value: str) -> None:
    """Upsert *key* → *value* in the config table."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO config (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, value),
            )
        conn.commit()


# ── Loyalty accounts ──────────────────────────────────────────────────────────

def get_or_create_loyalty_account(
    user_id:    int,
    first_name: str,
    last_name:  str | None,
    username:   str | None,
) -> tuple[dict, bool]:
    """
    Retrieve the loyalty account for *user_id*, creating it if it doesn't exist yet.

    Returns (account, is_new) where account is a dict with keys:
        user_id, first_name, last_name, username, created_at, points

    The account is created with 0 points and the current UTC timestamp.
    If the account already exists the existing row is returned unchanged —
    no fields are updated on subsequent calls.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO loyalty_accounts
                    (user_id, first_name, last_name, username, created_at, points)
                VALUES (%s, %s, %s, %s, %s, 0)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, first_name or "", last_name, username, now),
            )
            is_new = cur.rowcount > 0
            cur.execute(
                """
                SELECT user_id, first_name, last_name, username, created_at, points
                FROM loyalty_accounts
                WHERE user_id = %s
                """,
                (user_id,),
            )
            account = dict(cur.fetchone())
        conn.commit()
        return account, is_new


def get_loyalty_account(user_id: int) -> dict | None:
    """Return the loyalty account for *user_id*, or None if it doesn't exist."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, first_name, last_name, username, created_at, points
                FROM loyalty_accounts
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None


def search_loyalty_users(query: str) -> list[dict]:
    """
    Search loyalty accounts by:
    • Exact user_id (if the query is purely numeric)
    • username — case-insensitive substring (leading @ is stripped)
    • first_name — case-insensitive substring
    Returns up to 10 results ordered by first_name.
    """
    stripped = query.lstrip("@").strip()
    with _connect() as conn:
        with conn.cursor() as cur:
            # Exact user_id match takes priority
            if stripped.isdigit():
                cur.execute(
                    """
                    SELECT user_id, first_name, last_name, username, created_at, points
                    FROM loyalty_accounts WHERE user_id = %s
                    """,
                    (int(stripped),),
                )
                rows = cur.fetchall()
                if rows:
                    return [dict(r) for r in rows]
            # Substring match on username / first_name
            pattern = f"%{stripped}%"
            cur.execute(
                """
                SELECT user_id, first_name, last_name, username, created_at, points
                FROM loyalty_accounts
                WHERE username ILIKE %s OR first_name ILIKE %s
                ORDER BY first_name
                LIMIT 10
                """,
                (pattern, pattern),
            )
            return [dict(r) for r in cur.fetchall()]


def update_loyalty_points(user_id: int, delta: int) -> dict | None:
    """
    Add *delta* to loyalty_accounts.points, clamped to a minimum of 0.
    Returns the updated account dict, or None if the account does not exist.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE loyalty_accounts
                SET points = GREATEST(0, points + %s)
                WHERE user_id = %s
                RETURNING user_id, first_name, last_name, username, created_at, points
                """,
                (delta, user_id),
            )
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def add_loyalty_history(user_id: int, delta: int, reason: str) -> None:
    """
    Insert one row into loyalty_history for a point movement.
    Never raises — logs errors silently so point updates always succeed.
    """
    from datetime import datetime, timezone as _tz
    created_at = datetime.now(_tz.utc).isoformat()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO loyalty_history (user_id, delta, reason, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (user_id, delta, reason.strip(), created_at),
                )
            conn.commit()
    except Exception:
        import logging as _log
        _log.getLogger(__name__).exception("add_loyalty_history failed user=%s", user_id)


def get_loyalty_history(user_id: int, limit: int = 15) -> list[dict]:
    """
    Return the last *limit* point movements for *user_id*, newest first.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, delta, reason, created_at
                FROM loyalty_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]
