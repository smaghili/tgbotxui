from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import datetime
from typing import Any, Dict, Awaitable, Callable
from urllib.parse import quote, urlencode, urlparse, urlunparse

from bot.db import Database
from bot.utils import inbound_display_name
from bot.services.crypto import CryptoService
from bot.services.xui_client import (
    PanelConnection,
    XUIAuthError,
    XUIClient,
    XUIError,
    parse_login_url,
)
from bot.utils import gb_to_bytes, parse_epoch


class PanelService:
    def __init__(
        self,
        db: Database,
        crypto: CryptoService,
        xui: XUIClient,
        sub_url_strip_port_rules: dict[str, str] | None = None,
        sub_url_base_overrides: dict[str, str] | None = None,
    ) -> None:
        self.db = db
        self.crypto = crypto
        self.xui = xui
        self.sub_url_strip_port_rules = sub_url_strip_port_rules or {}
        self.sub_url_base_overrides = sub_url_base_overrides or {}

    async def _build_conn(self, panel_id: int) -> PanelConnection:
        panel = await self.db.get_panel(panel_id)
        if not panel:
            raise ValueError("panel not found.")
        return PanelConnection(
            base_url=panel["base_url"],
            web_base_path=panel["web_base_path"],
            login_path=panel["login_path"],
            username=self.crypto.decrypt(panel["username_enc"]) or "",
            password=self.crypto.decrypt(panel["password_enc"]) or "",
            two_factor=self.crypto.decrypt(panel["two_factor_enc"]),
        )

    async def add_panel(
        self,
        *,
        name: str,
        login_url: str,
        username: str,
        password: str,
        two_factor_code: str | None,
        created_by: int,
    ) -> Dict[str, Any]:
        base_url, web_base_path, login_path = parse_login_url(login_url)
        conn = PanelConnection(
            base_url=base_url,
            web_base_path=web_base_path,
            login_path=login_path,
            username=username,
            password=password,
            two_factor=two_factor_code or None,
        )
        cookies = await self.xui.login(conn)
        panel_id = await self.db.add_panel(
            name=name.strip(),
            base_url=base_url,
            web_base_path=web_base_path,
            login_path=login_path,
            username_enc=self.crypto.encrypt(username) or "",
            password_enc=self.crypto.encrypt(password) or "",
            two_factor_enc=self.crypto.encrypt(two_factor_code),
            created_by=created_by,
        )
        await self.db.save_panel_session(panel_id, cookies)
        await self.db.set_panel_login_status(panel_id, ok=True, last_error=None)
        panel = await self.db.get_panel(panel_id)
        if not panel:
            raise ValueError("failed to save panel")
        return panel

    async def list_panels(self) -> list[Dict[str, Any]]:
        return await self.db.list_panels()

    async def get_panel(self, panel_id: int) -> Dict[str, Any] | None:
        return await self.db.get_panel(panel_id)

    async def get_default_panel(self) -> Dict[str, Any] | None:
        return await self.db.get_default_panel()

    async def resolve_panel_id(self, panel_id: int | None) -> int:
        if panel_id is not None:
            panel = await self.db.get_panel(panel_id)
            if not panel:
                raise ValueError("selected panel not found.")
            return panel_id
        default_panel = await self.db.get_default_panel()
        if not default_panel:
            raise ValueError("default panel is not selected.")
        return int(default_panel["id"])

    async def toggle_default_panel(self, panel_id: int) -> tuple[bool, bool]:
        current = await self.db.get_default_panel()
        if current and int(current["id"]) == panel_id:
            await self.db.clear_default_panel()
            return True, False
        changed = await self.db.set_default_panel(panel_id)
        return changed, True

    async def delete_panel(self, panel_id: int) -> bool:
        return await self.db.delete_panel(panel_id)

    async def _with_auth_request(
        self,
        panel_id: int,
        request_fn: Callable[[PanelConnection, Dict[str, str] | None], Awaitable[tuple[Dict[str, Any], Dict[str, str]]]],
    ) -> tuple[Dict[str, Any], Dict[str, str]]:
        conn = await self._build_conn(panel_id)
        cookies = await self.db.get_panel_session(panel_id)
        try:
            body, response_cookies = await request_fn(conn, cookies)
        except XUIAuthError:
            cookies = await self.xui.login(conn)
            await self.db.save_panel_session(panel_id, cookies)
            body, response_cookies = await request_fn(conn, cookies)
        merged = dict(cookies or {})
        merged.update(response_cookies or {})
        if merged:
            await self.db.save_panel_session(panel_id, merged)
        await self.db.set_panel_login_status(panel_id, ok=True, last_error=None)
        return body, merged

    async def _with_auth_get_traffic(
        self, panel_id: int, client_email: str
    ) -> tuple[Dict[str, Any], Dict[str, str]]:
        return await self._with_auth_request(
            panel_id,
            lambda conn, cookies: self.xui.get_client_traffics(conn, cookies, client_email),
        )

    async def list_inbounds(self, panel_id: int) -> list[Dict[str, Any]]:
        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.get_inbounds_list(conn, cookies),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise
        obj = raw.get("obj", [])
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        if isinstance(obj, dict):
            return [obj]
        return []

    async def _get_inbound_by_id(
        self,
        panel_id: int,
        inbound_id: int,
        *,
        attempts: int = 3,
    ) -> Dict[str, Any] | None:
        for attempt in range(max(1, attempts)):
            inbounds = await self.list_inbounds(panel_id)
            inbound = next((x for x in inbounds if int(x.get("id") or -1) == inbound_id), None)
            if inbound is not None:
                return inbound
            if attempt < attempts - 1:
                await asyncio.sleep(0.75 * (attempt + 1))
        return None

    @staticmethod
    def inbound_label(inbound: dict[str, Any]) -> str:
        return inbound_display_name(inbound)

    async def panel_inbound_names(self, panel_id: int, inbound_id: int | None) -> tuple[str, str]:
        panel_name = str(panel_id)
        inbound_name = "-" if inbound_id is None else f"inbound-{inbound_id}"
        panel = await self.db.get_panel(panel_id)
        if panel is not None:
            panel_name = str(panel.get("name") or panel_id)
        if inbound_id is None:
            return panel_name, inbound_name
        try:
            inbounds = await self.list_inbounds(panel_id)
        except Exception:
            return panel_name, inbound_name
        inbound = next((item for item in inbounds if int(item.get("id") or 0) == inbound_id), None)
        if inbound is not None:
            inbound_name = self.inbound_label(inbound)
        return panel_name, inbound_name

    async def list_online_clients(
        self,
        panel_id: int,
        *,
        owner_admin_user_id: int | None = None,
        allowed_inbound_ids: set[int] | None = None,
    ) -> list[Dict[str, Any]]:
        clients = await self.list_clients(
            panel_id,
            online_only=True,
            owner_admin_user_id=owner_admin_user_id,
            allowed_inbound_ids=allowed_inbound_ids,
        )
        clients.sort(key=lambda item: (item["email"].lower(), item["inbound_id"], item["uuid"]))
        return clients

    @staticmethod
    def _parse_last_online_value(raw: Any) -> int | None:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        # 3x-ui may return epoch in milliseconds.
        if value > 10_000_000_000:
            value //= 1000
        return value

    async def _get_online_keys(self, panel_id: int) -> set[str]:
        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.get_online_clients(conn, cookies),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise
        obj = raw.get("obj", [])
        if not isinstance(obj, list):
            return set()
        return {str(item).strip().lower() for item in obj if str(item).strip()}

    @staticmethod
    def _owner_id_from_comment(comment: str) -> int | None:
        value = comment.strip()
        owner_raw = value.split(":", 1)[0].strip()
        return int(owner_raw) if owner_raw.isdigit() else None

    @classmethod
    def _owner_id_for_client(cls, *, mapped_owner_id: int | None, comment: str) -> int | None:
        comment_owner_id = cls._owner_id_from_comment(comment)
        return mapped_owner_id or comment_owner_id


    async def _get_last_online_map(self, panel_id: int) -> dict[str, int]:
        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.get_last_online(conn, cookies),
            )
        except XUIError:
            # Keep feature best-effort; callers can still operate without this map.
            return {}
        obj = raw.get("obj", {})
        if not isinstance(obj, dict):
            return {}
        out: dict[str, int] = {}
        for key, value in obj.items():
            parsed = self._parse_last_online_value(value)
            if parsed is not None:
                out[str(key).strip().lower()] = parsed
        return out

    async def list_clients(
        self,
        panel_id: int,
        *,
        online_only: bool = False,
        enabled: bool | None = None,
        email_query: str | None = None,
        include_last_online: bool = False,
        owner_admin_user_id: int | None = None,
        allowed_inbound_ids: set[int] | None = None,
    ) -> list[Dict[str, Any]]:
        online_keys: set[str] = set()
        if online_only:
            online_keys = await self._get_online_keys(panel_id)
            if not online_keys:
                return []

        last_online_map: dict[str, int] = {}
        if include_last_online:
            last_online_map = await self._get_last_online_map(panel_id)

        owner_map: dict[tuple[int, str], int] = {}
        if owner_admin_user_id is not None:
            owner_map = await self.db.list_client_owners_for_panel(panel_id)

        inbounds = await self.list_inbounds(panel_id)
        matched: list[Dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        query_norm = (email_query or "").strip().lower()
        for inbound in inbounds:
            inbound_id = int(inbound.get("id") or 0)
            if inbound_id <= 0:
                continue
            if allowed_inbound_ids is not None and inbound_id not in allowed_inbound_ids:
                continue
            for client in self._extract_inbound_clients(inbound):
                email = str(client.get("email") or "").strip()
                uuid = str(client.get("uuid") or client.get("id") or "").strip()
                sub_id = str(client.get("subId") or "").strip()
                comment = str(client.get("comment") or "").strip()
                if not email or not uuid:
                    continue
                if owner_admin_user_id is not None:
                    owner_id = self._owner_id_for_client(
                        mapped_owner_id=owner_map.get((inbound_id, uuid)),
                        comment=comment,
                    )
                    if owner_id != owner_admin_user_id:
                        continue
                candidates = {email.lower(), uuid.lower(), sub_id.lower()}
                if online_only and not any(c and c in online_keys for c in candidates):
                    continue
                is_enabled = bool(client.get("enable", True))
                if enabled is not None and is_enabled is not enabled:
                    continue
                if query_norm and query_norm not in email.lower():
                    continue
                dedupe_key = (inbound_id, uuid)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                last_online = None
                if include_last_online:
                    for candidate in candidates:
                        if candidate and candidate in last_online_map:
                            last_online = last_online_map[candidate]
                            break
                matched.append(
                    {
                        "panel_id": panel_id,
                        "inbound_id": inbound_id,
                        "uuid": uuid,
                        "email": email,
                        "enabled": is_enabled,
                        "tg_id": str(client.get("tgId") or "").strip(),
                        "sub_id": sub_id,
                        "comment": comment,
                        "last_online": last_online,
                    }
                )
        return matched

    async def search_clients_by_email(
        self,
        panel_id: int,
        query: str,
        *,
        owner_admin_user_id: int | None = None,
        allowed_inbound_ids: set[int] | None = None,
    ) -> list[Dict[str, Any]]:
        rows = await self.list_clients(
            panel_id,
            email_query=query,
            owner_admin_user_id=owner_admin_user_id,
            allowed_inbound_ids=allowed_inbound_ids,
        )
        rows.sort(key=lambda item: (item["email"].lower(), item["inbound_id"], item["uuid"]))
        return rows

    async def list_disabled_clients(
        self,
        panel_id: int,
        *,
        owner_admin_user_id: int | None = None,
        allowed_inbound_ids: set[int] | None = None,
    ) -> list[Dict[str, Any]]:
        rows = await self.list_clients(
            panel_id,
            owner_admin_user_id=owner_admin_user_id,
            allowed_inbound_ids=allowed_inbound_ids,
        )
        inactive: list[Dict[str, Any]] = []
        now = int(time.time())
        for row in rows:
            status = "active"
            try:
                detail = await self.get_client_detail(panel_id, int(row["inbound_id"]), str(row["uuid"]))
                enabled = bool(detail.get("enabled", row.get("enabled", True)))
                total = int(detail.get("total") or 0)
                used = int(detail.get("used") or 0)
                expiry = parse_epoch(detail.get("expiry"))
            except Exception:
                enabled = bool(row.get("enabled", True))
                total = int(row.get("total") or 0)
                used = int(row.get("used") or 0)
                expiry = parse_epoch(row.get("expiry"))

            if not enabled:
                status = "suspended"
            elif expiry and expiry <= now:
                status = "expired"
            elif total > 0 and used >= total:
                status = "depleted"

            if status != "active":
                row["status"] = status
                inactive.append(row)
        rows = inactive
        rows.sort(key=lambda item: (item["email"].lower(), item["inbound_id"], item["uuid"]))
        return rows

    async def list_low_traffic_clients(
        self,
        panel_id: int,
        *,
        threshold_mb: int,
        owner_admin_user_id: int | None = None,
        allowed_inbound_ids: set[int] | None = None,
    ) -> list[Dict[str, Any]]:
        threshold_bytes = max(0, int(threshold_mb)) * 1024 * 1024
        if threshold_bytes <= 0:
            return []
        rows = await self.list_clients(
            panel_id,
            owner_admin_user_id=owner_admin_user_id,
            allowed_inbound_ids=allowed_inbound_ids,
        )
        low_traffic: list[Dict[str, Any]] = []
        for row in rows:
            try:
                detail = await self.get_client_detail(panel_id, int(row["inbound_id"]), str(row["uuid"]))
            except Exception:
                continue
            total = int(detail.get("total") or 0)
            if total <= 0:
                continue
            used = int(detail.get("used") or 0)
            remaining = max(total - used, 0)
            if remaining <= 0 or remaining > threshold_bytes:
                continue
            row.update(
                {
                    "enabled": bool(detail.get("enabled", row.get("enabled", True))),
                    "remaining_bytes": remaining,
                    "total": total,
                    "used": used,
                }
            )
            low_traffic.append(row)
        low_traffic.sort(
            key=lambda item: (
                int(item.get("remaining_bytes") or 0),
                item["email"].lower(),
                item["inbound_id"],
                item["uuid"],
            )
        )
        return low_traffic

    async def cleanup_depleted_clients(self, delete_after_hours: int) -> dict[str, Any]:
        now = int(time.time())
        threshold_seconds = max(0, int(delete_after_hours)) * 3600
        scanned = 0
        deleted = 0
        failed = 0
        skipped_no_last_online = 0
        deleted_clients: list[dict[str, Any]] = []

        for panel in await self.list_panels():
            panel_id = int(panel["id"])
            try:
                clients = await self.list_clients(panel_id, include_last_online=True)
            except Exception:
                failed += 1
                continue
            for client in clients:
                scanned += 1
                inbound_id = int(client.get("inbound_id") or 0)
                client_uuid = str(client.get("uuid") or "").strip()
                email = str(client.get("email") or "").strip()
                if inbound_id <= 0 or not client_uuid:
                    continue
                try:
                    detail = await self.get_client_detail(panel_id, inbound_id, client_uuid)
                    total = int(detail.get("total") or 0)
                    used = int(detail.get("used") or 0)
                    expiry = parse_epoch(detail.get("expiry"))
                    is_depleted = total > 0 and used >= total
                    is_expired = bool(expiry and expiry <= now)
                    delete_reason = "expired" if is_expired else "depleted"
                except Exception:
                    failed += 1
                    continue

                if not (is_depleted or is_expired):
                    continue

                last_online = parse_epoch(client.get("last_online"))
                if not last_online:
                    skipped_no_last_online += 1
                    continue
                if now - last_online < threshold_seconds:
                    continue

                try:
                    await self.delete_client(panel_id, inbound_id, client_uuid)
                    if email:
                        await self.db.add_audit_log(
                            actor_user_id=None,
                            action="auto_cleanup_deleted_client",
                            target_type="client",
                            target_id=client_uuid,
                            success=True,
                            details=f"panel={panel_id};inbound={inbound_id};email={email}",
                        )
                    deleted_clients.append(
                        {
                            "panel_id": panel_id,
                            "panel_name": str(panel.get("name") or panel_id),
                            "inbound_id": inbound_id,
                            "inbound_name": (await self.panel_inbound_names(panel_id, inbound_id))[1],
                            "client_uuid": client_uuid,
                            "email": email or str(detail.get("email") or client_uuid),
                            "reason": delete_reason,
                        }
                    )
                except Exception:
                    failed += 1
                    continue
                deleted += 1

        return {
            "scanned": scanned,
            "deleted": deleted,
            "failed": failed,
            "skipped_no_last_online": skipped_no_last_online,
            "deleted_clients": deleted_clients,
        }

    async def bind_services_for_telegram_identity(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
    ) -> int:
        candidates = {str(telegram_user_id)}
        username_norm = (username or "").strip().lstrip("@").lower()
        if username_norm:
            candidates.add(username_norm)
            candidates.add(f"@{username_norm}")

        bound = 0
        for panel in await self.list_panels():
            panel_id = int(panel["id"])
            try:
                clients = await self.list_clients(panel_id)
            except Exception:
                continue
            for client in clients:
                tg_id = str(client.get("tg_id") or "").strip().lower()
                if not tg_id or tg_id not in candidates:
                    continue
                try:
                    await self.bind_service_to_user(
                        panel_id=panel_id,
                        telegram_user_id=telegram_user_id,
                        client_email=str(client["email"]),
                        service_name=None,
                        inbound_id=int(client["inbound_id"]),
                    )
                except Exception:
                    continue
                bound += 1
        return bound

    async def list_clients_with_last_online(
        self,
        panel_id: int,
        *,
        owner_admin_user_id: int | None = None,
        allowed_inbound_ids: set[int] | None = None,
    ) -> list[Dict[str, Any]]:
        rows = await self.list_clients(
            panel_id,
            include_last_online=True,
            owner_admin_user_id=owner_admin_user_id,
            allowed_inbound_ids=allowed_inbound_ids,
        )
        rows = [row for row in rows if int(row.get("last_online") or 0) > 0]
        rows.sort(key=lambda item: (-int(item.get("last_online") or 0), item["email"].lower()))
        return rows

    @staticmethod
    def _extract_inbound_clients(inbound: Dict[str, Any]) -> list[Dict[str, Any]]:
        settings_raw = inbound.get("settings")
        if isinstance(settings_raw, str) and settings_raw.strip():
            try:
                parsed = json.loads(settings_raw)
                clients = parsed.get("clients", [])
                if isinstance(clients, list):
                    rows: list[Dict[str, Any]] = []
                    for item in clients:
                        if isinstance(item, dict):
                            client = dict(item)
                            if "id" in client and "uuid" not in client:
                                client["uuid"] = client.get("id")
                            if "email" not in client:
                                client["email"] = ""
                            if "comment" not in client:
                                client["comment"] = ""
                            rows.append(client)
                    if rows:
                        return rows
            except json.JSONDecodeError:
                pass

        client_stats = inbound.get("clientStats")
        if isinstance(client_stats, list):
            rows = []
            for item in client_stats:
                if isinstance(item, dict):
                    rows.append(
                        {
                            "uuid": item.get("uuid") or item.get("id"),
                            "id": item.get("uuid") or item.get("id"),
                            "email": item.get("email") or "",
                            "enable": item.get("enable"),
                            "expiryTime": item.get("expiryTime"),
                            "totalGB": item.get("total"),
                            "limitIp": item.get("limitIp"),
                            "subId": item.get("subId"),
                            "reset": item.get("reset", 0),
                            "tgId": item.get("tgId", ""),
                            "comment": item.get("comment", ""),
                        }
                    )
            return rows
        return []

    async def list_inbound_clients(
        self,
        panel_id: int,
        inbound_id: int,
        *,
        owner_admin_user_id: int | None = None,
    ) -> list[Dict[str, Any]]:
        inbound = await self._get_inbound_by_id(panel_id, inbound_id)
        if inbound is None:
            raise ValueError("inbound not found.")
        clients = self._extract_inbound_clients(inbound)
        owner_map: dict[tuple[int, str], int] = {}
        if owner_admin_user_id is not None:
            owner_map = await self.db.list_client_owners_for_panel(panel_id)
        out: list[Dict[str, Any]] = []
        for client in clients:
            uuid = str(client.get("uuid") or client.get("id") or "").strip()
            email = str(client.get("email") or "").strip()
            comment = str(client.get("comment") or "").strip()
            if not uuid or not email:
                continue
            if owner_admin_user_id is not None:
                owner_id = self._owner_id_for_client(
                    mapped_owner_id=owner_map.get((inbound_id, uuid)),
                    comment=comment,
                )
                if owner_id != owner_admin_user_id:
                    continue
            out.append({"uuid": uuid, "email": email, "comment": comment})
        return out

    async def find_client_by_uuid(
        self,
        panel_id: int,
        client_uuid: str,
        *,
        allowed_inbound_ids: set[int] | None = None,
        owner_admin_user_id: int | None = None,
    ) -> Dict[str, Any] | None:
        target_uuid = client_uuid.strip()
        if not target_uuid:
            return None
        owner_map: dict[tuple[int, str], int] = {}
        if owner_admin_user_id is not None:
            owner_map = await self.db.list_client_owners_for_panel(panel_id)
        inbounds = await self.list_inbounds(panel_id)
        for inbound in inbounds:
            inbound_id = int(inbound.get("id") or 0)
            if inbound_id <= 0:
                continue
            if allowed_inbound_ids is not None and inbound_id not in allowed_inbound_ids:
                continue
            for client in self._extract_inbound_clients(inbound):
                uuid = str(client.get("uuid") or client.get("id") or "").strip()
                if uuid != target_uuid:
                    continue
                comment = str(client.get("comment") or "").strip()
                if owner_admin_user_id is not None:
                    owner_id = self._owner_id_for_client(
                        mapped_owner_id=owner_map.get((inbound_id, uuid)),
                        comment=comment,
                    )
                    if owner_id != owner_admin_user_id:
                        continue
                return {
                    "panel_id": panel_id,
                    "inbound_id": inbound_id,
                    "uuid": uuid,
                    "email": str(client.get("email") or "").strip(),
                    "sub_id": str(client.get("subId") or "").strip(),
                    "enabled": bool(client.get("enable", True)),
                    "comment": comment,
                }
        return None

    async def _get_client_config(
        self, panel_id: int, inbound_id: int, client_uuid: str
    ) -> tuple[Dict[str, Any], Dict[str, Any], list[Dict[str, Any]]]:
        inbound = await self._get_inbound_by_id(panel_id, inbound_id)
        if inbound is None:
            raise ValueError("inbound not found.")
        clients = self._extract_inbound_clients(inbound)
        current = next(
            (
                c
                for c in clients
                if str(c.get("uuid") or c.get("id") or "").strip() == client_uuid.strip()
            ),
            None,
        )
        if current is None:
            raise ValueError("client not found on this inbound.")
        return inbound, current, clients

    async def _update_client_by_mutation(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        mutator: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> None:
        inbound, current, _ = await self._get_client_config(panel_id, inbound_id, client_uuid)
        changed = mutator(dict(current))
        payload_client = {
            "id": changed.get("uuid") or changed.get("id"),
            "flow": changed.get("flow", ""),
            "email": changed.get("email", ""),
            "comment": changed.get("comment", ""),
            "limitIp": int(changed.get("limitIp") or 0),
            "totalGB": int(changed.get("totalGB") or 0),
            "expiryTime": int(changed.get("expiryTime") or 0),
            "enable": bool(changed.get("enable", True)),
            "tgId": changed.get("tgId", ""),
            "subId": changed.get("subId", ""),
            "reset": int(changed.get("reset") or 0),
        }
        update_payload = {
            "id": int(inbound.get("id") or inbound_id),
            "settings": json.dumps({"clients": [payload_client]}, ensure_ascii=False),
        }
        try:
            await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.update_client(
                    conn,
                    cookies,
                    client_uuid=client_uuid,
                    payload=update_payload,
                ),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise

    @staticmethod
    def _new_sub_id(length: int = 16) -> str:
        raw = secrets.token_urlsafe(length)
        safe = "".join(ch for ch in raw if ch.isalnum())
        return (safe or secrets.token_hex(8))[:length]

    async def create_client(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_email: str,
        total_gb: float,
        expiry_days: int,
        enable: bool = True,
        tg_id: str = "",
        comment: str = "",
    ) -> Dict[str, Any]:
        inbound = await self._get_inbound_by_id(panel_id, inbound_id)
        if inbound is None:
            raise ValueError("inbound not found.")

        email = client_email.strip()
        if not email:
            raise ValueError("client email is empty.")

        for existing in self._extract_inbound_clients(inbound):
            if str(existing.get("email") or "").strip().lower() == email.lower():
                raise ValueError("client email already exists on this inbound.")

        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.get_new_uuid(conn, cookies),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise

        obj = raw.get("obj") if isinstance(raw, dict) else None
        client_uuid = str((obj or {}).get("uuid") or "").strip() if isinstance(obj, dict) else ""
        if not client_uuid:
            raise ValueError("new UUID was not returned from server.")

        flow = ""
        for existing in self._extract_inbound_clients(inbound):
            flow = str(existing.get("flow") or "").strip()
            if flow:
                break

        total_bytes = gb_to_bytes(total_gb)
        expiry_ms = int((time.time() + (max(0, int(expiry_days)) * 86400)) * 1000)
        payload_client = {
            "id": client_uuid,
            "flow": flow,
            "email": email,
            "comment": comment.strip(),
            "limitIp": 0,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "enable": bool(enable),
            "tgId": tg_id.strip(),
            "subId": self._new_sub_id(),
            "reset": 0,
        }
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [payload_client]}, ensure_ascii=False),
        }
        try:
            await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.add_client(conn, cookies, payload=payload),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise
        return {
            "panel_id": panel_id,
            "inbound_id": inbound_id,
            "uuid": client_uuid,
            "email": email,
            "sub_id": payload_client["subId"],
        }

    async def delete_client(self, panel_id: int, inbound_id: int, client_uuid: str) -> None:
        client_email = ""
        try:
            detail = await self.get_client_detail(panel_id, inbound_id, client_uuid)
            client_email = str(detail.get("email") or "").strip()
        except Exception:
            client_email = ""
        try:
            await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.delete_client(
                    conn,
                    cookies,
                    inbound_id=inbound_id,
                    client_uuid=client_uuid,
                ),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise
        if client_email:
            await self.db.mark_user_services_deleted_by_panel_email(
                panel_id=panel_id,
                client_email=client_email,
                status="deleted",
                last_synced_at=int(time.time()),
            )

    async def get_client_traffic_by_uuid(self, panel_id: int, client_uuid: str) -> Dict[str, Any]:
        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.get_client_traffics_by_id(conn, cookies, client_uuid),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise
        item = self._pick_traffic_obj(raw, client_uuid)
        up = int(item.get("up") or 0)
        down = int(item.get("down") or 0)
        total = int(item.get("total") or -1)
        expiry = parse_epoch(item.get("expiryTime") or item.get("expiry_time"))
        enabled = bool(item.get("enable", True))
        last_online = parse_epoch(item.get("lastOnline"))
        return {
            "up": up,
            "down": down,
            "used": up + down,
            "total": total,
            "expiry": expiry,
            "enabled": enabled,
            "last_online": last_online,
            "email": item.get("email"),
        }

    async def get_client_detail(self, panel_id: int, inbound_id: int, client_uuid: str) -> Dict[str, Any]:
        _, config, _ = await self._get_client_config(panel_id, inbound_id, client_uuid)
        traffic = await self.get_client_traffic_by_uuid(panel_id, client_uuid)
        email = str(config.get("email") or traffic.get("email") or "").strip()
        now = int(time.time())
        last_online = traffic.get("last_online")
        online = bool(last_online and (now - int(last_online) <= 300))
        enabled = bool(config.get("enable", traffic.get("enabled", True)))
        expiry = parse_epoch(config.get("expiryTime")) or traffic.get("expiry")
        total_bytes = int(config.get("totalGB") or 0)
        return {
            "uuid": client_uuid,
            "email": email,
            "enabled": enabled,
            "online": online,
            "expiry": expiry,
            "up": int(traffic.get("up") or 0),
            "down": int(traffic.get("down") or 0),
            "used": int(traffic.get("used") or 0),
            "total": total_bytes,
            "limit_ip": int(config.get("limitIp") or 0),
            "tg_id": str(config.get("tgId") or ""),
            "comment": str(config.get("comment") or ""),
        }

    async def set_client_total_gb(
        self, panel_id: int, inbound_id: int, client_uuid: str, total_gb: float | None
    ) -> None:
        total_bytes = 0 if total_gb is None else gb_to_bytes(total_gb)
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            mutator=lambda c: {**c, "totalGB": total_bytes},
        )

    async def add_client_total_gb(
        self,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        add_gb: float,
        *,
        comment: str | None = None,
    ) -> int:
        _, current, _ = await self._get_client_config(panel_id, inbound_id, client_uuid)
        current_bytes = int(current.get("totalGB") or 0)
        if current_bytes < 0:
            current_bytes = 0
        new_total = current_bytes + gb_to_bytes(add_gb)
        new_comment = str(comment).strip() if comment is not None else str(current.get("comment") or "")
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            mutator=lambda c: {**c, "totalGB": new_total, "comment": new_comment},
        )
        return new_total

    async def set_client_expiry_days(
        self, panel_id: int, inbound_id: int, client_uuid: str, days: int | None
    ) -> None:
        if days is None:
            expiry = 0
        else:
            expiry = int((time.time() + (max(0, days) * 86400)) * 1000)
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            mutator=lambda c: {**c, "expiryTime": expiry},
        )

    async def extend_client_expiry_days(
        self, panel_id: int, inbound_id: int, client_uuid: str, add_days: int
    ) -> int:
        _, current, _ = await self._get_client_config(panel_id, inbound_id, client_uuid)
        now_ms = int(time.time() * 1000)
        current_expiry = int(current.get("expiryTime") or 0)
        base = current_expiry if current_expiry > now_ms else now_ms
        new_expiry = base + (max(0, int(add_days)) * 86400 * 1000)
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            mutator=lambda c: {**c, "expiryTime": new_expiry},
        )
        return new_expiry

    async def set_client_limit_ip(
        self, panel_id: int, inbound_id: int, client_uuid: str, limit_ip: int | None
    ) -> None:
        limit = 0 if limit_ip is None else max(0, int(limit_ip))
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            mutator=lambda c: {**c, "limitIp": limit},
        )

    async def set_client_tg_id(
        self, panel_id: int, inbound_id: int, client_uuid: str, tg_id: str
    ) -> None:
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            mutator=lambda c: {**c, "tgId": tg_id.strip()},
        )

    async def toggle_client_enable(self, panel_id: int, inbound_id: int, client_uuid: str) -> bool:
        _, current, _ = await self._get_client_config(panel_id, inbound_id, client_uuid)
        new_enable = not bool(current.get("enable", True))
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            mutator=lambda c: {**c, "enable": new_enable},
        )
        return new_enable

    async def reset_client_traffic(self, panel_id: int, inbound_id: int, email: str) -> None:
        try:
            await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.reset_client_traffic(
                    conn,
                    cookies,
                    inbound_id=inbound_id,
                    email=email,
                ),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise

    async def clear_client_ips(self, panel_id: int, email: str) -> None:
        try:
            await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.clear_client_ips(conn, cookies, email),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise

    async def get_client_ips(self, panel_id: int, email: str) -> str:
        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.client_ips(conn, cookies, email),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise
        obj = raw.get("obj")
        if obj is None:
            return "No IP Record"
        if isinstance(obj, str):
            return obj
        return json.dumps(obj, ensure_ascii=False)

    async def rotate_client_uuid_by_email(
        self, panel_id: int, inbound_id: int | None, client_email: str
    ) -> str:
        target_inbound, target_client = await self._find_client_on_panel(panel_id, inbound_id, client_email)
        if target_inbound is None or target_client is None:
            raise ValueError("client not found on panel.")

        old_uuid = str(target_client.get("uuid") or target_client.get("id") or "").strip()
        if not old_uuid:
            raise ValueError("current client UUID is not identifiable.")

        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.get_new_uuid(conn, cookies),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise

        obj = raw.get("obj") if isinstance(raw, dict) else None
        new_uuid = str((obj or {}).get("uuid") or "").strip() if isinstance(obj, dict) else ""
        if not new_uuid:
            raise ValueError("new UUID was not returned from server.")

        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=int(target_inbound.get("id") or inbound_id or 0),
            client_uuid=old_uuid,
            mutator=lambda c: {**c, "uuid": new_uuid, "id": new_uuid},
        )
        return new_uuid

    async def prepare_client_rotation_by_email(
        self, panel_id: int, inbound_id: int | None, client_email: str
    ) -> dict[str, Any]:
        target_inbound, target_client = await self._find_client_on_panel(panel_id, inbound_id, client_email)
        if target_inbound is None or target_client is None:
            raise ValueError("client not found on panel.")

        old_uuid = str(target_client.get("uuid") or target_client.get("id") or "").strip()
        if not old_uuid:
            raise ValueError("current client UUID is not identifiable.")

        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.get_new_uuid(conn, cookies),
            )
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise
        obj = raw.get("obj") if isinstance(raw, dict) else None
        new_uuid = str((obj or {}).get("uuid") or "").strip() if isinstance(obj, dict) else ""
        if not new_uuid:
            raise ValueError("new UUID was not returned from server.")

        new_sub_id = self._new_sub_id()
        preview_client = dict(target_client)
        preview_client["uuid"] = new_uuid
        preview_client["id"] = new_uuid
        preview_client["subId"] = new_sub_id
        vless_uri = await self._build_client_vless_uri(panel_id, target_inbound, preview_client, client_email)
        sub_url = await self._build_client_subscription_url(panel_id, preview_client)
        return {
            "panel_id": panel_id,
            "inbound_id": int(target_inbound.get("id") or inbound_id or 0),
            "email": str(preview_client.get("email") or client_email).strip(),
            "old_uuid": old_uuid,
            "new_uuid": new_uuid,
            "new_sub_id": new_sub_id,
            "vless_uri": vless_uri,
            "sub_url": sub_url,
        }

    async def apply_prepared_client_rotation(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        old_uuid: str,
        new_uuid: str,
        new_sub_id: str,
    ) -> None:
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=old_uuid,
            mutator=lambda c: {**c, "uuid": new_uuid, "id": new_uuid, "subId": new_sub_id},
        )

    @staticmethod
    def _parse_json_obj(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                obj = json.loads(value)
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _search_host(headers: Any) -> str:
        if not isinstance(headers, dict):
            return ""
        for key, value in headers.items():
            if str(key).lower() != "host":
                continue
            if isinstance(value, list):
                return str(value[0] or "").strip() if value else ""
            return str(value or "").strip()
        return ""

    @staticmethod
    def _search_key(data: Any, key: str) -> Any:
        if isinstance(data, dict):
            for item_key, value in data.items():
                if item_key == key:
                    return value
                found = PanelService._search_key(value, key)
                if found is not None:
                    return found
        if isinstance(data, list):
            for value in data:
                found = PanelService._search_key(value, key)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _first_string(value: Any) -> str:
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
            return ""
        return str(value or "").strip()

    @staticmethod
    def _parse_port(value: Any) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _gen_link_remark(inbound: Dict[str, Any], client: Dict[str, Any], client_email: str, extra: str = "") -> str:
        parts = [
            str(extra or "").strip(),
            str(client.get("email") or client_email).strip(),
        ]
        return "-".join([part for part in parts if part])

    @staticmethod
    def _build_vless_uri(
        *,
        client_uuid: str,
        host: str,
        port: int,
        params: Dict[str, str],
        remark: str,
    ) -> str:
        query = urlencode(params, doseq=False, safe=",:/")
        return f"vless://{client_uuid}@{host}:{port}?{query}#{quote(remark)}"

    def _normalize_subscription_url(self, panel: Dict[str, Any], sub_url: str) -> str:
        parsed = urlparse(sub_url)
        host = (parsed.hostname or "").strip().lower()
        if not host or parsed.port is None:
            return sub_url

        panel_keys = {
            str(panel.get("id") or "").strip().lower(),
            str(panel.get("name") or "").strip().lower(),
        }
        strip_hosts: set[str] = set()
        for panel_key in panel_keys:
            if panel_key:
                rule = self.sub_url_strip_port_rules.get(panel_key, "")
                if rule:
                    strip_hosts.add((urlparse(rule).hostname or "").strip().lower())
        wildcard_rule = self.sub_url_strip_port_rules.get("*", "")
        if wildcard_rule:
            strip_hosts.add((urlparse(wildcard_rule).hostname or "").strip().lower())
        if host not in strip_hosts:
            return sub_url

        netloc = parsed.hostname or ""
        if ":" in netloc and not netloc.startswith("["):
            netloc = f"[{netloc}]"
        return urlunparse(parsed._replace(netloc=netloc))

    def _panel_config_keys(self, panel: Dict[str, Any]) -> set[str]:
        return {
            value
            for value in (
                str(panel.get("id") or "").strip().lower(),
                str(panel.get("name") or "").strip().lower(),
            )
            if value
        }

    def _subscription_base_override(self, panel: Dict[str, Any]) -> str:
        for panel_key in self._panel_config_keys(panel):
            rule = self.sub_url_strip_port_rules.get(panel_key)
            if rule:
                return rule.rstrip("/")
            override = self.sub_url_base_overrides.get(panel_key)
            if override:
                return override.rstrip("/")
        return (
            self.sub_url_strip_port_rules.get("*", "")
            or self.sub_url_base_overrides.get("*", "")
        ).rstrip("/")

    def is_subscription_enabled_for_panel(self, panel: Dict[str, Any]) -> bool:
        return bool(self._subscription_base_override(panel))

    async def _get_panel_default_settings(self, panel_id: int) -> Dict[str, Any]:
        try:
            raw, _ = await self._with_auth_request(
                panel_id,
                lambda conn, cookies: self.xui.get_default_settings(conn, cookies),
            )
        except XUIError:
            return {}
        obj = raw.get("obj") if isinstance(raw, dict) else None
        return obj if isinstance(obj, dict) else {}

    async def _find_client_on_panel(
        self, panel_id: int, inbound_id: int | None, client_email: str
    ) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
        inbounds = await self.list_inbounds(panel_id)
        email_norm = client_email.strip().lower()
        target_inbound: Dict[str, Any] | None = None
        target_client: Dict[str, Any] | None = None

        def _scan_inbound(inbound: Dict[str, Any]) -> Dict[str, Any] | None:
            for c in self._extract_inbound_clients(inbound):
                if str(c.get("email") or "").strip().lower() == email_norm:
                    return c
            return None

        if inbound_id is not None:
            candidate = next((x for x in inbounds if int(x.get("id") or -1) == int(inbound_id)), None)
            if candidate is not None:
                found = _scan_inbound(candidate)
                if found is not None:
                    return candidate, found

        for inbound in inbounds:
            found = _scan_inbound(inbound)
            if found is not None:
                target_inbound = inbound
                target_client = found
                break
        return target_inbound, target_client

    async def _build_client_vless_uri(
        self,
        panel_id: int,
        target_inbound: Dict[str, Any],
        target_client: Dict[str, Any],
        client_email: str,
    ) -> str:
        panel = await self.db.get_panel(panel_id)
        if panel is None:
            raise ValueError("panel not found.")

        protocol = str(target_inbound.get("protocol") or "").strip().lower()
        if protocol != "vless":
            raise ValueError(f"protocol {protocol or '-'} is not supported for vless link.")

        client_uuid = str(target_client.get("uuid") or target_client.get("id") or "").strip()
        if not client_uuid:
            raise ValueError("client UUID not found.")

        listen = str(target_inbound.get("listen") or target_inbound.get("Listen") or "").strip()
        if listen and listen not in {"0.0.0.0", "::", "::0"}:
            base_host = listen
        else:
            base_host = (urlparse(str(panel.get("base_url") or "")).hostname or "").strip()
        port = int(target_inbound.get("port") or 0)
        if not base_host or port <= 0:
            raise ValueError("valid host/port for config generation was not found.")

        settings_obj = self._parse_json_obj(target_inbound.get("settings"))
        stream_obj = self._parse_json_obj(target_inbound.get("streamSettings"))
        network = str(stream_obj.get("network") or "tcp")
        security = str(stream_obj.get("security") or "none")

        params: Dict[str, str] = {
            "encryption": str(settings_obj.get("encryption") or "none"),
            "security": security,
            "type": network,
        }

        clients = settings_obj.get("clients")
        if isinstance(clients, list):
            for c in clients:
                if not isinstance(c, dict):
                    continue
                cid = str(c.get("id") or "").strip()
                if cid == client_uuid:
                    flow = str(c.get("flow") or "").strip()
                    if flow and network == "tcp" and security in {"tls", "reality"}:
                        params["flow"] = flow
                    break

        if network == "ws":
            ws = self._parse_json_obj(stream_obj.get("wsSettings"))
            path = str(ws.get("path") or "/")
            host = str(ws.get("host") or "").strip()
            if not host:
                host = self._search_host(ws.get("headers"))
            if host:
                params["host"] = host
            params["path"] = path
        elif network == "grpc":
            grpc = self._parse_json_obj(stream_obj.get("grpcSettings"))
            service_name = str(grpc.get("serviceName") or "").strip()
            if service_name:
                params["serviceName"] = service_name
            authority = str(grpc.get("authority") or "").strip()
            if authority:
                params["authority"] = authority
            if bool(grpc.get("multiMode")):
                params["mode"] = "multi"
        elif network == "tcp":
            tcp = self._parse_json_obj(stream_obj.get("tcpSettings"))
            header = self._parse_json_obj(tcp.get("header"))
            header_type = str(header.get("type") or "").strip()
            if header_type:
                params["headerType"] = header_type
            if header_type == "http":
                request = self._parse_json_obj(header.get("request"))
                path = self._first_string(request.get("path"))
                if path:
                    params["path"] = path
                host = self._search_host(request.get("headers"))
                if host:
                    params["host"] = host
        elif network == "kcp":
            kcp = self._parse_json_obj(stream_obj.get("kcpSettings"))
            header = self._parse_json_obj(kcp.get("header"))
            header_type = str(header.get("type") or "").strip()
            if header_type:
                params["headerType"] = header_type
            seed = str(kcp.get("seed") or "").strip()
            if seed:
                params["seed"] = seed
        elif network == "httpupgrade":
            httpupgrade = self._parse_json_obj(stream_obj.get("httpupgradeSettings"))
            path = str(httpupgrade.get("path") or "/")
            host = str(httpupgrade.get("host") or "").strip()
            if not host:
                host = self._search_host(httpupgrade.get("headers"))
            if host:
                params["host"] = host
            params["path"] = path
        elif network == "xhttp":
            xhttp = self._parse_json_obj(stream_obj.get("xhttpSettings"))
            path = str(xhttp.get("path") or "/")
            host = str(xhttp.get("host") or "").strip()
            if not host:
                host = self._search_host(xhttp.get("headers"))
            mode = str(xhttp.get("mode") or "").strip()
            if host:
                params["host"] = host
            if mode:
                params["mode"] = mode
            params["path"] = path

        if security == "tls":
            tls_obj = self._parse_json_obj(stream_obj.get("tlsSettings"))
            server_name = str(tls_obj.get("serverName") or "").strip()
            if server_name:
                params["sni"] = server_name
            alpn = tls_obj.get("alpn")
            if isinstance(alpn, list) and alpn:
                params["alpn"] = ",".join([str(x) for x in alpn if str(x).strip()])
            fingerprint = str(self._search_key(tls_obj.get("settings"), "fingerprint") or "").strip()
            if fingerprint:
                params["fp"] = fingerprint

        if security == "reality":
            reality = self._parse_json_obj(stream_obj.get("realitySettings"))
            reality_settings = reality.get("settings")
            pbk = str(self._search_key(reality_settings, "publicKey") or reality.get("publicKey") or "").strip()
            sid = self._first_string(reality.get("shortIds") or reality.get("shortId"))
            fp = str(self._search_key(reality_settings, "fingerprint") or reality.get("fingerprint") or "").strip()
            pqv = str(self._search_key(reality_settings, "mldsa65Verify") or "").strip()
            sni = params.get("sni", "")
            if not sni:
                sni = self._first_string(reality.get("serverNames"))
            if pbk:
                params["pbk"] = pbk
            if sid:
                params["sid"] = sid
            if fp:
                params["fp"] = fp
            if pqv:
                params["pqv"] = pqv
            if sni:
                params["sni"] = sni
            spx = str(reality.get("spiderX") or "").strip()
            if spx:
                params["spx"] = spx

        external_proxies = stream_obj.get("externalProxy")
        if isinstance(external_proxies, list) and external_proxies:
            links: list[str] = []
            for proxy in external_proxies:
                if not isinstance(proxy, dict):
                    continue
                dest = str(proxy.get("dest") or "").strip()
                proxy_port = self._parse_port(proxy.get("port"))
                if not dest or proxy_port <= 0:
                    continue
                force_tls = str(proxy.get("forceTls") or "same").strip().lower()
                link_params = dict(params)
                if force_tls and force_tls != "same":
                    link_params["security"] = force_tls
                    if force_tls == "none":
                        for key in ("alpn", "sni", "fp"):
                            link_params.pop(key, None)
                remark = self._gen_link_remark(
                    target_inbound,
                    target_client,
                    client_email,
                    str(proxy.get("remark") or "").strip(),
                )
                links.append(
                    self._build_vless_uri(
                        client_uuid=client_uuid,
                        host=dest,
                        port=proxy_port,
                        params=link_params,
                        remark=remark,
                    )
                )
            if links:
                return "\n".join(links)

        remark = self._gen_link_remark(target_inbound, target_client, client_email)
        return self._build_vless_uri(
            client_uuid=client_uuid,
            host=base_host,
            port=port,
            params=params,
            remark=remark,
        )

    async def get_client_vless_uri_by_email(
        self, panel_id: int, inbound_id: int | None, client_email: str
    ) -> str:
        target_inbound, target_client = await self._find_client_on_panel(panel_id, inbound_id, client_email)
        if target_inbound is None or target_client is None:
            raise ValueError("client not found on inbound.")
        return await self._build_client_vless_uri(panel_id, target_inbound, target_client, client_email)

    async def _build_client_subscription_url(self, panel_id: int, target_client: Dict[str, Any]) -> str:
        panel = await self.db.get_panel(panel_id)
        if panel is None:
            raise ValueError("panel not found.")

        override = self._subscription_base_override(panel)
        if not override:
            return ""

        sub_id = str(target_client.get("subId") or "").strip()
        if not sub_id:
            raise ValueError("subscription id not found for client.")

        return self._normalize_subscription_url(
            panel,
            f"{override}/{quote(sub_id, safe='')}",
        )

    async def get_client_subscription_url_by_email(
        self, panel_id: int, inbound_id: int | None, client_email: str
    ) -> str:
        _, target_client = await self._find_client_on_panel(panel_id, inbound_id, client_email)
        if target_client is None:
            raise ValueError("client not found on inbound.")
        return await self._build_client_subscription_url(panel_id, target_client)

    @staticmethod
    def _pick_traffic_obj(raw: Dict[str, Any], client_email: str) -> Dict[str, Any]:
        obj = raw.get("obj", raw)
        if isinstance(obj, list):
            for item in obj:
                if str(item.get("email", "")).strip().lower() == client_email.strip().lower():
                    return item
            return obj[0] if obj else {}
        if isinstance(obj, dict):
            if "email" in obj:
                return obj
            if "client" in obj and isinstance(obj["client"], dict):
                return obj["client"]
            return obj
        return {}

    @staticmethod
    def _normalize_traffic(raw: Dict[str, Any], client_email: str) -> Dict[str, Any]:
        item = PanelService._pick_traffic_obj(raw, client_email)
        up = int(item.get("up") or 0)
        down = int(item.get("down") or 0)
        total = int(item.get("total") or -1)
        used = up + down
        expire_at = parse_epoch(item.get("expiryTime") or item.get("expiry_time"))
        enabled = bool(item.get("enable", True))
        now = int(time.time())
        if not enabled:
            status = "suspended"
        elif expire_at and expire_at <= now:
            status = "expired"
        elif total >= 0 and used >= total:
            status = "depleted"
        else:
            status = "active"
        remain = None if total < 0 else max(total - used, 0)
        return {
            "client_email": item.get("email") or client_email,
            "client_id": item.get("id") or item.get("clientId"),
            "inbound_id": item.get("inboundId"),
            "service_name": item.get("email") or client_email,
            "total_bytes": total,
            "used_bytes": used,
            "remaining_bytes": remain,
            "expire_at": expire_at,
            "status": status,
            "synced_at": now,
        }

    async def fetch_client_usage(self, panel_id: int, client_email: str) -> Dict[str, Any]:
        try:
            raw, _ = await self._with_auth_get_traffic(panel_id, client_email)
        except XUIError as exc:
            await self.db.set_panel_login_status(panel_id, ok=False, last_error=str(exc))
            raise
        return self._normalize_traffic(raw, client_email)

    async def bind_service_to_user(
        self,
        *,
        panel_id: int,
        telegram_user_id: int,
        client_email: str,
        service_name: str | None,
        inbound_id: int | None = None,
    ) -> Dict[str, Any]:
        usage = await self.fetch_client_usage(panel_id, client_email)
        service_id = await self.db.bind_user_service(
            telegram_user_id=telegram_user_id,
            panel_id=panel_id,
            inbound_id=inbound_id if inbound_id is not None else usage.get("inbound_id"),
            client_email=usage["client_email"],
            client_id=usage.get("client_id"),
            service_name=service_name or usage["service_name"],
            total_bytes=usage["total_bytes"],
            used_bytes=usage["used_bytes"],
            expire_at=usage["expire_at"],
            status=usage["status"],
            last_synced_at=usage["synced_at"],
        )
        usage["service_id"] = service_id
        usage["service_name"] = service_name or usage["service_name"]
        return usage

    @staticmethod
    def _unwrap_xray_template_string(raw: str) -> str:
        s = raw.strip()
        for _ in range(8):
            try:
                top = json.loads(s)
            except json.JSONDecodeError:
                return s
            if not isinstance(top, dict) or "xraySetting" not in top:
                return s
            for k in ("inbounds", "outbounds", "routing", "api", "dns", "log", "policy", "stats"):
                if k in top:
                    return s
            inner = top["xraySetting"]
            if isinstance(inner, str):
                inner_st = inner.strip()
                if inner_st.startswith('"'):
                    try:
                        inner_st = json.loads(inner_st)
                    except json.JSONDecodeError:
                        pass
                if isinstance(inner_st, dict):
                    s = json.dumps(inner_st, ensure_ascii=False)
                else:
                    s = str(inner_st)
                continue
            if isinstance(inner, dict):
                s = json.dumps(inner, ensure_ascii=False)
                continue
            return s
        return s

    @staticmethod
    def _parse_xray_setting_bundle(body: Dict[str, Any]) -> Dict[str, Any]:
        obj = body.get("obj")
        if isinstance(obj, str):
            wrapper = json.loads(obj)
        elif isinstance(obj, dict):
            wrapper = obj
        else:
            raise ValueError("unexpected xray panel response.")
        test_url = str(wrapper.get("outboundTestUrl") or "").strip() or "https://www.google.com/generate_204"
        xs = wrapper.get("xraySetting")
        if isinstance(xs, str):
            cfg = json.loads(PanelService._unwrap_xray_template_string(xs))
        elif isinstance(xs, dict):
            cfg = json.loads(
                PanelService._unwrap_xray_template_string(json.dumps(xs, ensure_ascii=False))
            )
        else:
            raise ValueError("missing xraySetting in panel response.")
        if not isinstance(cfg, dict):
            raise ValueError("invalid xray template.")
        return {"config": cfg, "outbound_test_url": test_url}

    @staticmethod
    def _normalize_tag_list(val: Any) -> list[str]:
        if val is None:
            return []
        if isinstance(val, str):
            return [val] if val else []
        if isinstance(val, list):
            return [str(x) for x in val if str(x)]
        return []

    @staticmethod
    def _list_outbound_tags(cfg: Dict[str, Any]) -> list[str]:
        out = cfg.get("outbounds")
        if not isinstance(out, list):
            return []
        tags: list[str] = []
        for item in out:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("tag") or "").strip()
            if tag:
                tags.append(tag)
        return sorted(set(tags))

    @staticmethod
    def _rule_matches_client(rule: Dict[str, Any], email: str, inbound_tag: str) -> bool:
        users = PanelService._normalize_tag_list(rule.get("user"))
        if email not in users:
            return False
        in_tags = PanelService._normalize_tag_list(rule.get("inboundTag"))
        if not in_tags:
            return True
        return inbound_tag in in_tags

    @staticmethod
    def _first_rule_index_for_client(rules: list[Dict[str, Any]], email: str, inbound_tag: str) -> int | None:
        for i, rule in enumerate(rules):
            if isinstance(rule, dict) and PanelService._rule_matches_client(rule, email, inbound_tag):
                return i
        return None

    @staticmethod
    def _new_rule_insert_index(rules: list[Dict[str, Any]]) -> int:
        if not rules:
            return 0
        r0 = rules[0]
        if isinstance(r0, dict) and str(r0.get("outboundTag") or "") == "api":
            if "api" in PanelService._normalize_tag_list(r0.get("inboundTag")):
                return 1
        return 0

    async def list_outbound_tags(self, panel_id: int) -> list[str]:
        raw, _ = await self._with_auth_request(
            panel_id,
            lambda conn, cookies: self.xui.get_xray_setting(conn, cookies),
        )
        bundle = self._parse_xray_setting_bundle(raw)
        return self._list_outbound_tags(bundle["config"])

    async def set_client_outbound_tag(
        self,
        panel_id: int,
        inbound_id: int,
        client_email: str,
        outbound_tag: str,
    ) -> None:
        raw, _ = await self._with_auth_request(
            panel_id,
            lambda conn, cookies: self.xui.get_xray_setting(conn, cookies),
        )
        bundle = self._parse_xray_setting_bundle(raw)
        cfg = bundle["config"]
        test_url = bundle["outbound_test_url"]
        tags = self._list_outbound_tags(cfg)
        if outbound_tag not in tags:
            raise ValueError("outbound tag not found on panel.")
        inbound_tag = f"inbound-{inbound_id}"
        email = client_email.strip()
        routing = cfg.get("routing")
        if not isinstance(routing, dict):
            routing = {}
        raw_rules = routing.get("rules")
        rules_objs: list[Dict[str, Any]] = []
        if isinstance(raw_rules, list):
            for r in raw_rules:
                rules_objs.append(dict(r) if isinstance(r, dict) else {})
        idx = self._first_rule_index_for_client(rules_objs, email, inbound_tag)
        if idx is not None:
            target = rules_objs[idx]
            target["type"] = "field"
            target["outboundTag"] = outbound_tag
            target.pop("balancerTag", None)
        else:
            ins = self._new_rule_insert_index(rules_objs)
            rules_objs.insert(
                ins,
                {
                    "type": "field",
                    "inboundTag": [inbound_tag],
                    "user": [email],
                    "outboundTag": outbound_tag,
                },
            )
        routing["rules"] = rules_objs
        cfg["routing"] = routing
        payload = json.dumps(cfg, ensure_ascii=False)
        await self._with_auth_request(
            panel_id,
            lambda conn, cookies: self.xui.update_xray_setting(
                conn,
                cookies,
                xray_setting_json=payload,
                outbound_test_url=test_url,
            ),
        )

    async def sync_single_service(self, service_row: Dict[str, Any]) -> Dict[str, Any]:
        usage = await self.fetch_client_usage(service_row["panel_id"], service_row["client_email"])
        await self.db.update_user_service_stats(
            service_id=service_row["id"],
            total_bytes=usage["total_bytes"],
            used_bytes=usage["used_bytes"],
            expire_at=usage["expire_at"],
            status=usage["status"],
            service_name=service_row.get("service_name") or usage["service_name"],
            client_id=usage.get("client_id"),
            inbound_id=usage.get("inbound_id"),
            last_synced_at=usage["synced_at"],
        )
        await self.db.add_usage_snapshot(
            user_service_id=service_row["id"],
            used_bytes=usage["used_bytes"],
            total_bytes=usage["total_bytes"],
            remaining_bytes=usage["remaining_bytes"],
            status=usage["status"],
            synced_at=usage["synced_at"],
        )
        usage["service_name"] = service_row.get("service_name") or usage["service_name"]
        return usage
