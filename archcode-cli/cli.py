"""Backward-compatible CLI entry module.

Primary implementation now lives in app.runtime.cli_runtime.
"""

from app.runtime.cli_runtime import (
    ArchCodeCliRuntime,
    CliTheme,
    MockAgentForCommands,
    PlanActionSelector,
    RuntimeImports,
    SYSTEM_PROMPT,
    VersionManager,
    _set_terminal_background,
    main,
)


__all__ = [
    "CliTheme",
    "PlanActionSelector",
    "VersionManager",
    "RuntimeImports",
    "MockAgentForCommands",
    "ArchCodeCliRuntime",
    "SYSTEM_PROMPT",
    "_set_terminal_background",
    "main",
]


if __name__ == "__main__":
    _set_terminal_background()
    main()
