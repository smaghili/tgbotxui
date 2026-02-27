from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, Awaitable, Callable
from urllib.parse import quote, urlencode, urlparse

from bot.db import Database
from bot.services.crypto import CryptoService
from bot.services.xui_client import (
    PanelConnection,
    XUIAuthError,
    XUIClient,
    XUIError,
    parse_login_url,
)
from bot.utils import parse_epoch


class PanelService:
    def __init__(self, db: Database, crypto: CryptoService, xui: XUIClient) -> None:
        self.db = db
        self.crypto = crypto
        self.xui = xui

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

    async def list_online_clients(self, panel_id: int) -> list[Dict[str, Any]]:
        clients = await self.list_clients(panel_id, online_only=True)
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
    ) -> list[Dict[str, Any]]:
        online_keys: set[str] = set()
        if online_only:
            online_keys = await self._get_online_keys(panel_id)
            if not online_keys:
                return []

        last_online_map: dict[str, int] = {}
        if include_last_online:
            last_online_map = await self._get_last_online_map(panel_id)

        inbounds = await self.list_inbounds(panel_id)
        matched: list[Dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        query_norm = (email_query or "").strip().lower()
        for inbound in inbounds:
            inbound_id = int(inbound.get("id") or 0)
            if inbound_id <= 0:
                continue
            for client in self._extract_inbound_clients(inbound):
                email = str(client.get("email") or "").strip()
                uuid = str(client.get("uuid") or client.get("id") or "").strip()
                sub_id = str(client.get("subId") or "").strip()
                if not email or not uuid:
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
                        "sub_id": sub_id,
                        "last_online": last_online,
                    }
                )
        return matched

    async def search_clients_by_email(self, panel_id: int, query: str) -> list[Dict[str, Any]]:
        rows = await self.list_clients(panel_id, email_query=query)
        rows.sort(key=lambda item: (item["email"].lower(), item["inbound_id"], item["uuid"]))
        return rows

    async def list_disabled_clients(self, panel_id: int) -> list[Dict[str, Any]]:
        rows = await self.list_clients(panel_id, enabled=False)
        rows.sort(key=lambda item: (item["email"].lower(), item["inbound_id"], item["uuid"]))
        return rows

    async def list_clients_with_last_online(self, panel_id: int) -> list[Dict[str, Any]]:
        rows = await self.list_clients(panel_id, include_last_online=True)
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
                        }
                    )
            return rows
        return []

    async def list_inbound_clients(self, panel_id: int, inbound_id: int) -> list[Dict[str, Any]]:
        inbounds = await self.list_inbounds(panel_id)
        inbound = next((x for x in inbounds if int(x.get("id") or -1) == inbound_id), None)
        if inbound is None:
            raise ValueError("inbound not found.")
        clients = self._extract_inbound_clients(inbound)
        out: list[Dict[str, Any]] = []
        for client in clients:
            uuid = str(client.get("uuid") or client.get("id") or "").strip()
            email = str(client.get("email") or "").strip()
            if not uuid or not email:
                continue
            out.append({"uuid": uuid, "email": email})
        return out

    async def _get_client_config(
        self, panel_id: int, inbound_id: int, client_uuid: str
    ) -> tuple[Dict[str, Any], Dict[str, Any], list[Dict[str, Any]]]:
        inbounds = await self.list_inbounds(panel_id)
        inbound = next((x for x in inbounds if int(x.get("id") or -1) == inbound_id), None)
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
        }

    async def set_client_total_gb(
        self, panel_id: int, inbound_id: int, client_uuid: str, total_gb: int | None
    ) -> None:
        total_bytes = 0 if total_gb is None else max(0, int(total_gb)) * (1024**3)
        await self._update_client_by_mutation(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            mutator=lambda c: {**c, "totalGB": total_bytes},
        )

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
        inbounds = await self.list_inbounds(panel_id)
        email_norm = client_email.strip().lower()
        target_inbound: Dict[str, Any] | None = None
        target_client: Dict[str, Any] | None = None

        if inbound_id is not None:
            candidate = next((x for x in inbounds if int(x.get("id") or -1) == int(inbound_id)), None)
            if candidate is not None:
                for c in self._extract_inbound_clients(candidate):
                    if str(c.get("email") or "").strip().lower() == email_norm:
                        target_inbound = candidate
                        target_client = c
                        break

        if target_client is None:
            for inbound in inbounds:
                for c in self._extract_inbound_clients(inbound):
                    if str(c.get("email") or "").strip().lower() == email_norm:
                        target_inbound = inbound
                        target_client = c
                        break
                if target_client is not None:
                    break

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

    async def get_client_vless_uri_by_email(
        self, panel_id: int, inbound_id: int | None, client_email: str
    ) -> str:
        panel = await self.db.get_panel(panel_id)
        if panel is None:
            raise ValueError("panel not found.")
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
                    target_inbound = candidate
                    target_client = found

        if target_client is None:
            for inbound in inbounds:
                found = _scan_inbound(inbound)
                if found is not None:
                    target_inbound = inbound
                    target_client = found
                    break

        if target_inbound is None or target_client is None:
            raise ValueError("client not found on inbound.")

        protocol = str(target_inbound.get("protocol") or "").strip().lower()
        if protocol != "vless":
            raise ValueError(f"protocol {protocol or '-'} is not supported for vless link.")

        client_uuid = str(target_client.get("uuid") or target_client.get("id") or "").strip()
        if not client_uuid:
            raise ValueError("client UUID not found.")

        base_host = (urlparse(str(panel.get("base_url") or "")).hostname or "").strip()
        port = int(target_inbound.get("port") or 0)
        if not base_host or port <= 0:
            raise ValueError("valid host/port for config generation was not found.")

        settings_obj = self._parse_json_obj(target_inbound.get("settings"))
        stream_obj = self._parse_json_obj(target_inbound.get("streamSettings"))
        network = str(stream_obj.get("network") or "tcp")
        security = str(stream_obj.get("security") or "none")

        params: Dict[str, str] = {
            "encryption": "none",
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
                    if flow:
                        params["flow"] = flow
                    break

        if network == "ws":
            ws = self._parse_json_obj(stream_obj.get("wsSettings"))
            path = str(ws.get("path") or "/")
            host = ""
            headers = ws.get("headers")
            if isinstance(headers, dict):
                host = str(headers.get("Host") or "").strip()
            if host:
                params["host"] = host
            params["path"] = path
        elif network == "grpc":
            grpc = self._parse_json_obj(stream_obj.get("grpcSettings"))
            service_name = str(grpc.get("serviceName") or "").strip()
            if service_name:
                params["serviceName"] = service_name
        elif network == "tcp":
            tcp = self._parse_json_obj(stream_obj.get("tcpSettings"))
            header = self._parse_json_obj(tcp.get("header"))
            header_type = str(header.get("type") or "").strip()
            if header_type:
                params["headerType"] = header_type

        if security in {"tls", "reality"}:
            tls_obj = self._parse_json_obj(stream_obj.get("tlsSettings"))
            server_name = str(tls_obj.get("serverName") or "").strip()
            if server_name:
                params["sni"] = server_name
            alpn = tls_obj.get("alpn")
            if isinstance(alpn, list) and alpn:
                params["alpn"] = ",".join([str(x) for x in alpn if str(x).strip()])

        if security == "reality":
            reality = self._parse_json_obj(stream_obj.get("realitySettings"))
            pbk = str(reality.get("publicKey") or "").strip()
            sid = str(reality.get("shortId") or "").strip()
            fp = str(reality.get("fingerprint") or "").strip()
            sni = params.get("sni", "")
            if not sni:
                server_names = reality.get("serverNames")
                if isinstance(server_names, list) and server_names:
                    sni = str(server_names[0] or "").strip()
            if pbk:
                params["pbk"] = pbk
            if sid:
                params["sid"] = sid
            if fp:
                params["fp"] = fp
            if sni:
                params["sni"] = sni

        query = urlencode(params, doseq=False, safe=",:/")
        remark = quote(str(target_client.get("email") or client_email))
        return f"vless://{client_uuid}@{base_host}:{port}?{query}#{remark}"

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
