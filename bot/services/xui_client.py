from __future__ import annotations

import json
from asyncio import sleep
from dataclasses import dataclass
from typing import Any, Dict, Tuple
from urllib.parse import quote, urlparse

import aiohttp

from bot.metrics import XUI_ERRORS, XUI_REQUESTS


class XUIError(Exception):
    pass


class XUIAuthError(XUIError):
    pass


class XUIValidationError(XUIError):
    pass


class XUIRateLimitError(XUIError):
    pass


class XUIServerError(XUIError):
    pass


@dataclass(slots=True)
class PanelConnection:
    base_url: str
    web_base_path: str
    login_path: str
    username: str
    password: str
    two_factor: str | None


def parse_login_url(raw_login_url: str) -> tuple[str, str, str]:
    raw = raw_login_url.strip()
    if not raw:
        raise ValueError("login url is empty.")
    if "://" not in raw:
        raw = f"http://{raw}"

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid login url.")

    path = parsed.path or "/login/"
    if not path.endswith("/"):
        path = f"{path}/"
    if not path.lower().endswith("/login/"):
        raise ValueError("login url must end with /login/.")

    web_base_path = path[: -len("/login/")] or ""
    if web_base_path.endswith("/"):
        web_base_path = web_base_path[:-1]
    if web_base_path == "/":
        web_base_path = ""

    return f"{parsed.scheme}://{parsed.netloc}", web_base_path, path


class XUIClient:
    def __init__(self, timeout_seconds: int = 20, max_retries: int = 2) -> None:
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.max_retries = max_retries

    @staticmethod
    def _cookie_header(cookies: Dict[str, str] | None) -> str | None:
        if not cookies:
            return None
        return "; ".join([f"{k}={v}" for k, v in cookies.items()])

    @staticmethod
    def _api_path(web_base_path: str, endpoint: str) -> str:
        base = web_base_path.strip()
        if base and not base.startswith("/"):
            base = f"/{base}"
        base = base.rstrip("/")
        endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{base}/panel/api{endpoint}"

    async def login(self, conn: PanelConnection) -> Dict[str, str]:
        payload = {"username": conn.username, "password": conn.password}
        if conn.two_factor:
            payload["twoFactorCode"] = conn.two_factor
        url = f"{conn.base_url}{conn.login_path}"

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            response = await session.post(url, json=payload)
            text = await response.text()

            if response.status in (400, 415, 422):
                response = await session.post(url, data=payload)
                text = await response.text()

            if response.status == 401:
                XUI_REQUESTS.labels(endpoint="/login/", status="401").inc()
                XUI_ERRORS.labels(type="auth").inc()
                raise XUIAuthError("invalid username/password/twoFactorCode.")
            if response.status in (400, 415, 422):
                XUI_REQUESTS.labels(endpoint="/login/", status=str(response.status)).inc()
                XUI_ERRORS.labels(type="validation").inc()
                raise XUIValidationError("login payload invalid.")
            if response.status == 429:
                XUI_REQUESTS.labels(endpoint="/login/", status="429").inc()
                XUI_ERRORS.labels(type="rate_limit").inc()
                raise XUIRateLimitError("rate limited on login.")
            if response.status >= 500:
                XUI_REQUESTS.labels(endpoint="/login/", status=str(response.status)).inc()
                XUI_ERRORS.labels(type="server").inc()
                raise XUIServerError(f"server error on login ({response.status}).")
            if response.status >= 400:
                XUI_REQUESTS.labels(endpoint="/login/", status=str(response.status)).inc()
                XUI_ERRORS.labels(type="unknown").inc()
                raise XUIError(f"login failed ({response.status}): {text[:300]}")

            body = {}
            try:
                body = json.loads(text) if text else {}
            except json.JSONDecodeError:
                pass
            if isinstance(body, dict) and body.get("success") is False:
                XUI_REQUESTS.labels(endpoint="/login/", status="app_error").inc()
                XUI_ERRORS.labels(type="app").inc()
                raise XUIError(body.get("msg") or "login rejected by 3x-ui.")

            cookies = {name: morsel.value for name, morsel in response.cookies.items()}
            if not cookies:
                XUI_REQUESTS.labels(endpoint="/login/", status="no_cookie").inc()
                XUI_ERRORS.labels(type="no_cookie").inc()
                raise XUIError("no session cookie returned from login.")
            XUI_REQUESTS.labels(endpoint="/login/", status="ok").inc()
            return cookies

    async def request(
        self,
        *,
        conn: PanelConnection,
        method: str,
        endpoint: str,
        cookies: Dict[str, str] | None,
        payload: Dict[str, Any] | None = None,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        url = f"{conn.base_url}{self._api_path(conn.web_base_path, endpoint)}"
        headers: Dict[str, str] = {}
        cookie_header = self._cookie_header(cookies)
        if cookie_header:
            headers["Cookie"] = cookie_header

        for attempt in range(1, self.max_retries + 2):
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                kwargs: Dict[str, Any] = {"headers": headers}
                if payload is not None:
                    kwargs["json"] = payload
                response = await session.request(method=method.upper(), url=url, **kwargs)
                text = await response.text()
                new_cookies = {name: morsel.value for name, morsel in response.cookies.items()}

                if response.status in (401, 403):
                    XUI_REQUESTS.labels(endpoint=endpoint, status="auth").inc()
                    XUI_ERRORS.labels(type="auth").inc()
                    raise XUIAuthError(f"unauthorized on {endpoint}.")
                if response.status in (400, 415, 422):
                    XUI_REQUESTS.labels(endpoint=endpoint, status="validation").inc()
                    XUI_ERRORS.labels(type="validation").inc()
                    raise XUIValidationError(f"validation failed on {endpoint}: {text[:300]}")
                if response.status == 429:
                    if attempt <= self.max_retries:
                        await sleep(0.5 * attempt)
                        continue
                    XUI_REQUESTS.labels(endpoint=endpoint, status="429").inc()
                    XUI_ERRORS.labels(type="rate_limit").inc()
                    raise XUIRateLimitError(f"rate limited on {endpoint}.")
                if response.status >= 500:
                    if attempt <= self.max_retries:
                        await sleep(0.5 * attempt)
                        continue
                    XUI_REQUESTS.labels(endpoint=endpoint, status="5xx").inc()
                    XUI_ERRORS.labels(type="server").inc()
                    raise XUIServerError(f"server error on {endpoint}: {text[:300]}")
                if response.status >= 400:
                    XUI_REQUESTS.labels(endpoint=endpoint, status=str(response.status)).inc()
                    XUI_ERRORS.labels(type="unknown").inc()
                    raise XUIError(f"request failed ({response.status}) on {endpoint}: {text[:300]}")

                try:
                    body = json.loads(text) if text else {}
                except json.JSONDecodeError as exc:
                    XUI_ERRORS.labels(type="invalid_json").inc()
                    raise XUIError(f"invalid json on {endpoint}.") from exc

                if isinstance(body, dict) and body.get("success") is False:
                    XUI_REQUESTS.labels(endpoint=endpoint, status="app_error").inc()
                    XUI_ERRORS.labels(type="app").inc()
                    raise XUIError(body.get("msg") or f"3x-ui rejected {endpoint}.")

                XUI_REQUESTS.labels(endpoint=endpoint, status="ok").inc()
                return body, new_cookies

        raise XUIError("request exhausted retries")

    async def get_client_traffics(
        self, conn: PanelConnection, cookies: Dict[str, str] | None, client_email: str
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        endpoint = f"/inbounds/getClientTraffics/{quote(client_email, safe='')}"
        return await self.request(
            conn=conn,
            method="GET",
            endpoint=endpoint,
            cookies=cookies,
            payload=None,
        )

    async def get_inbounds_list(
        self, conn: PanelConnection, cookies: Dict[str, str] | None
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        return await self.request(
            conn=conn,
            method="GET",
            endpoint="/inbounds/list",
            cookies=cookies,
            payload=None,
        )

    async def get_default_settings(
        self, conn: PanelConnection, cookies: Dict[str, str] | None
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        return await self.request(
            conn=conn,
            method="POST",
            endpoint="/setting/defaultSettings",
            cookies=cookies,
            payload=None,
        )

    async def get_online_clients(
        self, conn: PanelConnection, cookies: Dict[str, str] | None
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        return await self.request(
            conn=conn,
            method="POST",
            endpoint="/inbounds/onlines",
            cookies=cookies,
            payload=None,
        )

    async def get_last_online(
        self, conn: PanelConnection, cookies: Dict[str, str] | None
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        return await self.request(
            conn=conn,
            method="POST",
            endpoint="/inbounds/lastOnline",
            cookies=cookies,
            payload=None,
        )

    async def get_client_traffics_by_id(
        self, conn: PanelConnection, cookies: Dict[str, str] | None, client_uuid: str
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        endpoint = f"/inbounds/getClientTrafficsById/{quote(client_uuid, safe='')}"
        return await self.request(
            conn=conn,
            method="GET",
            endpoint=endpoint,
            cookies=cookies,
            payload=None,
        )

    async def update_client(
        self,
        conn: PanelConnection,
        cookies: Dict[str, str] | None,
        *,
        client_uuid: str,
        payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        endpoint = f"/inbounds/updateClient/{quote(client_uuid, safe='')}"
        return await self.request(
            conn=conn,
            method="POST",
            endpoint=endpoint,
            cookies=cookies,
            payload=payload,
        )

    async def add_client(
        self,
        conn: PanelConnection,
        cookies: Dict[str, str] | None,
        *,
        payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        return await self.request(
            conn=conn,
            method="POST",
            endpoint="/inbounds/addClient",
            cookies=cookies,
            payload=payload,
        )

    async def delete_client(
        self,
        conn: PanelConnection,
        cookies: Dict[str, str] | None,
        *,
        inbound_id: int,
        client_uuid: str,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        endpoint = f"/inbounds/{inbound_id}/delClient/{quote(client_uuid, safe='')}"
        return await self.request(
            conn=conn,
            method="POST",
            endpoint=endpoint,
            cookies=cookies,
            payload=None,
        )

    async def clear_client_ips(
        self, conn: PanelConnection, cookies: Dict[str, str] | None, email: str
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        endpoint = f"/inbounds/clearClientIps/{quote(email, safe='')}"
        return await self.request(
            conn=conn,
            method="POST",
            endpoint=endpoint,
            cookies=cookies,
            payload=None,
        )

    async def reset_client_traffic(
        self,
        conn: PanelConnection,
        cookies: Dict[str, str] | None,
        *,
        inbound_id: int,
        email: str,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        endpoint = f"/inbounds/{inbound_id}/resetClientTraffic/{quote(email, safe='')}"
        return await self.request(
            conn=conn,
            method="POST",
            endpoint=endpoint,
            cookies=cookies,
            payload=None,
        )

    async def client_ips(
        self, conn: PanelConnection, cookies: Dict[str, str] | None, email: str
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        endpoint = f"/inbounds/clientIps/{quote(email, safe='')}"
        return await self.request(
            conn=conn,
            method="POST",
            endpoint=endpoint,
            cookies=cookies,
            payload=None,
        )

    async def get_new_uuid(
        self, conn: PanelConnection, cookies: Dict[str, str] | None
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        return await self.request(
            conn=conn,
            method="GET",
            endpoint="/server/getNewUUID",
            cookies=cookies,
            payload=None,
        )
