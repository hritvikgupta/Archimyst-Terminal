"""Terminal tool service implementation."""

import re
import subprocess
from typing import Optional

from rich.console import Console

from task_context import get_current_task_id


class TerminalToolService:
    """Service for controlled shell command execution."""

    MAX_OUTPUT_CHARS = 10000

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    @staticmethod
    def _is_risky(command: str) -> bool:
        risky_patterns = [
            r"\brm\b",
            r"\bdelete\b",
            r"\bdrop\b",
            r"\btruncate\b",
            r"\bshutdown\b",
            r"\breboot\b",
        ]
        return any(re.search(pattern, command) for pattern in risky_patterns)

    def _truncate_output(self, text: str) -> str:
        return text
        # if len(text) <= self.MAX_OUTPUT_CHARS:
        #     return text
        # return (
        #     f"[...output truncated, showing last {self.MAX_OUTPUT_CHARS} chars...]\n"
        #     + text[-self.MAX_OUTPUT_CHARS :]
        # )

    def run_terminal_command(self, command: str) -> str:
        """Run a shell command on the local machine."""
        if self._is_risky(command):
            if get_current_task_id() != "foreground":
                return (
                    "Error: Risky command refused in background task. "
                    "Cannot prompt for confirmation."
                )
            self.console.print(
                f"[bold red]WARNING: Command '{command}' may be destructive.[/bold red]"
            )
            confirmation = input("Do you want to proceed? (y/n): ")
            if confirmation.lower() != "y":
                return "Command execution cancelled by user."

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return f"Output:\n{self._truncate_output(result.stdout)}"
            return (
                f"Error (Exit Code {result.returncode}):\n"
                f"{self._truncate_output(result.stderr)}"
            )
        except subprocess.TimeoutExpired:
            return "Error: Command timed out."
        except Exception as e:
            return f"Error running command: {str(e)}"


__all__ = ["TerminalToolService"]
