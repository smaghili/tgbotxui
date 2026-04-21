from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "bot.db"
REQUIRED_TABLES = {
    "users",
    "audit_logs",
    "delegated_admins",
    "wallet_transactions",
}


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"' ")
    return values


def _resolve_db_path(cli_db_path: str | None) -> Path:
    if cli_db_path:
        candidate = Path(cli_db_path)
        return candidate if candidate.is_absolute() else (ROOT_DIR / candidate).resolve()

    env_path = ROOT_DIR / ".env"
    env_values = _load_env_file(env_path)
    configured = env_values.get("DATABASE_PATH") or os.getenv("DATABASE_PATH")
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_absolute() else (ROOT_DIR / candidate).resolve()
    return DEFAULT_DB_PATH.resolve()


def _parse_admin_ids() -> list[int]:
    env_values = _load_env_file(ROOT_DIR / ".env")
    raw = env_values.get("ADMIN_IDS") or os.getenv("ADMIN_IDS") or ""
    admin_ids: list[int] = []
    for chunk in raw.split(","):
        value = chunk.strip()
        if value.lstrip("-").isdigit():
            admin_ids.append(int(value))
    return admin_ids


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _print_rows(rows: list[sqlite3.Row], *, limit: int | None = None) -> None:
    if not rows:
        print("(none)")
        return
    shown = rows if limit is None else rows[:limit]
    for row in shown:
        print(dict(row))
    if limit is not None and len(rows) > limit:
        print(f"... {len(rows) - limit} more rows")


def _resolve_actor_candidates(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    normalized = query.strip()
    if not normalized:
        return []
    if normalized.lstrip("-").isdigit():
        user_id = int(normalized)
        rows = conn.execute(
            """
            SELECT u.telegram_user_id, u.full_name, u.username, da.title, da.parent_user_id, da.admin_scope
            FROM users AS u
            LEFT JOIN delegated_admins AS da ON da.telegram_user_id = u.telegram_user_id AND da.is_active = 1
            WHERE u.telegram_user_id = ?
            UNION
            SELECT da.telegram_user_id, NULL AS full_name, NULL AS username, da.title, da.parent_user_id, da.admin_scope
            FROM delegated_admins AS da
            WHERE da.telegram_user_id = ? AND da.is_active = 1
            """,
            (user_id, user_id),
        ).fetchall()
        unique: dict[int, sqlite3.Row] = {}
        for row in rows:
            unique[int(row["telegram_user_id"])] = row
        return list(unique.values())

    username = normalized.lstrip("@").lower()
    return conn.execute(
        """
        SELECT DISTINCT
            COALESCE(u.telegram_user_id, da.telegram_user_id) AS telegram_user_id,
            u.full_name,
            u.username,
            da.title,
            da.parent_user_id,
            da.admin_scope
        FROM delegated_admins AS da
        LEFT JOIN users AS u ON u.telegram_user_id = da.telegram_user_id
        WHERE da.is_active = 1
          AND (
                LOWER(COALESCE(u.username, '')) = ?
             OR LOWER(COALESCE(u.full_name, '')) LIKE ?
             OR LOWER(COALESCE(da.title, '')) LIKE ?
          )
        UNION
        SELECT
            u.telegram_user_id,
            u.full_name,
            u.username,
            da.title,
            da.parent_user_id,
            da.admin_scope
        FROM users AS u
        LEFT JOIN delegated_admins AS da ON da.telegram_user_id = u.telegram_user_id AND da.is_active = 1
        WHERE LOWER(COALESCE(u.username, '')) = ?
           OR LOWER(COALESCE(u.full_name, '')) LIKE ?
        """,
        (username, f"%{username}%", f"%{username}%", username, f"%{username}%"),
    ).fetchall()


def _get_user_row(conn: sqlite3.Connection, telegram_user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, telegram_user_id, full_name, username, is_admin, language, created_at, updated_at
        FROM users
        WHERE telegram_user_id = ?
        LIMIT 1
        """,
        (telegram_user_id,),
    ).fetchone()


def _get_delegated_row(conn: sqlite3.Connection, telegram_user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM delegated_admins WHERE telegram_user_id = ? LIMIT 1",
        (telegram_user_id,),
    ).fetchone()


def _get_parent_chain(conn: sqlite3.Connection, telegram_user_id: int) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    seen: set[int] = set()
    current_id = telegram_user_id
    while current_id and current_id not in seen:
        seen.add(current_id)
        row = _get_delegated_row(conn, current_id)
        if row is None:
            break
        parent_user_id = row["parent_user_id"] if "parent_user_id" in row.keys() else None
        chain.append(
            {
                "telegram_user_id": row["telegram_user_id"],
                "title": row["title"],
                "admin_scope": row["admin_scope"] if "admin_scope" in row.keys() else None,
                "parent_user_id": parent_user_id,
            }
        )
        if not parent_user_id:
            break
        current_id = int(parent_user_id)
    return chain


def _get_scope_window_clause(hours: int) -> tuple[str, tuple[Any, ...]]:
    return "created_at >= datetime('now', ?)", (f"-{hours} hours",)


def _query_recent_audit_logs(conn: sqlite3.Connection, actor_user_id: int, hours: int) -> list[sqlite3.Row]:
    where_clause, params = _get_scope_window_clause(hours)
    return conn.execute(
        f"""
        SELECT id, actor_user_id, action, target_type, target_id, success, details, created_at
        FROM audit_logs
        WHERE actor_user_id = ?
          AND {where_clause}
        ORDER BY id DESC
        LIMIT 200
        """,
        (actor_user_id, *params),
    ).fetchall()


def _query_recent_wallet_rows(conn: sqlite3.Connection, actor_user_id: int, hours: int) -> list[sqlite3.Row]:
    where_clause, params = _get_scope_window_clause(hours)
    table_columns = _table_columns(conn, "wallet_transactions")
    details_column = "details" if "details" in table_columns else "NULL AS details"
    metadata_column = "metadata_json" if "metadata_json" in table_columns else "NULL AS metadata_json"
    return conn.execute(
        f"""
        SELECT id, telegram_user_id, actor_user_id, amount, kind, operation, status, {details_column}, {metadata_column}, created_at
        FROM wallet_transactions
        WHERE actor_user_id = ?
          AND {where_clause}
        ORDER BY id DESC
        LIMIT 200
        """,
        (actor_user_id, *params),
    ).fetchall()


def _query_recent_notifications(conn: sqlite3.Connection, actor_user_id: int, hours: int) -> list[sqlite3.Row]:
    if "admin_activity_notifications" not in {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }:
        return []
    where_clause, params = _get_scope_window_clause(hours)
    return conn.execute(
        f"""
        SELECT id, actor_user_id, chat_id, attempts, last_error, next_attempt_at, sent_at, created_at, text
        FROM admin_activity_notifications
        WHERE actor_user_id = ?
          AND {where_clause}
        ORDER BY id DESC
        LIMIT 200
        """,
        (actor_user_id, *params),
    ).fetchall()


def _query_action_counts(conn: sqlite3.Connection, actor_user_id: int, hours: int) -> list[sqlite3.Row]:
    where_clause, params = _get_scope_window_clause(hours)
    return conn.execute(
        f"""
        SELECT action, COUNT(*) AS cnt
        FROM audit_logs
        WHERE actor_user_id = ?
          AND {where_clause}
        GROUP BY action
        ORDER BY cnt DESC, action ASC
        """,
        (actor_user_id, *params),
    ).fetchall()


def _print_relevant_audit_groups(rows: list[sqlite3.Row]) -> None:
    groups = {
        "create_client": [],
        "admin_activity": [],
        "admin_activity_notification_sent": [],
        "admin_activity_notification_queued": [],
        "admin_activity_notification_retry_failed": [],
    }
    for row in rows:
        action = str(row["action"])
        if action in groups:
            groups[action].append(row)
    for action, items in groups.items():
        _print_header(f"audit_logs action={action} count={len(items)}")
        _print_rows(items, limit=50)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose why delegated admin activity logs/notifications are missing."
    )
    parser.add_argument(
        "query",
        help="Telegram user id, @username, username, or part of delegated title/full name.",
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="Optional database path. Defaults to DATABASE_PATH from .env or data/bot.db",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=48,
        help="How many recent hours to inspect. Default: 48",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db_path)
    print(f"Database path: {db_path}")
    print(f"Root admin ids from env: {_parse_admin_ids()}")
    if not db_path.exists():
        print("Database file not found.")
        return 1

    conn = _connect(db_path)
    try:
        existing_tables = _existing_tables(conn)
        missing_tables = sorted(REQUIRED_TABLES - existing_tables)
        if missing_tables:
            print(
                "The selected database does not look like the bot database.\n"
                f"Missing tables: {', '.join(missing_tables)}\n"
                f"Current database path: {db_path}\n"
                "Hint: run with --db /opt/tgbot/data/bot.db or execute the script from the real project directory."
            )
            return 1
        candidates = _resolve_actor_candidates(conn, args.query)
        if not candidates:
            print("No matching user/delegated admin found.")
            return 1
        if len(candidates) > 1:
            _print_header("Multiple candidates found")
            _print_rows(candidates)
            print("\nRun again with the exact telegram user id.")
            return 1

        actor_user_id = int(candidates[0]["telegram_user_id"])
        _print_header("Resolved actor")
        print(dict(candidates[0]))

        _print_header("users row")
        user_row = _get_user_row(conn, actor_user_id)
        print(dict(user_row) if user_row else "(none)")

        _print_header("delegated_admins row")
        delegated_row = _get_delegated_row(conn, actor_user_id)
        print(dict(delegated_row) if delegated_row else "(none)")

        _print_header("parent chain")
        chain = _get_parent_chain(conn, actor_user_id)
        if chain:
            for item in chain:
                print(item)
        else:
            print("(none)")

        action_counts = _query_action_counts(conn, actor_user_id, args.hours)
        _print_header(f"audit action counts in last {args.hours}h")
        _print_rows(action_counts)

        audit_rows = _query_recent_audit_logs(conn, actor_user_id, args.hours)
        _print_relevant_audit_groups(audit_rows)

        _print_header(f"recent wallet_transactions for actor in last {args.hours}h")
        wallet_rows = _query_recent_wallet_rows(conn, actor_user_id, args.hours)
        _print_rows(wallet_rows, limit=100)

        _print_header(f"recent admin_activity_notifications for actor in last {args.hours}h")
        notification_rows = _query_recent_notifications(conn, actor_user_id, args.hours)
        _print_rows(notification_rows, limit=100)

        print(
            "\nDiagnostic hints:\n"
            "- If create_client exists but admin_activity is missing, the log/notify path is failing after create.\n"
            "- If admin_activity exists but no *_notification_* rows exist, recipient resolution/send path is failing or actor is not delegated.\n"
            "- If wallet rows exist for create_client but both create_client and admin_activity are missing, the actor id used for the operation is not the one you searched.\n"
            "- Emoji in actor full_name/title does not affect actor_user_id-based queries."
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
