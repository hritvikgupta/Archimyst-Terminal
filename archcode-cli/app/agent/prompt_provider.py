"""Agent prompt provider module."""

from prompts import AGENT_DESCRIPTION, get_agent_instructions


class PromptProvider:
    """Provide prompt payloads for agent construction."""

    @staticmethod
    def description() -> str:
        return AGENT_DESCRIPTION

    @staticmethod
    def instructions(tool_use_count: int = 0) -> str:
        return get_agent_instructions(tool_use_count=tool_use_count)


__all__ = ["PromptProvider"]
