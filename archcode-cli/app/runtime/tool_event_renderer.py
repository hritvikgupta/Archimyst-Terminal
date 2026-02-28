"""Tool event rendering helpers.

Isolates console rendering logic for tool execution traces.
"""

from rich.console import Console


class ToolEventRenderer:
    """Render tool lifecycle events in the CLI."""

    def __init__(self, console: Console):
        self.console = console

    def render_tool_line(self, tool_name: str, description: str) -> None:
        self.console.print(f"  L [dim][{tool_name}] {description}[/dim]")

    def render_tool_done(self, tool_uses: int, token_text: str, duration_s: int) -> None:
        self.console.print(
            f"  L [#ff8888]Done[/#ff8888] ({tool_uses} tool uses · {token_text} · {duration_s}s)"
        )


__all__ = ["ToolEventRenderer"]
