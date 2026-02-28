"""Rewind command helpers module."""

from app.commands.command_handler import (
    _show_diff_rich,
    interactive_rewind_selector,
)


class RewindCommands:
    """Static access to rewind selector and diff preview."""

    selector = staticmethod(interactive_rewind_selector)
    show_diff = staticmethod(_show_diff_rich)


__all__ = ["RewindCommands", "interactive_rewind_selector", "_show_diff_rich"]
