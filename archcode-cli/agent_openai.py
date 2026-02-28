"""Backward-compatible agent factory shim (OpenAI Agents SDK variant).

Primary implementation: app.agent.agent_openai_factory

To switch the CLI from Agno → OpenAI Agents SDK, change one line in
app/runtime/cli_runtime.py:

    # from agent_agno import create_agent        ← current (Agno)
    from agent_openai import create_agent        # ← OpenAI Agents SDK

Everything else (session_id, extra_tools, skills params) stays identical.
The returned ArchCodeOpenAIAgent exposes .run() / .arun() / .run_streamed()
plus .session_id and .name to match what the CLI runtime expects.
"""

from app.agent.agent_openai_factory import (
    _get_core_tools_public as _get_core_tools,
    create_agent,
    ArchCodeOpenAIAgent,
    ArchCodeContext,
    ArchCodeSessionStore,
    SessionSummaryManager,
    ToolResultCompressor,
    ArchCodeAgentHooks,
)


__all__ = [
    "_get_core_tools",
    "create_agent",
    "ArchCodeOpenAIAgent",
    "ArchCodeContext",
    "ArchCodeSessionStore",
    "SessionSummaryManager",
    "ToolResultCompressor",
    "ArchCodeAgentHooks",
]
