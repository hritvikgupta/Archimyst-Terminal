"""Authentication command handlers module."""

from app.commands.command_handler import CommandHandler


class AuthCommands:
    """Auth command facade over CommandHandler."""

    def __init__(self, handler: CommandHandler):
        self.handler = handler

    def login(self):
        return self.handler.handle_login()

    def logout(self):
        return self.handler.handle_logout()


__all__ = ["AuthCommands"]
