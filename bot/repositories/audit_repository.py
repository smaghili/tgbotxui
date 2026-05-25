from __future__ import annotations

from bot.db import Database


class AuditRepository:
    def __init__(self, *, db: Database) -> None:
        self.db = db

    async def add_log(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        success: bool = True,
        details: str | None = None,
    ) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            """
            INSERT INTO audit_logs(actor_user_id, action, target_type, target_id, success, details)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (actor_user_id, action, target_type, target_id, int(success), details),
        )
        await self.db.conn.commit()
