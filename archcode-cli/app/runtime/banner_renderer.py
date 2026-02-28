"""Banner renderer module.

Keeps banner rendering concerns isolated for future decomposition.
"""

import os

from rich.console import Console

from config import config
from logo import get_banner_info, get_logo


class BannerRenderer:
    """Render startup banner and context information."""

    def __init__(self, console: Console):
        self.console = console

    def render(self) -> None:
        self.console.clear()
        self.console.print(get_logo())
        self.console.print(
            get_banner_info(
                config.version,
                config.model,
                config.mode,
                os.getcwd(),
                config.user_email,
            )
        )


__all__ = ["BannerRenderer"]
