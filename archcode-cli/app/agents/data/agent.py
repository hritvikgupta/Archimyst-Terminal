"""Data Analysis Agent using Agno with full toolset for data analysis."""
import os
import logging
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.session.summary import SessionSummaryManager
from config import config
from prompts_data import get_data_agent_instructions
from tools.data_tools import get_all_data_tools


def create_data_agent(
    session_id: str,
    extra_tools: list = None,
) -> Agent:
    """
    Create a Data Analysis Agent configured for the ArchCode CLI.

    Args:
        session_id: Unique session ID for chat history continuity.
        extra_tools: Additional tools to add (e.g. from MCP).
    """
    # Suppress Agno's "PythonTools can run arbitrary code" warning —
    # user has already opted into data mode which includes code execution.
    # The warn() function is lru_cached, so pre-call it with logging suppressed.
    _agno_logger = logging.getLogger("agno")
    _prev_level = _agno_logger.level
    _agno_logger.setLevel(logging.ERROR)
    try:
        from agno.tools.python import warn as _python_warn
        _python_warn()
    except Exception:
        pass
    _agno_logger.setLevel(_prev_level)

    # Get all data analysis tools
    tools = get_all_data_tools(config)
    if extra_tools:
        tools.extend(extra_tools)

    # Persistent session storage - same location as coding agent
    db_path = os.path.join(os.getcwd(), ".archcode", "data_agent_sessions.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    agent = Agent(
        name="DataMyst",
        description=get_data_agent_instructions(),
        model=config.get_agno_model(),
        tools=tools,
        # Storage for persistent history & metrics
        db=SqliteDb(db_file=db_path),
        # Session tracking
        session_id=session_id,
        # Rolling summaries: condense conversation to save tokens
        enable_session_summaries=True,
        add_session_summary_to_context=True,
        session_summary_manager=SessionSummaryManager(
            model=config.get_agno_model(model_id="openai/gpt-oss-120b")
        ),
        # History management
        add_history_to_context=True,
        num_history_runs=2,
        store_tool_messages=True,
        # Anti-loop
        tool_call_limit=15,
        max_tool_calls_from_history=2,
        # Output formatting
        markdown=True,
    )

    return agent
