"""LangGraph-based data analysis agent for ArchCode CLI.

Replaces the Agno-based data agent with the same LangGraph pattern used
by agent_graph.py.  Reuses RunEvent, AgentEvent, _get_model, etc. from
the main agent module — no duplication.

Architecture
------------
  user_input
      |
  supervisor node  --(tool calls?)-->  tool_node
      |  <----------------------------------
      |
  (no more tool calls)
      |
  final AIMessage -> run_content + run_completed events
"""

from typing import Generator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from app.agents.agent_graph import (
    RunEvent,
    AgentEvent,
    ToolInfo,
    Metrics,
    RunOutput,
    ModelInfo,
    _get_model,
    _compress_messages,
    _trim_messages,
    _extract_usage,
)
from app.agents.graph import build_graph
from app.agents.state import AgentState
from config import config
from prompts_data import get_data_agent_instructions
from tools.data_tools import get_all_data_tools


# ─────────────────────────────────────────────────────────────────────────────
# Tool assembly
# ─────────────────────────────────────────────────────────────────────────────

def _get_data_tools(extra_tools: Optional[list] = None) -> list:
    """Assemble the full data tool list, deduplicating by name."""
    tools = get_all_data_tools(config)
    if extra_tools:
        tools.extend(extra_tools)
    unique = []
    seen: set = set()
    for t in tools:
        name = getattr(t, "name", getattr(t, "__name__", str(t)))
        if name not in seen:
            seen.add(name)
            unique.append(t)
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph node factories
# ─────────────────────────────────────────────────────────────────────────────

def _make_data_agent_node(extra_tools: Optional[list] = None):
    """Factory: return a data-agent supervisor node closure."""

    def agent_node(state: AgentState):
        messages = state["messages"]

        # Anti-loop: count messages accumulated this turn (since last HumanMessage)
        turn_msgs: list = []
        for msg in reversed(list(messages)):
            if isinstance(msg, HumanMessage):
                break
            turn_msgs.append(msg)

        # Count tool calls this turn
        tool_calls_this_turn = sum(
            len(getattr(m, "tool_calls", []) or [])
            for m in turn_msgs
            if isinstance(m, AIMessage)
        )

        # Stop at 30 tool calls or 60 messages
        should_stop = tool_calls_this_turn >= 30 or len(turn_msgs) > 60

        if should_stop:
            model = _get_model("data")
            trimmed = _trim_messages(messages, max_tokens=60_000)
            try:
                response = model.invoke(
                    [SystemMessage(content=(
                        "You have reached the tool use limit for this request. "
                        "Based on everything you have found so far, provide a clear "
                        "concise summary of what was found, what was done, and any "
                        "remaining items. Do NOT make any tool calls."
                    ))] + trimmed
                )
                summary = response.content if isinstance(response.content, str) else str(response.content)
                if not summary:
                    summary = "Reached the tool use limit. Please try a more specific query."
            except Exception:
                summary = "Reached the tool use limit. Please try a more specific query."

            return {
                "messages": [AIMessage(content=summary, name="DataMyst")],
                "next": "FINISH",
                "token_usage": {},
                "active_skills": [],
                "skills_read": [],
            }

        model = _get_model("data")
        all_tools = _get_data_tools(extra_tools)
        model_with_tools = model.bind_tools(all_tools)

        # Compress + trim history
        compressed = _compress_messages(messages)
        trimmed = _trim_messages(compressed, max_tokens=100_000)

        system_messages = [SystemMessage(content=get_data_agent_instructions())]

        try:
            response = model_with_tools.invoke(system_messages + trimmed)
        except Exception as exc:
            return {
                "messages": [AIMessage(content=f"Error calling model: {exc}", name="DataMyst")],
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
                    system_messages + trimmed + [SystemMessage(content=(
                        "You just executed tools and received results above. "
                        "Summarize what you found and respond to the user's request. "
                        "Do NOT make any tool calls — respond with text only."
                    ))]
                )
                if retry_response.content:
                    response = retry_response
            except Exception:
                pass

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
                response = AIMessage(content=fallback, name="DataMyst")

        if response.tool_calls:
            next_state = "supervisor"
        else:
            next_state = "FINISH"

        return {
            "messages": [response],
            "next": next_state,
            "token_usage": _extract_usage(response),
            "active_skills": [],
            "skills_read": [],
        }

    return agent_node


def _make_data_tool_node(extra_tools: Optional[list] = None):
    """Factory: return a data-agent tool_node closure with deduplication."""

    def dynamic_tool_node(state: AgentState):
        messages = list(state["messages"])

        # Sanitize tool call names and deduplicate on the last AIMessage
        if messages and isinstance(messages[-1], AIMessage):
            last = messages[-1]
            if getattr(last, "tool_calls", None):
                seen: set = set()
                deduped: list = []
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

        all_tools = _get_data_tools(extra_tools)
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
    return "supervisor"


# ─────────────────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_data_graph(extra_tools: Optional[list] = None):
    return build_graph(
        agent_node_fn=_make_data_agent_node(extra_tools),
        tool_node_fn=_make_data_tool_node(extra_tools),
        agent_router_fn=_agent_router,
        tool_router_fn=_tool_router,
    )


# ─────────────────────────────────────────────────────────────────────────────
# DataLangGraphAgent — Agno-compatible wrapper
# ─────────────────────────────────────────────────────────────────────────────

class DataLangGraphAgent:
    """
    LangGraph-based data analysis agent with Agno-compatible .run() interface.

    Exposes:
      .run(input, stream, stream_events) -> Generator[AgentEvent]
      .model.id                          -> current model id
      .session_id                        -> session identifier
      .run_output                        -> RunOutput with Metrics after last run
      .get_session_metrics()             -> None (no persistent DB)
    """

    def __init__(
        self,
        session_id: str,
        extra_tools: Optional[list] = None,
    ):
        self.session_id = session_id
        self.model = ModelInfo(config.model)
        self._extra_tools = extra_tools or []
        self._graph = _build_data_graph(self._extra_tools)
        self._history: List = []
        self._run_output: Optional[RunOutput] = None

    def run(
        self,
        user_input: str,
        stream: bool = True,
        stream_events: bool = True,
    ) -> Generator[AgentEvent, None, None]:
        """
        Run the data agent on user_input.

        Yields AgentEvent objects compatible with cli_runtime.py's event loop.
        """
        # Compress history from prior turns
        if self._history:
            self._history = _compress_messages(self._history)

        current_messages = list(self._history) + [HumanMessage(content=user_input)]
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
                        # Pass tool output content so cli_runtime can display it
                        tool_content = (
                            msg.content
                            if isinstance(msg.content, str)
                            else str(msg.content)
                        ) if msg.content else None
                        yield AgentEvent(
                            event=RunEvent.tool_call_completed,
                            content=tool_content,
                        )

        # Persist history for multi-turn conversations
        self._history = current_messages + all_new_messages

        # Safety net: if the graph completed but no run_content was ever yielded,
        # extract the last AI response or synthesize one from tool results
        has_content = any(
            isinstance(m, AIMessage) and not m.tool_calls and m.content
            for m in all_new_messages
        )
        if not has_content and all_new_messages:
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

def create_data_agent(
    session_id: str,
    extra_tools: Optional[list] = None,
) -> DataLangGraphAgent:
    """
    Create a DataLangGraphAgent for the ArchCode CLI.

    Drop-in replacement for the Agno-based create_data_agent — same signature.
    """
    return DataLangGraphAgent(
        session_id=session_id,
        extra_tools=extra_tools,
    )
