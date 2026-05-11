from __future__ import annotations

import base64
import json
import re
import secrets
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


def _unique_tag(hint: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", (hint or "").strip())[:24].strip("-") or "out"
    return f"{base}-{secrets.token_hex(3)}"


def _parse_qs_flat(q: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, vals in parse_qs(q, keep_blank_values=True).items():
        if vals:
            out[k.lower()] = unquote(vals[0])
    return out


def _stream_from_flat(q: dict[str, str], host: str) -> dict[str, Any]:
    net = (q.get("type") or "tcp").lower()
    if net == "http":
        net = "tcp"
    sec = (q.get("security") or "none").lower()
    stream: dict[str, Any] = {"network": net}
    if sec in {"tls", "reality"}:
        stream["security"] = sec
        tls: dict[str, Any] = {
            "serverName": q.get("sni") or q.get("peer") or host,
            "allowInsecure": q.get("allowinsecure") in {"1", "true", "yes"},
        }
        if sec == "reality":
            tls["fingerprint"] = q.get("fp") or "chrome"
            tls["publicKey"] = q.get("pbk") or ""
            tls["shortId"] = q.get("sid") or ""
            tls["spiderX"] = q.get("spx") or "/"
            stream["realitySettings"] = tls
        else:
            if q.get("alpn"):
                tls["alpn"] = [x for x in q.get("alpn", "").split(",") if x]
            stream["tlsSettings"] = tls
    if net == "ws":
        stream["wsSettings"] = {
            "path": q.get("path") or "/",
            "headers": {"Host": q.get("host") or host},
        }
    elif net == "grpc":
        stream["grpcSettings"] = {
            "serviceName": q.get("serviceName") or q.get("servicename") or "",
        }
    return stream


def parse_share_link_to_outbound(uri: str) -> dict[str, Any]:
    raw = (uri or "").strip()
    if not raw:
        raise ValueError("empty link.")
    if raw.lower().startswith("vmess://"):
        return _parse_vmess(raw)
    if raw.lower().startswith("vless://"):
        return _parse_vless(raw)
    if raw.lower().startswith("trojan://"):
        return _parse_trojan(raw)
    if raw.lower().startswith("ss://"):
        return _parse_ss(raw)
    low = raw.lower()
    if low.startswith("hysteria2://") or low.startswith("hy2://"):
        return _parse_hy2(raw)
    raise ValueError("unsupported scheme (use vless, vmess, trojan, ss, hysteria2).")


def _parse_vless(raw: str) -> dict[str, Any]:
    u = urlparse(raw)
    if u.scheme.lower() != "vless" or not u.hostname:
        raise ValueError("invalid vless link.")
    uid = (u.username or "").strip()
    if not uid:
        raise ValueError("vless: missing uuid.")
    port = u.port or 443
    host = u.hostname
    q = _parse_qs_flat(u.query or "")
    flow = (q.get("flow") or "").strip()
    user_obj: dict[str, Any] = {"id": uid, "encryption": "none"}
    if flow:
        user_obj["flow"] = flow
    tag = _unique_tag(unquote(u.fragment) if u.fragment else host)
    outbound: dict[str, Any] = {
        "tag": tag,
        "protocol": "vless",
        "settings": {"vnext": [{"address": host, "port": int(port), "users": [user_obj]}]},
        "streamSettings": _stream_from_flat(q, host),
    }
    return outbound


def _parse_vmess(raw: str) -> dict[str, Any]:
    b64 = raw[len("vmess://") :].strip()
    pad = "=" * ((4 - len(b64) % 4) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(b64 + pad).decode("utf-8", errors="strict"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid vmess payload.") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid vmess json.")
    add = str(data.get("add") or "").strip()
    if not add:
        raise ValueError("vmess: missing address.")
    port = int(data.get("port") or 443)
    uid = str(data.get("id") or "").strip()
    if not uid:
        raise ValueError("vmess: missing id.")
    aid = int(data.get("aid") or 0)
    net = str(data.get("net") or "tcp").lower()
    if net == "http":
        net = "tcp"
    tls = str(data.get("tls") or "").lower() in {"tls", "1", "true"}
    tag = _unique_tag(str(data.get("ps") or add))
    stream: dict[str, Any] = {"network": net}
    if tls:
        stream["security"] = "tls"
        stream["tlsSettings"] = {
            "serverName": str(data.get("sni") or add),
            "allowInsecure": str(data.get("verify_cert") or "1") == "0",
        }
    if net == "ws":
        stream["wsSettings"] = {
            "path": str(data.get("path") or "/"),
            "headers": {"Host": str(data.get("host") or add)},
        }
    return {
        "tag": tag,
        "protocol": "vmess",
        "settings": {
            "vnext": [
                {
                    "address": add,
                    "port": port,
                    "users": [{"id": uid, "alterId": aid, "security": "auto"}],
                }
            ]
        },
        "streamSettings": stream,
    }


def _parse_trojan(raw: str) -> dict[str, Any]:
    u = urlparse(raw)
    if u.scheme.lower() != "trojan" or not u.hostname:
        raise ValueError("invalid trojan link.")
    pwd = unquote(u.username or "")
    if not pwd:
        raise ValueError("trojan: missing password.")
    port = u.port or 443
    host = u.hostname
    q = _parse_qs_flat(u.query or "")
    tag = _unique_tag(unquote(u.fragment) if u.fragment else host)
    stream = _stream_from_flat(q, host)
    return {
        "tag": tag,
        "protocol": "trojan",
        "settings": {
            "servers": [
                {
                    "address": host,
                    "port": int(port),
                    "password": pwd,
                    "level": 0,
                }
            ]
        },
        "streamSettings": stream,
    }


def _parse_ss(raw: str) -> dict[str, Any]:
    u = urlparse(raw)
    if u.scheme.lower() != "ss":
        raise ValueError("invalid ss link.")
    host = u.hostname
    port = u.port
    if not host or not port:
        raise ValueError("ss: missing host/port.")
    method = ""
    password = ""
    if u.password is not None and str(u.password) != "":
        method = unquote(u.username or "")
        password = unquote(u.password or "")
    elif u.username:
        enc = unquote(u.username)
        pad = "=" * ((4 - len(enc) % 4) % 4)
        try:
            inner = base64.urlsafe_b64decode(enc + pad).decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("ss: bad base64.") from exc
        if "@" in inner:
            cred, _, _ = inner.partition("@")
            if ":" not in cred:
                raise ValueError("ss: bad legacy payload.")
            method, password = cred.split(":", 1)
        elif ":" in inner:
            method, password = inner.split(":", 1)
        else:
            raise ValueError("ss: bad base64 payload.")
    if not method or not password:
        raise ValueError("ss: missing method/password.")
    tag = _unique_tag(unquote(u.fragment) if u.fragment else host)
    return {
        "tag": tag,
        "protocol": "shadowsocks",
        "settings": {
            "servers": [
                {
                    "address": host,
                    "port": int(port),
                    "method": method,
                    "password": password,
                }
            ]
        },
    }


def _parse_hy2(raw: str) -> dict[str, Any]:
    u = urlparse(raw)
    if not u.hostname:
        raise ValueError("invalid hysteria2 link.")
    auth = unquote(u.username or "")
    port = u.port or 443
    host = u.hostname
    q = _parse_qs_flat(u.query or "")
    insecure = q.get("insecure") in {"1", "true", "yes"}
    sni = q.get("sni") or host
    tag = _unique_tag(unquote(u.fragment) if u.fragment else host)
    return {
        "tag": tag,
        "protocol": "hysteria2",
        "settings": {
            "servers": [
                {
                    "address": host,
                    "port": int(port),
                    "password": auth,
                }
            ]
        },
        "streamSettings": {
            "network": "tcp",
            "security": "tls",
            "tlsSettings": {"serverName": sni, "allowInsecure": insecure},
        },
    }
