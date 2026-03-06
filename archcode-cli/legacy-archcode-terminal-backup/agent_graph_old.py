import json
import operator
from typing import Annotated, Sequence, TypedDict, Union, Literal, List, Optional, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from config import config
from prompts import get_enriched_agent_prompt
from tools.filesystem import (
    read_file, write_to_file_tool, edit_file, list_dir, delete_file, whole_file_update,
    view_symbol, list_symbols, view_context, read_file_chunked,
)
from tools.terminal import run_terminal_command
from tools.web import search_web
from tools.rag import search_codebase, get_project_overview
from tools.github import (
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
)
from skill_manager import skill_manager
from mcp_manager import mcp_manager


# --- Helpers ---

def merge_usage(a: dict, b: dict) -> dict:
    """Robustly merge token usage dictionaries, handling nested structures."""
    if not a: return b or {}
    if not b: return a or {}
    res = a.copy()
    for k, v in b.items():
        if isinstance(v, (int, float)):
            res[k] = res.get(k, 0) + v
        elif isinstance(v, dict):
            res[k] = merge_usage(res.get(k, {}), v)
    return res


# --- State Definition ---

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next: str
    token_usage: Annotated[dict, merge_usage]
    active_skills: Annotated[List[str], operator.add]
    skills_read: Annotated[List[str], operator.add]


# --- Tools Setup ---

base_tools = [
    # Smart file reading
    view_symbol, list_symbols, view_context, read_file_chunked,
    # read_file,  # commented out — forcing agents to use smarter reading tools
    # File writing
    write_to_file_tool, edit_file, whole_file_update, delete_file,
    # Navigation
    list_dir,
    # Terminal & Web
    run_terminal_command, search_web,
    # Code search
    search_codebase, get_project_overview,
    # GitHub Tools
    github_repo_info, github_list_issues, github_view_issue, github_list_prs, github_view_pr,
    github_list_branches, github_list_commits, github_list_tags,
    github_create_issue, github_create_pr, github_merge_pr, github_close_issue, github_create_comment,
    github_create_branch, github_push_commits,
]


def get_all_tools():
    """Get all tools including dynamically installed skills and MCP tools."""
    return (base_tools
            + skill_manager.get_research_tools()
            + skill_manager.get_skill_tools()
            + mcp_manager.get_tools())


# Helper to get model based on role
def get_model(role: str):
    model_id = config.model_map.get(role, config.model)
    return ChatOpenAI(
        model=model_id,
        api_key=config.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://archcode.ai",
            "X-Title": "ArchCode CLI"
        }
    )


def _estimate_tokens(msg) -> int:
    """Rough token estimate: ~4 chars per token."""
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    # Tool calls add overhead
    extra = sum(len(str(tc)) for tc in getattr(msg, "tool_calls", []) or [])
    return max(1, (len(content) + extra) // 4)


def trim_messages_to_limit(messages: list, max_tokens: int = 100_000) -> list:
    """Trim oldest messages to stay within context budget.

    Always preserves the most recent HumanMessage so the agent
    knows what the user asked, and keeps recent messages intact.
    Drops oldest messages first until we are under the limit.
    """
    msgs = list(messages)
    total = sum(_estimate_tokens(m) for m in msgs)
    if total <= max_tokens:
        return msgs

    # Find the index of the last HumanMessage — must always keep it
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


def extract_usage(response):
    """Extract token usage from AIMessage if available."""
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        return response.usage_metadata
    if hasattr(response, "additional_kwargs") and "token_usage" in response.additional_kwargs:
        return response.additional_kwargs["token_usage"]
    return {}


def extract_skills(response):
    """Extract skill execution names from tool calls."""
    if not hasattr(response, "tool_calls"):
        return []
    return [tc['name'].replace("run_", "") for tc in response.tool_calls if tc['name'].startswith("run_")]


def extract_read_skills(response):
    """Extract skill names being read as blueprints."""
    if not hasattr(response, "tool_calls"):
        return []
    return [tc['args']['skill_name'] for tc in response.tool_calls if tc['name'] == "read_skill_blueprint" and 'skill_name' in tc['args']]


# --- Single Agent Node ---

def agent_node(state):
    """Single combined agent — searches, reads, plans, and executes."""
    messages = state['messages']

    # Anti-loop: count messages since last HumanMessage
    turn_msgs = []
    for msg in reversed(list(messages)):
        if isinstance(msg, HumanMessage):
            break
        turn_msgs.append(msg)

    # Each tool use cycle = 1 AIMessage (tool_calls) + 1 ToolMessage = 2 messages.
    # A 32-tool-call run generates 64 messages, which blew past the old limit of 40
    # and caused the agent to return the placeholder before writing any real output.
    # 80 gives headroom for up to ~35 unique tool uses + a final response message.
    if len(turn_msgs) > 80:
        return {
            "messages": [AIMessage(content="I've completed the available work. Please review the results.", name="Archimyst")],
            "next": "FINISH",
            "token_usage": {},
            "active_skills": [],
            "skills_read": [],
        }

    model = get_model("coder")
    all_tools = get_all_tools()
    model_with_tools = model.bind_tools(all_tools)

    # Trim history to stay within context budget before every LLM call.
    # This prevents the 2M-token blowup that occurs when tool results
    # accumulate across many sub-calls within a single agent run.
    trimmed_messages = trim_messages_to_limit(messages, max_tokens=100_000)

    try:
        response = model_with_tools.invoke(
            [SystemMessage(content=get_enriched_agent_prompt())] + trimmed_messages
        )
    except Exception as e:
        return {
            "messages": [AIMessage(content=f"Error calling model: {e}", name="Archimyst")],
            "next": "FINISH",
            "token_usage": {},
            "active_skills": [],
            "skills_read": [],
        }

    # Determine routing
    if response.tool_calls:
        next_state = "supervisor"  # routes to tool_node via agent_router
    elif "PLAN AWAITING APPROVAL" in (response.content or ""):
        next_state = "PLAN_PENDING"
    else:
        next_state = "FINISH"

    return {
        "messages": [response],
        "next": next_state,
        "token_usage": extract_usage(response),
        "active_skills": extract_skills(response),
        "skills_read": extract_read_skills(response),
    }


def dynamic_tool_node(state):
    """Tool node that re-resolves tools and deduplicates calls on every invocation."""
    messages = list(state["messages"])

    # Deduplicate tool calls on the last AIMessage.
    # The LLM sometimes emits the same (tool, args) pair multiple times in a
    # single response, causing the same file chunk / search to run 2-3× back
    # to back. Drop the duplicates before ToolNode executes anything.
    if messages and isinstance(messages[-1], AIMessage):
        last = messages[-1]
        if getattr(last, "tool_calls", None):
            seen: set = set()
            deduped = []
            for tc in last.tool_calls:
                key = (tc["name"], str(tc.get("args", {})))
                if key not in seen:
                    seen.add(key)
                    deduped.append(tc)
            if len(deduped) < len(last.tool_calls):
                messages[-1] = AIMessage(
                    content=last.content,
                    tool_calls=deduped,
                    id=last.id,
                )

    all_tools = get_all_tools()
    node = ToolNode(all_tools)
    return node.invoke({**state, "messages": messages})


# --- Graph Construction ---

def agent_router(state):
    last_message = state['messages'][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tool_node"
    return state.get("next", "FINISH")


def tool_router(state):
    return "supervisor"  # always route back to single agent after tool execution


def _build_graph():
    wf = StateGraph(AgentState)
    wf.add_node("supervisor", agent_node)
    wf.add_node("tool_node", dynamic_tool_node)
    wf.set_entry_point("supervisor")
    wf.add_conditional_edges("supervisor", agent_router, {
        "tool_node": "tool_node",
        "FINISH": END,
        "PLAN_PENDING": END,
    })
    wf.add_conditional_edges("tool_node", tool_router, {
        "supervisor": "supervisor",
    })
    return wf.compile()


graph = _build_graph()


def create_graph():
    """Factory: build a fresh compiled graph with current tools."""
    return _build_graph()
