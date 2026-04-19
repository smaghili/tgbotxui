from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.middlewares.menu_state_reset import MenuStateResetMiddleware


class DummyState:
    def __init__(self) -> None:
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True


@pytest.mark.asyncio
async def test_menu_button_clears_active_state() -> None:
    middleware = MenuStateResetMiddleware()
    state = DummyState()
    event = SimpleNamespace(text="لیست کاربران")

    async def handler(event, data):
        return "ok"

    result = await middleware(handler, event, {"state": state})

    assert result == "ok"
    assert state.cleared is True


@pytest.mark.asyncio
async def test_regular_text_does_not_clear_state() -> None:
    middleware = MenuStateResetMiddleware()
    state = DummyState()
    event = SimpleNamespace(text="vless://example")

    async def handler(event, data):
        return "ok"

    await middleware(handler, event, {"state": state})

    assert state.cleared is False


@pytest.mark.asyncio
async def test_cancel_operation_button_clears_active_state() -> None:
    middleware = MenuStateResetMiddleware()
    state = DummyState()
    event = SimpleNamespace(text="لغو عملیات")

    async def handler(event, data):
        return "ok"

    await middleware(handler, event, {"state": state})

    assert state.cleared is True
