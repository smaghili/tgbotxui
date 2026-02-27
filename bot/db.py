from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from bot.migration_runner import MigrationRunner


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON;")
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def init_schema(self) -> None:
        assert self.conn is not None
        runner = MigrationRunner(self.conn, str(Path(__file__).resolve().parent / "migrations"))
        await runner.migrate()

    async def upsert_user(
        self, telegram_user_id: int, full_name: str, username: str | None, is_admin: bool
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO users (telegram_user_id, full_name, username, is_admin, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                full_name=excluded.full_name,
                username=excluded.username,
                is_admin=excluded.is_admin,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (telegram_user_id, full_name, username, int(is_admin)),
        )
        await self.conn.commit()

    async def find_user_by_username(self, username: str) -> Dict[str, Any] | None:
        assert self.conn is not None
        normalized = username.strip().lstrip("@")
        if not normalized:
            return None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, full_name, username, is_admin
            FROM users
            WHERE LOWER(username)=LOWER(?)
            LIMIT 1;
            """,
            (normalized,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_user_language(self, telegram_user_id: int) -> str:
        assert self.conn is not None
        cur = await self.conn.execute(
            "SELECT language FROM users WHERE telegram_user_id=? LIMIT 1;",
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return "fa"
        value = str(row["language"] or "fa").strip().lower()
        return value if value in {"fa", "en"} else "fa"

    async def set_user_language(self, telegram_user_id: int, language: str) -> None:
        assert self.conn is not None
        lang = language.strip().lower()
        if lang not in {"fa", "en"}:
            lang = "fa"
        await self.conn.execute(
            """
            UPDATE users
            SET language=?, updated_at=CURRENT_TIMESTAMP
            WHERE telegram_user_id=?;
            """,
            (lang, telegram_user_id),
        )
        await self.conn.commit()

    async def add_panel(
        self,
        *,
        name: str,
        base_url: str,
        web_base_path: str,
        login_path: str,
        username_enc: str,
        password_enc: str,
        two_factor_enc: str | None,
        created_by: int,
    ) -> int:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            INSERT INTO panels (
                name, base_url, web_base_path, login_path, username_enc, password_enc, two_factor_enc, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                name,
                base_url,
                web_base_path,
                login_path,
                username_enc,
                password_enc,
                two_factor_enc,
                created_by,
            ),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def get_panel(self, panel_id: int) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT * FROM panels WHERE id=?;", (panel_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_panels(self) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, name, base_url, web_base_path, login_path, is_default, last_login_ok, last_error, updated_at
            FROM panels ORDER BY id DESC;
            """
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_default_panel(self) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, name, base_url, web_base_path, login_path, is_default, last_login_ok, last_error, updated_at
            FROM panels
            WHERE is_default=1
            LIMIT 1;
            """
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_default_panel(self, panel_id: int) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT id FROM panels WHERE id=? LIMIT 1;", (panel_id,))
        row = await cur.fetchone()
        if row is None:
            return False
        await self.conn.execute("UPDATE panels SET is_default=0 WHERE is_default=1;")
        await self.conn.execute("UPDATE panels SET is_default=1 WHERE id=?;", (panel_id,))
        await self.conn.commit()
        return True

    async def clear_default_panel(self) -> None:
        assert self.conn is not None
        await self.conn.execute("UPDATE panels SET is_default=0 WHERE is_default=1;")
        await self.conn.commit()

    async def delete_panel(self, panel_id: int) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute("DELETE FROM panels WHERE id=?;", (panel_id,))
        await self.conn.commit()
        return (cur.rowcount or 0) > 0

    async def set_panel_login_status(self, panel_id: int, ok: bool, last_error: str | None) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            UPDATE panels
            SET last_login_ok=?, last_error=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?;
            """,
            (int(ok), last_error, panel_id),
        )
        await self.conn.commit()

    async def save_panel_session(self, panel_id: int, cookies: Dict[str, str]) -> None:
        assert self.conn is not None
        raw = json.dumps(cookies, ensure_ascii=False)
        await self.conn.execute(
            """
            INSERT INTO panel_sessions(panel_id, cookies_json)
            VALUES (?, ?)
            ON CONFLICT(panel_id) DO UPDATE SET
                cookies_json=excluded.cookies_json,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (panel_id, raw),
        )
        await self.conn.commit()

    async def get_panel_session(self, panel_id: int) -> Dict[str, str] | None:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT cookies_json FROM panel_sessions WHERE panel_id=?;", (panel_id,))
        row = await cur.fetchone()
        if not row:
            return None
        return json.loads(row["cookies_json"])

    async def bind_user_service(
        self,
        *,
        telegram_user_id: int,
        panel_id: int,
        inbound_id: int | None,
        client_email: str,
        client_id: str | None,
        service_name: str,
        total_bytes: int,
        used_bytes: int,
        expire_at: int | None,
        status: str,
        last_synced_at: int,
    ) -> int:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO user_services (
                telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                total_bytes, used_bytes, expire_at, status, last_synced_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id, panel_id, client_email) DO UPDATE SET
                inbound_id=excluded.inbound_id,
                client_id=excluded.client_id,
                service_name=excluded.service_name,
                total_bytes=excluded.total_bytes,
                used_bytes=excluded.used_bytes,
                expire_at=excluded.expire_at,
                status=excluded.status,
                last_synced_at=excluded.last_synced_at,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                telegram_user_id,
                panel_id,
                inbound_id,
                client_email,
                client_id,
                service_name,
                total_bytes,
                used_bytes,
                expire_at,
                status,
                last_synced_at,
            ),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            """
            SELECT id FROM user_services
            WHERE telegram_user_id=? AND panel_id=? AND client_email=?;
            """,
            (telegram_user_id, panel_id, client_email),
        )
        row = await cur.fetchone()
        return int(row["id"])

    async def get_user_services(self, telegram_user_id: int) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                   total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            WHERE telegram_user_id=?
            ORDER BY id ASC;
            """,
            (telegram_user_id,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_user_service_by_id(self, service_id: int) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                   total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            WHERE id=?
            LIMIT 1;
            """,
            (service_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_all_user_services(self) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                   total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            ORDER BY id ASC;
            """
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def update_user_service_stats(
        self,
        *,
        service_id: int,
        total_bytes: int,
        used_bytes: int,
        expire_at: int | None,
        status: str,
        service_name: str,
        client_id: str | None,
        inbound_id: int | None,
        last_synced_at: int,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            UPDATE user_services
            SET total_bytes=?, used_bytes=?, expire_at=?, status=?, service_name=?, client_id=?, inbound_id=?,
                last_synced_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?;
            """,
            (
                total_bytes,
                used_bytes,
                expire_at,
                status,
                service_name,
                client_id,
                inbound_id,
                last_synced_at,
                service_id,
            ),
        )
        await self.conn.commit()

    async def add_usage_snapshot(
        self,
        *,
        user_service_id: int,
        used_bytes: int,
        total_bytes: int,
        remaining_bytes: int | None,
        status: str,
        synced_at: int,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO usage_snapshots (
                user_service_id, used_bytes, total_bytes, remaining_bytes, status, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (user_service_id, used_bytes, total_bytes, remaining_bytes, status, synced_at),
        )
        await self.conn.commit()

    async def add_audit_log(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        success: bool = True,
        details: str | None = None,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO audit_logs(actor_user_id, action, target_type, target_id, success, details)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (actor_user_id, action, target_type, target_id, int(success), details),
        )
        await self.conn.commit()

    async def count_panels(self) -> int:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT COUNT(*) AS cnt FROM panels;")
        row = await cur.fetchone()
        return int(row["cnt"])

    async def count_user_services(self) -> int:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT COUNT(*) AS cnt FROM user_services;")
        row = await cur.fetchone()
        return int(row["cnt"])
