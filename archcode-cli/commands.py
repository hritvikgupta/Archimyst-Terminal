"""Backward-compatible command handler module.

Primary implementation now lives in app.commands.command_handler.
"""

from app.commands.command_handler import (
    CommandHandler,
    _show_diff_rich,
    console,
    interactive_rewind_selector,
)


__all__ = [
    "console",
    "interactive_rewind_selector",
    "_show_diff_rich",
    "CommandHandler",
]
