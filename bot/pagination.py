from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def paginate_window(total: int, page: int, per_page: int) -> tuple[int, int, int, int]:
    total_pages = max(1, (max(0, total) + per_page - 1) // per_page)
    safe_page = max(1, min(page, total_pages))
    start = (safe_page - 1) * per_page
    end = start + per_page
    return safe_page, total_pages, start, end


def chunk_buttons(items: list[T], columns: int = 2) -> list[list[T]]:
    rows: list[list[T]] = []
    current: list[T] = []
    for item in items:
        current.append(item)
        if len(current) == columns:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return rows
