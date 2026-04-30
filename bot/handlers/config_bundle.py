from __future__ import annotations

from html import escape
from io import BytesIO
from typing import Any

import qrcode
from aiogram.types import BufferedInputFile, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.utils import format_gb, to_local_date


async def send_config_bundle_card(
    message: Message,
    *,
    config_name: str,
    total_label: str,
    expiry_label: str,
    vless_uri: str,
    sub_url: str,
    lang: str | None,
    filename: str = "config_qr.png",
) -> None:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(vless_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0B5ED7", back_color="#F7F7E8")
    buf = BytesIO()
    img.save(buf, format="PNG")
    file = BufferedInputFile(buf.getvalue(), filename=filename)
    caption_key = "config_full_caption" if sub_url.strip() else "config_without_sub_caption"
    caption = t(
        caption_key,
        lang,
        config_name=escape(config_name),
        total=escape(total_label),
        expiry=escape(expiry_label),
        vless_uri=escape(vless_uri),
        sub_url=escape(sub_url),
    )
    await message.answer_photo(file, caption=caption, parse_mode="HTML")


def existing_bundle_labels(
    *,
    settings: Settings,
    total_bytes: int,
    expiry: int | None,
    lang: str | None,
) -> tuple[str, str]:
    total_label = t("admin_unlimited_reset_value", lang) if total_bytes <= 0 else format_gb(total_bytes, lang or "fa")
    expiry_label = "-"
    if expiry:
        expiry_label = to_local_date(expiry, settings.timezone, lang or "fa")
    return total_label, expiry_label


async def fetch_config_links_for_email(
    services: ServiceContainer,
    *,
    panel_id: int,
    inbound_id: int | None,
    client_email: str,
) -> tuple[str, str]:
    vless_uri = await services.panel_service.get_client_vless_uri_by_email(
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_email=client_email,
    )
    sub_url = await services.panel_service.get_client_subscription_url_by_email(
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_email=client_email,
    )
    return vless_uri, sub_url


async def send_existing_config_bundle_for_email(
    message: Message,
    *,
    services: ServiceContainer,
    settings: Settings,
    panel_id: int,
    inbound_id: int | None,
    client_email: str,
    config_name: str,
    total_bytes: int,
    expiry: int | None,
    lang: str | None,
    filename: str = "config_qr.png",
) -> tuple[str, str]:
    vless_uri, sub_url = await fetch_config_links_for_email(
        services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_email=client_email,
    )
    total_label, expiry_label = existing_bundle_labels(
        settings=settings,
        total_bytes=total_bytes,
        expiry=expiry,
        lang=lang,
    )
    await send_config_bundle_card(
        message,
        config_name=config_name,
        total_label=total_label,
        expiry_label=expiry_label,
        vless_uri=vless_uri,
        sub_url=sub_url,
        lang=lang,
        filename=filename,
    )
    return vless_uri, sub_url


async def send_rotation_preview_bundle_for_email(
    message: Message,
    *,
    services: ServiceContainer,
    settings: Settings,
    panel_id: int,
    inbound_id: int | None,
    client_email: str,
    config_name: str,
    total_bytes: int,
    expiry: int | None,
    lang: str | None,
    filename: str = "config_qr.png",
) -> dict[str, Any]:
    prepared = await services.panel_service.prepare_client_rotation_by_email(
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_email=client_email,
    )
    total_label, expiry_label = existing_bundle_labels(
        settings=settings,
        total_bytes=total_bytes,
        expiry=expiry,
        lang=lang,
    )
    await send_config_bundle_card(
        message,
        config_name=config_name,
        total_label=total_label,
        expiry_label=expiry_label,
        vless_uri=str(prepared["vless_uri"]),
        sub_url=str(prepared["sub_url"]),
        lang=lang,
        filename=filename,
    )
    return prepared
