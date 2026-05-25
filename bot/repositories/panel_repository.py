from __future__ import annotations

import json
from typing import Any

from bot.db import Database


class PanelRepository:
    def __init__(self, *, db: Database) -> None:
        self.db = db

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
        api_version: str,
        api_token_enc: str | None,
        created_by: int,
    ) -> int:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            INSERT INTO panels (
                name, base_url, web_base_path, login_path, username_enc, password_enc,
                two_factor_enc, api_version, api_token_enc, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                name,
                base_url,
                web_base_path,
                login_path,
                username_enc,
                password_enc,
                two_factor_enc,
                api_version,
                api_token_enc,
                created_by,
            ),
        )
        await self.db.conn.commit()
        return int(cur.lastrowid)

    async def get_panel(self, panel_id: int) -> dict[str, Any] | None:
        assert self.db.conn is not None
        cur = await self.db.conn.execute("SELECT * FROM panels WHERE id=?;", (panel_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_panels(self) -> list[dict[str, Any]]:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT id, name, base_url, web_base_path, login_path, api_version, created_by, is_default, last_login_ok, last_error, updated_at
            FROM panels ORDER BY id DESC;
            """
        )
        return [dict(row) for row in await cur.fetchall()]

    async def get_default_panel(self) -> dict[str, Any] | None:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT id, name, base_url, web_base_path, login_path, api_version, created_by, is_default, last_login_ok, last_error, updated_at
            FROM panels
            WHERE is_default=1
            LIMIT 1;
            """
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_default_panel(self, panel_id: int) -> bool:
        assert self.db.conn is not None
        cur = await self.db.conn.execute("SELECT id FROM panels WHERE id=? LIMIT 1;", (panel_id,))
        row = await cur.fetchone()
        if row is None:
            return False
        await self.db.conn.execute("UPDATE panels SET is_default=0 WHERE is_default=1;")
        await self.db.conn.execute("UPDATE panels SET is_default=1 WHERE id=?;", (panel_id,))
        await self.db.conn.commit()
        return True

    async def clear_default_panel(self) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute("UPDATE panels SET is_default=0 WHERE is_default=1;")
        await self.db.conn.commit()

    async def delete_panel(self, panel_id: int) -> bool:
        assert self.db.conn is not None
        cur = await self.db.conn.execute("DELETE FROM panels WHERE id=?;", (panel_id,))
        await self.db.conn.commit()
        return (cur.rowcount or 0) > 0

    async def set_panel_login_status(self, panel_id: int, ok: bool, last_error: str | None) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            """
            UPDATE panels
            SET last_login_ok=?, last_error=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?;
            """,
            (int(ok), last_error, panel_id),
        )
        await self.db.conn.commit()

    async def save_panel_session(self, panel_id: int, cookies: dict[str, str]) -> None:
        assert self.db.conn is not None
        raw = json.dumps(cookies, ensure_ascii=False)
        await self.db.conn.execute(
            """
            INSERT INTO panel_sessions(panel_id, cookies_json)
            VALUES (?, ?)
            ON CONFLICT(panel_id) DO UPDATE SET
                cookies_json=excluded.cookies_json,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (panel_id, raw),
        )
        await self.db.conn.commit()

    async def get_panel_session(self, panel_id: int) -> dict[str, str] | None:
        assert self.db.conn is not None
        cur = await self.db.conn.execute("SELECT cookies_json FROM panel_sessions WHERE panel_id=?;", (panel_id,))
        row = await cur.fetchone()
        if not row:
            return None
        return json.loads(row["cookies_json"])
