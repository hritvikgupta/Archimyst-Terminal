"""Graph construction utilities for LangGraph-based ArchCode agents."""

from langgraph.graph import END, StateGraph

from app.agents.state import AgentState


def build_graph(agent_node_fn, tool_node_fn, agent_router_fn, tool_router_fn):
    """
    Build and compile a standard supervisor → tool_node LangGraph workflow.

    Args:
        agent_node_fn: The main agent node (supervisor) callable.
        tool_node_fn: The tool execution node callable.
        agent_router_fn: Conditional edge function for the supervisor node.
        tool_router_fn: Conditional edge function for the tool node.

    Returns:
        A compiled LangGraph CompiledStateGraph.
    """
    wf = StateGraph(AgentState)
    wf.add_node("supervisor", agent_node_fn)
    wf.add_node("tool_node", tool_node_fn)
    wf.set_entry_point("supervisor")
    wf.add_conditional_edges(
        "supervisor",
        agent_router_fn,
        {
            "tool_node": "tool_node",
            "FINISH": END,
            "PLAN_PENDING": END,
        },
    )
    wf.add_conditional_edges(
        "tool_node",
        tool_router_fn,
        {"supervisor": "supervisor"},
    )
    return wf.compile()
