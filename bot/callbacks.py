from __future__ import annotations

from dataclasses import dataclass

MAX_QUERY_LEN = 20
NOOP = "noop"


@dataclass(frozen=True, slots=True)
class OnlinePageCallback:
    mode: str
    panel_id: int
    page: int
    query: str | None = None


@dataclass(frozen=True, slots=True)
class InboundPageCallback:
    panel_id: int
    inbound_id: int
    page: int


def encode_online_page(mode: str, panel_id: int, page: int, query: str | None = None) -> str:
    if mode == "sr" and query:
        safe_query = query.replace(":", " ").strip()[:MAX_QUERY_LEN]
        return f"uop:{mode}:{panel_id}:{page}:{safe_query}"
    return f"uop:{mode}:{panel_id}:{page}"


def parse_online_page(data: str) -> OnlinePageCallback:
    parts = data.split(":", 4)
    if len(parts) < 4 or parts[0] != "uop":
        raise ValueError("invalid_online_page_callback")
    mode = parts[1]
    panel_id = int(parts[2])
    page = int(parts[3])
    query = parts[4] if len(parts) > 4 else None
    return OnlinePageCallback(mode=mode, panel_id=panel_id, page=page, query=query)


def encode_inbound_page(panel_id: int, inbound_id: int, page: int) -> str:
    return f"uip:{panel_id}:{inbound_id}:{page}"


def parse_inbound_page(data: str) -> InboundPageCallback:
    parts = data.split(":", 3)
    if len(parts) != 4 or parts[0] != "uip":
        raise ValueError("invalid_inbound_page_callback")
    return InboundPageCallback(panel_id=int(parts[1]), inbound_id=int(parts[2]), page=int(parts[3]))
