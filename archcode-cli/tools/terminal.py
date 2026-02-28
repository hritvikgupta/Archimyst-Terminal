"""Terminal tool wrapper with LangChain @tool decorator."""

from langchain_core.tools import tool

from tools.services.terminal_service import TerminalToolService

_terminal_service = TerminalToolService()


@tool
def run_terminal_command(command: str) -> str:
    """Run a shell command on the local machine. Each call starts a fresh shell — chain commands with && to preserve directory context."""
    return _terminal_service.run_terminal_command(command)


__all__ = ["run_terminal_command", "TerminalToolService"]
