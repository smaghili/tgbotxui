from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import Settings
from bot.db import Database


async def main() -> None:
    settings = Settings.from_env()
    db_path = Path(settings.database_path)
    if not db_path.is_absolute():
        db_path = (ROOT_DIR / db_path).resolve()

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
