"""Runtime trading mode state.

Initialized from PAPER_TRADING_MODE in settings at first access.
Can be toggled via /api/settings/mode without restarting the server.
"""

_paper_mode: bool | None = None


def get_paper_mode() -> bool:
    global _paper_mode
    if _paper_mode is None:
        from sol.config import get_settings
        _paper_mode = get_settings().PAPER_TRADING_MODE
    return _paper_mode


def set_paper_mode(enabled: bool) -> None:
    global _paper_mode
    _paper_mode = enabled
