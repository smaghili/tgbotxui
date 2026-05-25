from __future__ import annotations

from bot.db import Database


class ClientRepository:
    def __init__(self, *, db: Database) -> None:
        self.db = db

    async def upsert_client_owner(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        owner_user_id: int,
        client_email: str | None = None,
    ) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            """
            INSERT INTO client_owners (
                panel_id, inbound_id, client_uuid, owner_user_id, client_email, updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(panel_id, inbound_id, client_uuid) DO UPDATE SET
                owner_user_id=excluded.owner_user_id,
                client_email=excluded.client_email,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (panel_id, inbound_id, client_uuid, owner_user_id, client_email),
        )
        await self.db.conn.commit()

    async def get_client_owner(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> int | None:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT owner_user_id
            FROM client_owners
            WHERE panel_id=? AND inbound_id=? AND client_uuid=?
            LIMIT 1;
            """,
            (panel_id, inbound_id, client_uuid),
        )
        row = await cur.fetchone()
        return int(row["owner_user_id"]) if row and row["owner_user_id"] is not None else None
