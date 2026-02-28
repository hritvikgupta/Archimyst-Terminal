"""MCP command handlers module."""

from app.commands.command_handler import CommandHandler


class MCPCommands:
    """MCP command facade over CommandHandler."""

    def __init__(self, handler: CommandHandler):
        self.handler = handler

    def route(self, user_input: str):
        return self.handler.handle_mcp(user_input)


__all__ = ["MCPCommands"]
