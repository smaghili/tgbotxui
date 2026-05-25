from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class OperationGuardService:
    """Serialize sensitive in-process operations by stable logical keys."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()

    async def _get_lock(self, key: str) -> asyncio.Lock:
        async with self._registry_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def run(self, key: str, func: Callable[[], Awaitable[T]]) -> T:
        return await self.run_many([key], func)

    async def run_many(self, keys: list[str] | tuple[str, ...], func: Callable[[], Awaitable[T]]) -> T:
        normalized = sorted({str(key).strip() for key in keys if str(key).strip()})
        if not normalized:
            return await func()
        locks = [await self._get_lock(key) for key in normalized]
        for lock in locks:
            await lock.acquire()
        try:
            return await func()
        finally:
            for lock in reversed(locks):
                lock.release()
