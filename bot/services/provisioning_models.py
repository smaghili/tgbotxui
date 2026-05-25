from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class InboundAccess:
    panel_id: int
    panel_name: str
    inbound_id: int
    inbound_name: str
    access_id: int | None = None
    delegated_admin_user_id: int | None = None
    delegated_admin_title: str | None = None


@dataclass(slots=True, frozen=True)
class ManagedClientRef:
    panel_id: int
    panel_name: str
    inbound_id: int
    inbound_name: str
    client_uuid: str
    client_email: str
