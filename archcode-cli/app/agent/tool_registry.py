"""Agent tool registry module."""

from typing import Callable, List

from app.agent.agent_factory import _get_core_tools


class ToolRegistry:
    """Registry for assembling agent tool sets."""

    @staticmethod
    def core_tools() -> List[Callable]:
        return list(_get_core_tools())

    @staticmethod
    def merged_tools(extra_tools: List[Callable] | None = None) -> List[Callable]:
        tools = ToolRegistry.core_tools()
        if extra_tools:
            tools.extend(extra_tools)
        return tools


__all__ = ["ToolRegistry"]
