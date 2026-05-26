from __future__ import annotations


class PanelAccessError(Exception):
    pass


class PanelAccessInvalidCallbackError(PanelAccessError):
    pass


class PanelAccessDeniedError(PanelAccessError):
    pass


class PanelAccessPanelNotFoundError(PanelAccessError):
    pass


class PanelAccessDelegatedAdminNotFoundError(PanelAccessError):
    pass


class PanelAccessInboundNotFoundError(PanelAccessError):
    pass


class PanelAccessStateMismatchError(PanelAccessError):
    pass
