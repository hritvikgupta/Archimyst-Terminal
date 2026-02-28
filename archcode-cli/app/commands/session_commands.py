"""Session command handlers module."""

from app.commands.command_handler import CommandHandler


class SessionCommands:
    """Focused session command facade over CommandHandler."""

    def __init__(self, handler: CommandHandler):
        self.handler = handler

    def shortcuts(self):
        return self.handler.show_shortcuts()

    def status(self):
        return self.handler.handle_status()

    def rewind(self):
        return self.handler.interactive_rewind()

    def revert(self, user_input: str):
        return self.handler.handle_revert(user_input)

    def model(self, input_str: str):
        return self.handler.change_model(input_str)


__all__ = ["SessionCommands"]
