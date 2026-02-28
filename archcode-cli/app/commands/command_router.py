"""Command router compatibility module."""

from app.commands.command_handler import CommandHandler


class CommandRouter(CommandHandler):
    """Backward-compatible alias for command routing entrypoint."""


__all__ = ["CommandRouter", "CommandHandler"]
