import json
import unittest
from urllib.parse import parse_qs, urlparse

from bot.config import (
    _parse_moaf_traffic_gb_values,
    _parse_proxy_list,
    _parse_sub_url_base_overrides,
    _parse_sub_url_strip_port_rules,
)
from bot.services.admin_provisioning_service import AdminProvisioningService
from bot.services.panel_service import PanelService


class ConfigAndVlessTests(unittest.TestCase):
    def test_parse_proxy_list_supports_commas_and_lines(self) -> None:
        raw = "http://a:1,\nhttp://b:2\r\nhttp://c:3"
        self.assertEqual(
            _parse_proxy_list(raw),
            ("http://a:1", "http://b:2", "http://c:3"),
        )

    def test_parse_sub_url_strip_port_rules(self) -> None:
        self.assertEqual(
            _parse_sub_url_strip_port_rules(
                "1:sub.goldoonam.shop,\n2:sub.goldoonam.shop:2569,\n3:sub.goldoonam.shop:2569/subnist/"
            ),
            {
                "1": "http://sub.goldoonam.shop/sub",
                "2": "http://sub.goldoonam.shop:2569/sub",
                "3": "http://sub.goldoonam.shop:2569/subnist",
            },
        )

    def test_parse_sub_url_base_overrides(self) -> None:
        self.assertEqual(
            _parse_sub_url_base_overrides("1=http://sub.goldoonam.shop/sub,\n3xui|https://cdn.example.com/sub"),
            {"1": "http://sub.goldoonam.shop/sub", "3xui": "https://cdn.example.com/sub"},
        )

    def test_parse_moaf_traffic_gb_values(self) -> None:
        self.assertEqual(
            _parse_moaf_traffic_gb_values("5, 10\n0\nbad"),
            {5 * 1024 ** 3, 10 * 1024 ** 3},
        )

    def test_extract_uuid_from_vless_uri(self) -> None:
        uri = "vless://0b8ca9c6-9f47-42d5-971f-af595efd842b@example.com:443?encryption=none#test"
        self.assertEqual(
            AdminProvisioningService.extract_uuid_from_vless_uri(uri),
            "0b8ca9c6-9f47-42d5-971f-af595efd842b",
        )

    def test_extract_uuid_rejects_invalid_scheme(self) -> None:
        with self.assertRaises(ValueError):
            AdminProvisioningService.extract_uuid_from_vless_uri("vmess://abc")

    def test_external_proxy_vless_uri_uses_proxy_dest_and_ws_host(self) -> None:
        uuid = "7af489fc-b6a4-4c06-b636-478d574e8f9e"
        params = {
            "type": "ws",
            "encryption": "none",
            "path": "/",
            "host": "xzcksjdlfkljxccjvhsjflksckjvjkxhvjkshdfkjlcvlzjkvhjzkfhllfj.goldoonam.shop",
            "security": "none",
        }
        uri = PanelService._build_vless_uri(
            client_uuid=uuid,
            host="snapp.ir",
            port=2095,
            params=params,
            remark=PanelService._gen_link_remark({}, {"email": "Farajitest"}, "Farajitest", "Friend"),
        )

        parsed = urlparse(uri)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "vless")
        self.assertEqual(parsed.username, uuid)
        self.assertEqual(parsed.hostname, "snapp.ir")
        self.assertEqual(parsed.port, 2095)
        self.assertEqual(query["type"], ["ws"])
        self.assertEqual(query["path"], ["/"])
        self.assertEqual(query["host"], [params["host"]])
        self.assertEqual(query["security"], ["none"])
        self.assertEqual(parsed.fragment, "Friend-Farajitest")


class PanelServiceVlessTests(unittest.IsolatedAsyncioTestCase):
    async def test_vless_generation_uses_external_proxy_tls_and_ws_settings(self) -> None:
        class FakeDB:
            async def get_panel(self, panel_id: int) -> dict[str, str]:
                return {"base_url": "http://130.185.72.150:2052", "web_base_path": ""}

        uuid = "7af489fc-b6a4-4c06-b636-478d574e8f9e"
        ws_host = "xzcksjdlfkljxccjvhsjflksckjvjkxhvjkshdfkjlcvlzjkvhjzkfhllfj.goldoonam.shop"
        service = PanelService(FakeDB(), None, None)  # type: ignore[arg-type]

        async def list_inbounds(panel_id: int) -> list[dict[str, object]]:
            return [
                {
                    "id": 1,
                    "protocol": "vless",
                    "port": 443,
                    "settings": json.dumps(
                        {
                            "encryption": "none",
                            "clients": [
                                {
                                    "id": uuid,
                                    "email": "Farajitest",
                                    "flow": "xtls-rprx-vision",
                                }
                            ],
                        }
                    ),
                    "streamSettings": json.dumps(
                        {
                            "network": "ws",
                            "security": "tls",
                            "wsSettings": {"path": "/", "headers": {"Host": ws_host}},
                            "tlsSettings": {
                                "serverName": "example.com",
                                "alpn": ["h2", "http/1.1"],
                                "settings": {"fingerprint": "chrome"},
                            },
                            "externalProxy": [
                                {
                                    "dest": "snapp.ir",
                                    "port": 2095,
                                    "forceTls": "same",
                                    "remark": "Friend",
                                }
                            ],
                        }
                    ),
                }
            ]

        service.list_inbounds = list_inbounds  # type: ignore[method-assign]
        uri = await service.get_client_vless_uri_by_email(1, 1, "Farajitest")

        parsed = urlparse(uri)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.hostname, "snapp.ir")
        self.assertEqual(parsed.port, 2095)
        self.assertEqual(query["type"], ["ws"])
        self.assertEqual(query["host"], [ws_host])
        self.assertEqual(query["path"], ["/"])
        self.assertEqual(query["security"], ["tls"])
        self.assertEqual(query["sni"], ["example.com"])
        self.assertEqual(query["alpn"], ["h2,http/1.1"])
        self.assertEqual(query["fp"], ["chrome"])
        self.assertEqual(parsed.fragment, "Friend-Farajitest")

    def test_subscription_url_can_strip_port_for_configured_panel_host(self) -> None:
        service = PanelService(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            sub_url_strip_port_rules={"1": "http://sub.goldoonam.shop/sub"},
        )
        url = service._normalize_subscription_url(
            {"id": 1, "name": "3xui"},
            "http://sub.goldoonam.shop:2096/sub/Y5GcTKTHSJua2rBr",
        )
        self.assertEqual(url, "http://sub.goldoonam.shop/sub/Y5GcTKTHSJua2rBr")

    def test_subscription_url_keeps_port_for_unconfigured_panel_host(self) -> None:
        service = PanelService(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            sub_url_strip_port_rules={"2": "http://sub.goldoonam.shop/sub"},
        )
        url = service._normalize_subscription_url(
            {"id": 1, "name": "3xui"},
            "http://sub.goldoonam.shop:2096/sub/Y5GcTKTHSJua2rBr",
        )
        self.assertEqual(url, "http://sub.goldoonam.shop:2096/sub/Y5GcTKTHSJua2rBr")

    def test_subscription_base_override_uses_configured_panel_base(self) -> None:
        service = PanelService(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            sub_url_strip_port_rules={"1": "http://sub.goldoonam.shop:2569/subnist"},
        )
        self.assertEqual(
            service._subscription_base_override({"id": 1, "name": "3xui"}),
            "http://sub.goldoonam.shop:2569/subnist",
        )

    def test_subscription_is_disabled_without_panel_env_rule(self) -> None:
        service = PanelService(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            sub_url_strip_port_rules={"1": "http://sub.goldoonam.shop/sub"},
            sub_url_base_overrides={"1": "http://sub.goldoonam.shop/sub"},
        )

        self.assertTrue(service.is_subscription_enabled_for_panel({"id": 1, "name": "panel-one"}))
        self.assertFalse(service.is_subscription_enabled_for_panel({"id": 2, "name": "panel-two"}))

    def test_owner_id_from_comment_supports_moaf_marker(self) -> None:
        self.assertEqual(PanelService._owner_id_from_comment("55:Moaf"), 55)


if __name__ == "__main__":
    unittest.main()
