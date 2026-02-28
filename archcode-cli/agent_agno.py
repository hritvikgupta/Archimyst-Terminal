"""Backward-compatible agent factory module.

Primary implementation now lives in app.agent.agent_factory.
"""

from app.agent.agent_factory import _get_core_tools, create_agent


__all__ = ["_get_core_tools", "create_agent"]
