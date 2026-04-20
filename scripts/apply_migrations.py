from __future__ import annotations

import asyncio
from pathlib import Path

from bot.config import Settings
from bot.db import Database


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env()
    db_path = Path(settings.database_path)
    if not db_path.is_absolute():
        db_path = (root / db_path).resolve()

    db = Database(str(db_path))
    await db.connect()
    try:
        applied = await db.init_schema()
    finally:
        await db.close()

    print(f"Applied migrations: {applied}")
    print(f"Database path: {db_path}")


if __name__ == "__main__":
    asyncio.run(main())
