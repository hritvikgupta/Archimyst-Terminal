"""
LangGraph-based agent for ArchCode CLI.

Revives the LangGraph implementation (from legacy-archcode-terminal-backup/)
with the current prompts and full tool set.  Exposes a LangGraphAgent adapter
whose .run() interface is compatible with cli_runtime.py — no changes needed
there other than swapping the import.

Architecture
------------
  user_input
      │
  supervisor node  ──(tool calls?)──▶  tool_node
      │  ◀────────────────────────────────────
      │
  (no more tool calls)
      │
  final AIMessage → run_content + run_completed events
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode

from app.agents.graph import build_graph
from app.agents.state import AgentState
from config import config
from prompts import get_agent_instructions
from app.runtime.plan_file import get_plan_context

# ─────────────────────────────────────────────────────────────────────────────
# Tool imports — same set as app.agent.agent_factory._get_core_tools()
# ─────────────────────────────────────────────────────────────────────────────
from tools.filesystem import (
    delete_file,
    edit_file,
    whole_file_update,
    write_to_file_tool,
)
from tools.github import (
    execute_github_command,
    github_close_issue,
    github_create_branch,
    github_create_comment,
    github_create_issue,
    github_create_pr,
    github_list_branches,
    github_list_commits,
    github_list_issues,
    github_list_prs,
    github_list_tags,
    github_merge_pr,
    github_push_commits,
    github_repo_info,
    github_view_issue,
    github_view_pr,
)
from tools.guidelines import (
    get_active_skills_overview,
    get_coding_standards,
    get_execution_principles,
    get_github_reference,
    get_mcp_guidelines,
    get_skill_usage_guidelines,
    get_terminal_reference,
)
from tools.terminal import run_terminal_command
from tools.web import search_web
from RAG.tools import search_codebase
from tools.axon_tools import search_codebase_graph, axon_context, axon_impact


# ─────────────────────────────────────────────────────────────────────────────
# RunEvent enum — mirrors agno.agent.RunEvent so cli_runtime.py needs no edits
# ─────────────────────────────────────────────────────────────────────────────

class RunEvent(str, Enum):
    tool_call_started = "tool_call_started"
    tool_call_completed = "tool_call_completed"
    model_request_completed = "model_request_completed"
    run_content = "run_content"
    run_completed = "run_completed"


# ─────────────────────────────────────────────────────────────────────────────
# Event data classes — shape-compatible with Agno event objects
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolInfo:
    tool_name: str
    tool_args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Metrics:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class RunOutput:
    metrics: Optional[Metrics] = None


@dataclass
class AgentEvent:
    event: RunEvent
    tool: Optional[ToolInfo] = None
    content: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    metrics: Optional[Metrics] = None


# ─────────────────────────────────────────────────────────────────────────────
# Model shim — exposes .id so cli_runtime's model-swap check works
# ─────────────────────────────────────────────────────────────────────────────

class ModelInfo:
    def __init__(self, model_id: str):
        self.id = model_id


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities (ported from legacy agent_graph.py)
# ─────────────────────────────────────────────────────────────────────────────

def _estimate_tokens(msg) -> int:
    """Rough token estimate: ~4 chars per token."""
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    extra = sum(len(str(tc)) for tc in getattr(msg, "tool_calls", []) or [])
    return max(1, (len(content) + extra) // 4)


def _trim_messages(messages: list, max_tokens: int = 100_000) -> list:
    """Trim oldest messages to stay within context budget.

    Always preserves the most-recent HumanMessage.
    """
    msgs = list(messages)
    total = sum(_estimate_tokens(m) for m in msgs)
    if total <= max_tokens:
        return msgs

    last_human_idx = None
    for i in reversed(range(len(msgs))):
        if isinstance(msgs[i], HumanMessage):
            last_human_idx = i
            break

    must_keep = {last_human_idx} if last_human_idx is not None else set()
    i = 0
    while total > max_tokens and i < len(msgs):
        if i not in must_keep:
            total -= _estimate_tokens(msgs[i])
            msgs[i] = None
        i += 1
    return [m for m in msgs if m is not None]


# ─────────────────────────────────────────────────────────────────────────────
# History compression — summarise older messages when they exceed 30k tokens
# ─────────────────────────────────────────────────────────────────────────────

_COMPRESS_TOKEN_THRESHOLD = 30_000

_COMPRESS_SYSTEM_PROMPT = (
    "You are a conversation compressor for a coding assistant. "
    "Summarise the following conversation history into a structured context block. "
    "Your summary MUST preserve ALL of the following with full precision:\n"
    "• File paths that were read, created, edited, or deleted\n"
    "• Exact line numbers and code snippets that were changed\n"
    "• SEARCH/REPLACE blocks or diffs that were applied\n"
    "• Terminal commands that were run and their key output\n"
    "• Errors encountered and how they were resolved\n"
    "• Decisions made and reasoning behind them\n"
    "• The user's original request and any follow-up instructions\n"
    "• Current state: what is done, what is pending\n\n"
    "Format the summary as a structured reference document. "
    "Use exact file paths and line numbers — never paraphrase code. "
    "Be concise but NEVER drop actionable context. "
    "Do NOT add commentary or suggestions — just summarise what happened."
)


def _compress_messages(messages: list) -> list:
    """Compress older messages when total tokens exceed the threshold.

    Keeps the current turn intact (last HumanMessage + everything after it).
    Summarises everything before that into a single SystemMessage using the
    same model the agent is currently configured to use.

    Returns the original list unchanged if under threshold.
    """
    total = sum(_estimate_tokens(m) for m in messages)
    if total <= _COMPRESS_TOKEN_THRESHOLD:
        return messages

    # Find the boundary: last HumanMessage marks the start of the current turn
    last_human_idx = None
    for i in reversed(range(len(messages))):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break

    if last_human_idx is None or last_human_idx < 2:
        # Nothing meaningful to compress
        return messages

    # Split: older history vs current turn
    older = messages[:last_human_idx]
    current_turn = messages[last_human_idx:]

    # Check if the older portion alone is worth compressing
    older_tokens = sum(_estimate_tokens(m) for m in older)
    if older_tokens < 5_000:
        # Too small to bother — just trim instead
        return _trim_messages(messages, max_tokens=100_000)

    # Build a text representation of older messages for the compressor
    history_parts = []
    for msg in older:
        if isinstance(msg, SystemMessage):
            continue  # skip system prompts — they'll be re-added fresh
        role = "User" if isinstance(msg, HumanMessage) else \
               "Assistant" if isinstance(msg, AIMessage) else \
               f"Tool({getattr(msg, 'name', 'unknown')})"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)

        # Include tool calls if present
        tool_calls_text = ""
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            tc_parts = []
            for tc in msg.tool_calls:
                args_str = str(tc.get("args", {}))
                # Truncate very long tool args (e.g. full file writes) but keep enough
                if len(args_str) > 1500:
                    args_str = args_str[:1500] + "... [truncated]"
                tc_parts.append(f"  → {tc['name']}({args_str})")
            tool_calls_text = "\n".join(tc_parts)

        # Truncate very long individual messages but keep enough for context
        if len(content) > 3000:
            content = content[:3000] + "\n... [truncated]"

        entry = f"[{role}]"
        if content.strip():
            entry += f"\n{content}"
        if tool_calls_text:
            entry += f"\n{tool_calls_text}"
        history_parts.append(entry)

    history_text = "\n\n---\n\n".join(history_parts)

    # Cap the text we send for compression to avoid blowing up the compressor call
    if len(history_text) > 50_000:
        history_text = history_text[:50_000] + "\n\n... [older history truncated for compression]"

    try:
        compressor = _get_model("coder")
        resp = compressor.invoke([
            SystemMessage(content=_COMPRESS_SYSTEM_PROMPT),
            HumanMessage(content=history_text),
        ])
        summary = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as e:
        # Compression failed — fall back to simple trimming
        import sys
        print(f"[compression fallback] {e}", file=sys.stderr)
        return _trim_messages(messages, max_tokens=100_000)

    # Replace older messages with a single SystemMessage containing the summary
    compressed = [
        SystemMessage(content=(
            "=== COMPRESSED CONVERSATION HISTORY ===\n"
            "The following is a summary of prior conversation turns. "
            "Treat this as authoritative context for what has already been discussed and done.\n\n"
            f"{summary}\n"
            "=== END COMPRESSED HISTORY ==="
        ))
    ] + current_turn

    return compressed


def _extract_usage(response) -> dict:
    """Extract token counts from an AIMessage (handles both OpenAI and Anthropic field names)."""
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        if isinstance(um, dict):
            return {
                "input_tokens": um.get("input_tokens", um.get("prompt_tokens", 0)),
                "output_tokens": um.get("output_tokens", um.get("completion_tokens", 0)),
            }
        return {
            "input_tokens": getattr(um, "input_tokens", 0) or getattr(um, "prompt_tokens", 0),
            "output_tokens": getattr(um, "output_tokens", 0) or getattr(um, "completion_tokens", 0),
        }
    if hasattr(response, "additional_kwargs"):
        tu = response.additional_kwargs.get("token_usage", {})
        if tu:
            return {
                "input_tokens": tu.get("prompt_tokens", tu.get("input_tokens", 0)),
                "output_tokens": tu.get("completion_tokens", tu.get("output_tokens", 0)),
            }
    return {}


# _COMPRESS_EVERY = 10  # Mirror Agno's compress_tool_results_limit=10


# def _compress_tool_results(messages: list, compress_every: int = _COMPRESS_EVERY) -> list:
#     """
#     After every `compress_every` ToolMessages in the current turn, summarise the
#     oldest uncompressed batch using a cheap LLM (openai/gpt-oss-120b).
#
#     Mirrors Agno's CompressionManager(compress_tool_results_limit=3):
#     - Keeps message structure intact (tool_call_ids preserved for LangChain)
#     - Replaces the content of compressed ToolMessages with a summary
#     - Only compresses when a full batch has accumulated
#     """
#     # Find boundary of current turn (last HumanMessage)
#     last_human = -1
#     for i, m in enumerate(messages):
#         if isinstance(m, HumanMessage):
#             last_human = i
#     if last_human == -1:
#         return messages
#
#     # Collect ToolMessages in the current turn
#     current_turn = list(enumerate(messages))[last_human + 1:]
#     tool_entries = [(idx, m) for idx, m in current_turn if isinstance(m, ToolMessage)]
#     # Only compress when a full uncompressed batch has accumulated
#     uncompressed = [
#         (idx, m) for idx, m in tool_entries
#         if not str(m.content).startswith("[Compressed")
#     ]
#     if len(uncompressed) < compress_every:
#         return messages
#
#     batch = uncompressed[:compress_every]
#     try:
#         compressor = ChatOpenAI(
#             model="openai/gpt-oss-120b",
#             api_key=config.openrouter_api_key,
#             base_url="https://openrouter.ai/api/v1",
#         )
#         combined = "\n\n---\n\n".join(
#             f"Tool `{m.name}`:\n{str(m.content)[:3000]}"
#             for _, m in batch
#         )
#         resp = compressor.invoke([
#             SystemMessage(content=(
#                 "Summarise these tool results concisely. "
#                 "Keep: file paths, line numbers, code snippets, errors, key values. "
#                 "Drop: verbose output, repeated info."
#             )),
#             HumanMessage(content=combined),
#         ])
#         summary = f"[Compressed {compress_every} tool results]: {resp.content}"
#
#         msgs = list(messages)
#         for i, (msg_idx, orig) in enumerate(batch):
#             msgs[msg_idx] = ToolMessage(
#                 content=summary if i == 0 else "[Compressed: see previous result]",
#                 tool_call_id=orig.tool_call_id,
#                 name=orig.name,
#             )
#         return msgs
#     except Exception:
#         return messages  # compression optional — never break the agent


def _extract_skills(response) -> list:
    if not hasattr(response, "tool_calls"):
        return []
    return [
        tc["name"].replace("run_", "")
        for tc in response.tool_calls
        if tc["name"].startswith("run_")
    ]


def _extract_read_skills(response) -> list:
    if not hasattr(response, "tool_calls"):
        return []
    return [
        tc["args"]["skill_name"]
        for tc in response.tool_calls
        if tc["name"] == "read_skill_blueprint" and "skill_name" in tc.get("args", {})
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Core tool list — mirrors agent_factory._get_core_tools()
# ─────────────────────────────────────────────────────────────────────────────

_BASE_TOOLS = [
    # Filesystem (write/edit only — directed reads via terminal rg+sed)
    write_to_file_tool,
    delete_file,
    edit_file,
    whole_file_update,
    # Terminal
    run_terminal_command,
    # Web search
    search_web,
    # Code symbol index
    # search_codebase,
    # GitHub
    github_repo_info,
    github_list_issues,
    github_view_issue,
    github_list_prs,
    github_view_pr,
    github_list_branches,
    github_list_commits,
    github_list_tags,
    github_create_issue,
    github_create_pr,
    github_merge_pr,
    github_close_issue,
    github_create_comment,
    github_create_branch,
    github_push_commits,
    execute_github_command,
    # Guidelines & manuals
    get_terminal_reference,
    get_github_reference,
    get_skill_usage_guidelines,
    get_coding_standards,
    get_execution_principles,
    get_mcp_guidelines,
    get_active_skills_overview,
    # Code intelligence (Axon knowledge graph)
    search_codebase_graph,
    axon_context,
    axon_impact,
]


def _get_all_tools(extra_tools: Optional[list] = None) -> list:
    """Assemble full tool list: core + skills + MCP + any extra."""
    tools = list(_BASE_TOOLS)
    try:
        from skill_manager import skill_manager as _sm
        tools.extend(_sm.get_research_tools())
        tools.extend(_sm.get_skill_tools())
    except Exception:
        pass
    try:
        from mcp_manager import mcp_manager as _mcp
        tools.extend(_mcp.get_tools())
    except Exception:
        pass
    if extra_tools:
        tools.extend(extra_tools)
        
    unique_tools = []
    seen_names = set()
    for t in tools:
        name = getattr(t, "name", getattr(t, "__name__", str(t)))
        if name not in seen_names:
            seen_names.add(name)
            unique_tools.append(t)
            
    return unique_tools


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph node factories
# ─────────────────────────────────────────────────────────────────────────────

def _get_model(role: str = "coder"):
    """Return the appropriate LangChain chat model for the current config.

    Routing priority:
    - claude-* / anthropic.* models → Anthropic API (when ANTHROPIC_API_KEY set)
    - gpt-* models                  → OpenAI API   (when OPENAI_API_KEY set)
    - Groq model IDs                → Groq API     (when GROQ_API_KEY set)
    - everything else               → OpenRouter
    """
    model_id = config.model

    provider = config.active_provider

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=model_id,
                api_key=config.anthropic_api_key,
                max_tokens=16384,
            )
        except ImportError:
            pass  # fall through to OpenRouter if langchain_anthropic not installed

    if provider == "openai":
        return ChatOpenAI(
            model=model_id,
            api_key=config.openai_api_key,
            base_url="https://api.openai.com/v1",
            temperature=1,  # newer OpenAI models only accept the default value (1)
        )

    if provider == "groq":
        return ChatOpenAI(
            model=model_id,
            api_key=config.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

    if provider == "together":
        return ChatOpenAI(
            model=model_id,
            api_key=config.together_api_key,
            base_url="https://api.together.xyz/v1",
        )

    # Default: OpenRouter
    return ChatOpenAI(
        model=model_id,
        api_key=config.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://archcode.ai",
            "X-Title": "ArchCode CLI",
        },
        max_tokens=16384,
    )


def _make_agent_node(extra_tools: Optional[list] = None):
    """Factory: return a supervisor agent_node closure bound to extra_tools."""

    def agent_node(state: AgentState):
        messages = state["messages"]

        # Anti-loop: count messages accumulated this turn (since last HumanMessage)
        turn_msgs = []
        for msg in reversed(list(messages)):
            if isinstance(msg, HumanMessage):
                break
            turn_msgs.append(msg)

        # Count repeated search_codebase calls — a sign the agent is stuck searching
        # search_rag_calls = sum(
        #     1 for m in turn_msgs
        #     if isinstance(m, AIMessage)
        #     and any(tc["name"] == "search_codebase" for tc in (m.tool_calls or []))
        # )

        # Inject a warning at 3 search_codebase calls to push toward planning
        # if search_rag_calls == 3:
        #     messages = list(messages) + [SystemMessage(content=(
        #         "NOTICE: You have called search_codebase 3 times. "
        #         "You should have enough context now. Create your plan with exact "
        #         "file paths, line numbers, and SEARCH/REPLACE code blocks. Stop searching."
        #     ))]

        # Early warning at 10 tool calls to prompt agent to wrap up
        tool_use_count_early = sum(1 for m in messages if isinstance(m, ToolMessage))
        if tool_use_count_early == 10:
            messages = list(messages) + [SystemMessage(content=(
                "⚠️ TOOL LIMIT WARNING: You have used 10 tool calls. "
                "You are approaching the tool use limit (15 max). "
                "If you have gathered sufficient information, summarize your findings NOW. "
                "Avoid starting new searches. Present what you've discovered to the user."
            ))]

        # Threshold: fire well before recursion_limit=50 so we always get a clean response
        should_stop = len(turn_msgs) > 40

        if should_stop:
            # Make one final tool-free LLM call to produce a clean summary
            model = _get_model("coder")
            trimmed = _trim_messages(messages, max_tokens=60_000)
            try:
                response = model.invoke(
                    [SystemMessage(content=(
                        "You have reached the tool use limit for this request. "
                        "Based on everything you have found so far, provide a clear concise summary of: "
                        "what was found, what was done, and any remaining items. "
                        "Do NOT make any tool calls. Respond with text only."
                    ))] + trimmed
                )
                summary = response.content if isinstance(response.content, str) else str(response.content)
                if not summary:
                    summary = "Reached the tool use limit. Please try a more specific query."
            except Exception:
                summary = "Reached the tool use limit. Please try a more specific query."

            return {
                "messages": [
                    AIMessage(content=summary, name="Archimyst")
                ],
                "next": "FINISH",
                "token_usage": {},
                "active_skills": [],
                "skills_read": [],
            }

        model = _get_model("coder")
        all_tools = _get_all_tools(extra_tools)
        model_with_tools = model.bind_tools(all_tools)

        # Calculate tool use count to inform the agent of its progress/limits
        tool_use_count = sum(1 for m in messages if isinstance(m, ToolMessage))
        
        # Compress history if messages exceed 30k tokens, then trim as safety net
        compressed = _compress_messages(messages)
        trimmed = _trim_messages(compressed, max_tokens=100_000)

        # Build system messages: base instructions + plan context if active
        _system_messages = [SystemMessage(content=get_agent_instructions(tool_use_count=tool_use_count))]
        _plan_ctx = get_plan_context()
        if _plan_ctx:
            _plan_tracker_summary = ""
            try:
                from app.runtime.plan_tracker import get_tracker as _get_tracker
                _tracker = _get_tracker()
                if _tracker:
                    _plan_tracker_summary = _tracker.get_status_summary()
            except Exception:
                pass
            _system_messages.append(SystemMessage(content=(
                "=== ACTIVE PLAN (.archcode/archcode.md) ===\n"
                "Follow this plan strictly. Execute tasks in order. "
                "Do not re-discover or re-plan what has already been decided.\n\n"
                f"{_plan_ctx}\n"
                + (f"\n{_plan_tracker_summary}\n" if _plan_tracker_summary else "")
                + "=== END ACTIVE PLAN ==="
            )))

        try:
            response = model_with_tools.invoke(
                _system_messages + trimmed
            )
            # Filter out search_codebase calls with empty/short queries
            if response.tool_calls:
                valid_calls = []
                for tc in response.tool_calls:
                    if tc["name"] == "search_codebase":
                        query_val = tc.get("args", {}).get("query", "")
                        if not query_val or len(str(query_val).strip()) < 3:
                            continue
                    valid_calls.append(tc)
                response.tool_calls = valid_calls
        except Exception as exc:
            return {
                "messages": [
                    AIMessage(content=f"Error calling model: {exc}", name="Archimyst")
                ],
                "next": "FINISH",
                "token_usage": {},
                "active_skills": [],
                "skills_read": [],
            }

        # Detect empty response after tool execution — retry without tools
        content_str = response.content if isinstance(response.content, str) else str(response.content or "")
        has_recent_tools = any(isinstance(m, ToolMessage) for m in list(messages)[-10:])
        if not content_str.strip() and not response.tool_calls and has_recent_tools:
            try:
                retry_response = model.invoke(
                    _system_messages + trimmed + [SystemMessage(content=(
                        "You just executed tools and received results above. "
                        "Summarize what you found and respond to the user's request. "
                        "Do NOT make any tool calls — respond with text only."
                    ))]
                )
                if retry_response.content:
                    response = retry_response
            except Exception:
                pass  # fall through with original empty response

        # If still empty after retry, synthesize a minimal response from tool results
        if not (response.content if isinstance(response.content, str) else str(response.content or "")).strip() and not response.tool_calls:
            tool_results = [
                m.content for m in list(messages)[-10:]
                if isinstance(m, ToolMessage) and m.content
            ]
            if tool_results:
                fallback = "Here are the results from the tools I ran:\n\n" + "\n\n---\n\n".join(
                    str(r)[:2000] for r in tool_results[-3:]
                )
                response = AIMessage(content=fallback, name="Archimyst")

        # Plan detection takes PRIORITY over tool calls — if the model outputs
        # "PLAN AWAITING APPROVAL" we route to PLAN_PENDING even if it also
        # attached tool calls (which we strip to prevent looping).
        if "PLAN AWAITING APPROVAL" in (response.content or ""):
            next_state = "PLAN_PENDING"
            # Strip any accidental tool calls that came with the plan
            response = AIMessage(content=response.content, name="Archimyst")
        elif response.tool_calls:
            next_state = "supervisor"
        else:
            next_state = "FINISH"

        return {
            "messages": [response],
            "next": next_state,
            "token_usage": _extract_usage(response),
            "active_skills": _extract_skills(response),
            "skills_read": _extract_read_skills(response),
        }

    return agent_node


def _make_tool_node(extra_tools: Optional[list] = None):
    """Factory: return a dynamic tool_node closure that deduplicates calls."""

    def dynamic_tool_node(state: AgentState):
        messages = list(state["messages"])

        # Sanitize tool call names and deduplicate on the last AIMessage
        if messages and isinstance(messages[-1], AIMessage):
            last = messages[-1]
            if getattr(last, "tool_calls", None):
                seen: set = set()
                deduped = []
                for tc in last.tool_calls:
                    # Strip whitespace from tool names (LLM sometimes adds leading spaces)
                    tc["name"] = tc["name"].strip()
                    key = (tc["name"], str(tc.get("args", {})))
                    if key not in seen:
                        seen.add(key)
                        deduped.append(tc)
                # Always rebuild to apply stripped names
                messages[-1] = AIMessage(
                    content=last.content,
                    tool_calls=deduped,
                    id=last.id,
                )

        all_tools = _get_all_tools(extra_tools)
        node = ToolNode(all_tools)
        return node.invoke({**state, "messages": messages})

    return dynamic_tool_node


# ─────────────────────────────────────────────────────────────────────────────
# Router functions
# ─────────────────────────────────────────────────────────────────────────────

def _agent_router(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tool_node"
    return state.get("next", "FINISH")


def _tool_router(state: AgentState) -> str:
    return "supervisor"  # always route back after tool execution


# ─────────────────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_compiled_graph(extra_tools: Optional[list] = None):
    return build_graph(
        agent_node_fn=_make_agent_node(extra_tools),
        tool_node_fn=_make_tool_node(extra_tools),
        agent_router_fn=_agent_router,
        tool_router_fn=_tool_router,
    )


def create_graph(extra_tools: Optional[list] = None):
    """Public factory: build a fresh compiled graph with current tools."""
    return _build_compiled_graph(extra_tools)


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph Agent Adapter
# Wraps the compiled graph with an Agno-compatible .run() interface so
# cli_runtime.py requires only a one-line import change.
# ─────────────────────────────────────────────────────────────────────────────

class LangGraphAgent:
    """
    Agno-compatible wrapper around a LangGraph compiled graph.

    Exposes:
      .run(input, stream, stream_events) → Generator[AgentEvent]
      .model.id                          → current model id
      .session_id                        → session identifier
      .run_output                        → RunOutput with Metrics after last run
      .get_session_metrics()             → None (no persistent DB for this variant)
    """

    def __init__(
        self,
        session_id: str,
        extra_tools: Optional[list] = None,
        skills: Any = None,  # Agno Skills — unused by LangGraph, accepted for compat
    ):
        self.session_id = session_id
        self.model = ModelInfo(config.model)
        self._extra_tools = extra_tools or []
        self._graph = _build_compiled_graph(self._extra_tools)
        self._history: List = []
        self._run_output: Optional[RunOutput] = None

    def run(
        self,
        user_input: str,
        stream: bool = True,
        stream_events: bool = True,
    ) -> Generator[AgentEvent, None, None]:
        """
        Run the agent on user_input.

        Yields AgentEvent objects compatible with cli_runtime.py's event loop:
          - tool_call_started   (one per tool call)
          - tool_call_completed (one per ToolMessage returned)
          - model_request_completed (one per LLM call)
          - run_content         (once, with the final text response)
          - run_completed       (once, with aggregate Metrics)
        """
        # Compress history from prior turns if it has grown beyond threshold
        if self._history:
            self._history = _compress_messages(self._history)

        # Inject plan context as a system message if an active plan exists
        plan_messages = []
        _plan_ctx = get_plan_context()
        if _plan_ctx:
            plan_messages.append(SystemMessage(content=(
                "=== ACTIVE PLAN CONTEXT ===\n"
                "You have an approved plan saved at .archcode/archcode.md. "
                "Follow it strictly and execute tasks in order.\n\n"
                f"{_plan_ctx}\n"
                "=== END PLAN CONTEXT ==="
            )))

        current_messages = plan_messages + list(self._history) + [HumanMessage(content=user_input)]
        inputs: AgentState = {
            "messages": current_messages,
            "next": "",
            "token_usage": {},
            "active_skills": [],
            "skills_read": [],
        }

        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        all_new_messages: List = []

        for update in self._graph.stream(inputs, stream_mode="updates", config={"recursion_limit": 50}):
            for _node_name, state_delta in update.items():
                delta_messages = state_delta.get("messages", [])
                all_new_messages.extend(delta_messages)

                for msg in delta_messages:
                    if isinstance(msg, AIMessage):
                        # Token accounting
                        usage = _extract_usage(msg)
                        in_toks = usage.get("input_tokens", 0) or 0
                        out_toks = usage.get("output_tokens", 0) or 0
                        tot_toks = usage.get("total_tokens", in_toks + out_toks) or (in_toks + out_toks)
                        total_usage["input_tokens"] += in_toks
                        total_usage["output_tokens"] += out_toks
                        total_usage["total_tokens"] += tot_toks

                        yield AgentEvent(
                            event=RunEvent.model_request_completed,
                            input_tokens=in_toks,
                            output_tokens=out_toks,
                            total_tokens=tot_toks,
                        )

                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                yield AgentEvent(
                                    event=RunEvent.tool_call_started,
                                    tool=ToolInfo(
                                        tool_name=tc["name"],
                                        tool_args=tc.get("args", {}),
                                    ),
                                )
                        else:
                            # Final text response
                            content = (
                                msg.content
                                if isinstance(msg.content, str)
                                else str(msg.content)
                            )
                            if content:
                                yield AgentEvent(
                                    event=RunEvent.run_content,
                                    content=content,
                                )

                    elif isinstance(msg, ToolMessage):
                        yield AgentEvent(event=RunEvent.tool_call_completed)

        # Persist history for multi-turn conversations
        self._history = current_messages + all_new_messages

        # Safety net: if the graph completed but no run_content was ever yielded,
        # extract the last AI response or synthesize one from tool results
        has_content = any(
            isinstance(m, AIMessage) and not m.tool_calls and m.content
            for m in all_new_messages
        )
        if not has_content and all_new_messages:
            # Try to find any AIMessage content (even from tool-calling messages)
            fallback_parts = []
            for m in reversed(all_new_messages):
                if isinstance(m, ToolMessage) and m.content:
                    fallback_parts.append(str(m.content)[:1500])
                    if len(fallback_parts) >= 3:
                        break
            if fallback_parts:
                fallback_parts.reverse()
                fallback = "Here are the results from the tools I ran:\n\n" + "\n\n---\n\n".join(fallback_parts)
                yield AgentEvent(event=RunEvent.run_content, content=fallback)

        metrics = Metrics(
            input_tokens=total_usage["input_tokens"],
            output_tokens=total_usage["output_tokens"],
            total_tokens=total_usage["total_tokens"],
        )
        self._run_output = RunOutput(metrics=metrics)

        yield AgentEvent(event=RunEvent.run_completed, metrics=metrics)

    @property
    def run_output(self) -> Optional[RunOutput]:
        return self._run_output

    def get_session_metrics(self):
        """Return None — no persistent SQLite session for LangGraph variant."""
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public factory
# ─────────────────────────────────────────────────────────────────────────────

def create_langgraph_agent(
    session_id: str,
    extra_tools: Optional[list] = None,
    skills: Any = None,
) -> LangGraphAgent:
    """
    Factory function: create a LangGraphAgent for the ArchCode CLI.

    Drop-in replacement for agent_factory.create_agent — same signature.
    """
    return LangGraphAgent(
        session_id=session_id,
        extra_tools=extra_tools,
        skills=skills,
    )
