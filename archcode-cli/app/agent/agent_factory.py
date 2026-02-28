"""
Agno-based Agent for ArchCode CLI.

Replaces the LangGraph agent_graph.py with a simpler Agno Agent
that handles:
- Tool loop (automatic tool call → result cycling)
- Context compression (prevents token overflow)
- Session management & chat history
- Token usage tracking via RunOutput.metrics
"""

import os
import logging
import functools
from typing import List, Callable, Optional

from agno.agent import Agent
from agno.models.openrouter import OpenRouter
# from sumy.parsers.plaintext import PlaintextParser
# from sumy.nlp.tokenizers import Tokenizer
# from sumy.summarizers.text_rank import TextRankSummarizer
from agno.run import RunContext
# import nltk
# nltk.download('punkt')
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.session import SessionSummaryManager
from agno.skills import Skills

from config import config
from prompts import AGENT_DESCRIPTION, get_agent_instructions

# Suppress interactive log spam for a cleaner UX
from agno.utils.log import configure_agno_logging
import logging
logging.disable(logging.INFO)  # Add this as the VERY FIRST line after imports
# Suppress ALL agno internal logs (INFO, WARNING, etc.)
custom_logger = logging.getLogger("agno")
custom_logger.setLevel(logging.CRITICAL)
custom_logger.propagate = False
configure_agno_logging(custom_default_logger=custom_logger)

# Also suppress httpx/openai logs
for name in ["httpx", "openai", "httpcore"]:
    logging.getLogger(name).setLevel(logging.CRITICAL)

# Tool imports (all are plain functions after migration)
from tools.filesystem import (
    write_to_file_tool, delete_file,
    edit_file, whole_file_update
)
from tools.terminal import run_terminal_command
from tools.web import search_web
from RAG.tools import search_codebase
from tools.github import (
    github_repo_info, github_list_issues, github_view_issue,
    github_list_prs, github_view_pr, github_list_branches,
    github_list_commits, github_list_tags,
    github_create_issue, github_create_pr, github_merge_pr,
    github_close_issue, github_create_comment, github_create_branch,
    github_push_commits, execute_github_command
)
from tools.guidelines import (
    get_terminal_reference, get_github_reference, get_skill_usage_guidelines,
    get_coding_standards, get_execution_principles, get_mcp_guidelines,
    get_active_skills_overview,
)


def _get_core_tools() -> List[Callable]:
    """Return the base set of tools available to the agent."""
    return [
        # Filesystem
        # Read/explore tools intentionally disabled to force directed terminal-based retrieval
        # list_dir,
        # read_file,
        # read_file_chunked,
        # list_symbols,
        # view_symbol,
        # view_context,
        write_to_file_tool, delete_file,
        edit_file, whole_file_update,
        # Terminal
        run_terminal_command,
        # Web search
        search_web,
        # Code symbol index (Professional RAG)
        search_codebase,
        # GitHub
        github_repo_info, github_list_issues, github_view_issue,
        github_list_prs, github_view_pr, github_list_branches,
        github_list_commits, github_list_tags,
        github_create_issue, github_create_pr, github_merge_pr,
        github_close_issue, github_create_comment, github_create_branch,
        github_push_commits, execute_github_command,
        # Guidelines & Manuals
        get_terminal_reference, get_github_reference, get_skill_usage_guidelines,
        get_coding_standards, get_execution_principles, get_mcp_guidelines,
        get_active_skills_overview,
    ]

# def my_custom_compress(last_4_results: list) -> str:
#     """Summarize last 4 tool results extractively (no LLM)."""
#     print(f"Starting compression of {len(last_4_results)} tool results.")
#     # Combine all outputs into one text block
#     combined_text = ""
#     for res in last_4_results:
#         output = res["result"]
#         if isinstance(output, dict):
#             combined_text += " ".join([str(v) for v in output.values() if v]) + " "  # Flatten dicts to strings
#         elif isinstance(output, list):
#             combined_text += " ".join(map(str, output)) + " "  # Flatten lists
#         else:
#             combined_text += str(output) + " "  # Append as is
    
#     if not combined_text.strip():
#         print(f"Compressed result: No summarizable content.")
#         return "No summarizable content."
    
#     # Parse and summarize
#     parser = PlaintextParser.from_string(combined_text, Tokenizer("english"))
#     summarizer = TextRankSummarizer()
#     summary_sentences = summarizer(parser.document, 2)  # Summarize to 2 key sentences (adjust as needed)
    
#     # Join into a clean summary
#     summary = " ".join([str(sent) for sent in summary_sentences])
#     print(f"Compressed result: Extractive Summary: {summary[:1000]}")
#     return f"Extractive Summary: {summary[:1000]}"

# def compress_every_5th(
#     run_context: RunContext,
#     function_name: str,
#     function_call: callable,
#     arguments: dict,
# ):
#     """Tool hook: compress last 4 tool results on every 5th call."""
#     if not run_context.session_state:
#         run_context.session_state = {}

#     count = run_context.session_state.get("tool_call_count", 0) + 1
#     results = run_context.session_state.get("tool_results", [])

#     # Execute the current tool call
#     result = function_call(**arguments)

#     # Store the result
#     results.append({"tool": function_name, "result": result})

#     # On every 5th call, return compressed summary instead of raw result
#     if count % 5 == 0:
#         last_4 = results[-5:-1]
#         compressed = my_custom_compress(last_4)
#         # Return compressed context + current result
#         result = f"{compressed}\n\nLatest result:\n{result}"

#     run_context.session_state["tool_call_count"] = count
#     run_context.session_state["tool_results"] = results

#     return result

compression_manager = CompressionManager(
    model=OpenRouter(
        id="amazon/nova-lite-v1",
        api_key=config.openrouter_api_key,
    ),
    compress_tool_results_limit=3,
)

def _get_dynamic_instructions(agent: Agent) -> str:
    """Dynamic instruction provider that counts tools in history."""
    count = 0
    if agent.memory and agent.memory.chat_history:
        # Count tool messages in the current session
        count = sum(1 for m in agent.memory.chat_history if m.role == "tool")
    return get_agent_instructions(tool_use_count=count)

def create_agent(
    session_id: str,
    extra_tools: Optional[List[Callable]] = None,
    skills: Optional[Skills] = None,
) -> Agent:
    """
    Create an Agno Agent configured for the ArchCode CLI.

    Args:
        session_id: Unique session ID for chat history continuity.
        extra_tools: Additional tools (e.g. skill tools, MCP tools) to add.
    """
    tools = _get_core_tools()
    if extra_tools:
        tools.extend(extra_tools)

    # Persistent session storage
    db_path = os.path.join(os.getcwd(), ".archcode", "agno_sessions.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    agent = Agent(
        name="Archimyst",
        description=AGENT_DESCRIPTION,
        instructions=_get_dynamic_instructions,
        skills=skills,
        model=OpenRouter(
            id=config.model,
            api_key=config.openrouter_api_key,
            max_tokens=16384,
        ),
        tools=tools,
        # Storage for persistent history & metrics
        db=SqliteDb(db_file=db_path),
        # Session tracking
        session_id=session_id,
        # Rolling summaries: condense conversation to save tokens
        enable_session_summaries=True,
        add_session_summary_to_context=True,
        session_summary_manager=SessionSummaryManager(
            model=OpenRouter(
                id="openai/gpt-oss-120b",
                api_key=config.openrouter_api_key,
            )
        ),
        # History management
        add_history_to_context=True,
        num_history_runs=2,          # reduced from 3 — less history = less context bloat
        store_tool_messages=True,    # agent can see its own previous reads → stops re-reading
        # Anti-loop
        tool_call_limit=15,          # reduced from 20 — forces more efficient tool use
        max_tool_calls_from_history=2,
        # Context compression: custom hook-based, no LLM
        # compress_tool_results=True,
        # tool_hooks=[compress_every_5th],
        compression_manager=compression_manager,
        session_state={"tool_call_count": 0, "tool_results": []},
        # Output
        markdown=True,
    )

    return agent


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph agent — imported here so both implementations are accessible from
# a single import point (app.agent.agent_factory)
# ─────────────────────────────────────────────────────────────────────────────
from app.agents.agent_graph import (  # noqa: E402  (after module-level code intentionally)
    create_langgraph_agent,
    LangGraphAgent,
    RunEvent,
)

__all__ = [
    "create_agent",
    "create_langgraph_agent",
    "LangGraphAgent",
    "RunEvent",
    "_get_core_tools",
]
