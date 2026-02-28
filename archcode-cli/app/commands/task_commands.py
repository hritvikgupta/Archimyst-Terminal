"""Task command handlers module."""

from app.commands.command_handler import CommandHandler


class TaskCommands:
    """Task command facade over CommandHandler."""

    def __init__(self, handler: CommandHandler):
        self.handler = handler

    def route(self, user_input: str, history: list):
        return self.handler._handle_task_commands(user_input, history)

    def list(self):
        return self.handler._task_list()


__all__ = ["TaskCommands"]
