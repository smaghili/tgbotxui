from __future__ import annotations

from pathlib import Path

import aiosqlite


class MigrationRunner:
    def __init__(self, conn: aiosqlite.Connection, migrations_dir: str) -> None:
        self.conn = conn
        self.migrations_dir = Path(migrations_dir)

    async def _ensure_table(self) -> None:
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await self.conn.commit()

    async def migrate(self) -> int:
        await self._ensure_table()
        cursor = await self.conn.execute("SELECT version FROM schema_migrations;")
        rows = await cursor.fetchall()
        applied = {str(row[0]) for row in rows}

        if not self.migrations_dir.exists():
            raise FileNotFoundError(f"Migrations directory not found: {self.migrations_dir}")

        count = 0
        for file in sorted(self.migrations_dir.glob("*.sql")):
            version = file.stem
            if version in applied:
                continue
            sql = file.read_text(encoding="utf-8")
            await self.conn.executescript(sql)
            await self.conn.execute(
                "INSERT INTO schema_migrations(version) VALUES (?);",
                (version,),
            )
            await self.conn.commit()
            count += 1
        return count
