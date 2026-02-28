"""Prompt session builder module.

This module is intentionally additive and does not alter existing runtime flow.
"""

import os

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from app.runtime.cli_runtime import CliTheme
from file_completer import (
    ArchimystCompleter,
    AtFileCompleter,
    SlashCommandCompleter,
    get_at_file_key_bindings,
)


class PromptSessionBuilder:
    """Build prompt_toolkit session instances for the CLI runtime."""

    @staticmethod
    def build(project_root: str | None = None) -> PromptSession:
        root = project_root or os.getcwd()
        slash_completer = SlashCommandCompleter()
        at_file_completer = AtFileCompleter(project_root=root)
        merged_completer = ArchimystCompleter(slash_completer, at_file_completer)

        return PromptSession(
            history=FileHistory(".archcode_history"),
            style=CliTheme.PROMPT_STYLE,
            completer=merged_completer,
            complete_while_typing=True,
            key_bindings=get_at_file_key_bindings(),
        )


__all__ = ["PromptSessionBuilder"]
