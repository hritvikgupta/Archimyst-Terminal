import json
from typing import Annotated, Sequence, TypedDict, Union, Literal
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from config import config
from prompts import SUPERVISOR_PROMPT, CODER_PROMPT, REVIEWER_PROMPT
from tools.filesystem import read_file, list_dir
from tools.terminal import run_terminal_command
from tools.web import search_web
# from tools.rag import query_codebase # Optional if RAG is ready

# State Definition
class AgentState(TypedDict):
    messages: Sequence[BaseMessage]
    next: str

# Tools Setup
tools = [read_file, list_dir, run_terminal_command, search_web]

# Helper to get model based on role
def get_model(role: str):
    model_id = config.model_map.get(role, config.model)
    # Using ChatOpenAI for broad compatibility (Works with OpenRouter)
    return ChatOpenAI(
        model=model_id, 
        api_key=config.openrouter_api_key, 
        base_url="https://openrouter.ai/api/v1"
    )

# --- Nodes ---

def supervisor_node(state):
    messages = state['messages']
    model = get_model("supervisor")
    
    # The supervisor decides the next step or finishes
    # We force it to output a JSON-like structure or just simple text for routing
    # For simplicity in this V1, let's append a specific guidance to the system prompt
    
    options = ["coder", "reviewer", "executor", "FINISH"]
    
    system_msg = SystemMessage(content=f"{SUPERVISOR_PROMPT}\n\nBased on the conversation, who should act next? Options: {options}. Return ONLY the role name.")
    
    # Filter messages to avoid context window issues if needed, but for now pass all
    chain = model
    response = chain.invoke([system_msg] + messages)
    
    decision = response.content.strip().lower()
    
    # Simple mapping to graph nodes
    if "coder" in decision:
        return {"next": "coder"}
    elif "reviewer" in decision:
        return {"next": "reviewer"}
    elif "executor" in decision:
        return {"next": "executor"}
    elif "finish" in decision:
        return {"next": "FINISH"}
    else:
        # Default fallback
        return {"next": "coder"}

def coder_node(state):
    messages = state['messages']
    model = get_model("coder")
    tool_node = ToolNode(tools) # Coder can use file tools
    
    # Bind tools to the coder model
    model_with_tools = model.bind_tools(tools)
    
    response = model_with_tools.invoke([SystemMessage(content=CODER_PROMPT)] + messages)
    return {"messages": [response], "next": "supervisor"} # Loop back to supervisor

def reviewer_node(state):
    messages = state['messages']
    model = get_model("reviewer")
    response = model.invoke([SystemMessage(content=REVIEWER_PROMPT)] + messages)
    return {"messages": [response], "next": "supervisor"}

def executor_node(state):
    messages = state['messages']
    model = get_model("executor")
    model_with_tools = model.bind_tools(tools)
    response = model_with_tools.invoke([SystemMessage(content=REVIEWER_PROMPT)] + messages) # Reviewer persona shares Executor role for now
    return {"messages": [response], "next": "supervisor"}

# --- Graph Construction ---

workflow = StateGraph(AgentState)

workflow.add_node("supervisor", supervisor_node)
workflow.add_node("coder", coder_node)
workflow.add_node("reviewer", reviewer_node)
workflow.add_node("executor", executor_node)
workflow.add_node("tool_node", ToolNode(tools))

workflow.set_entry_point("supervisor")

workflow.add_edge("tool_node", "supervisor") # Tools return to supervisor for re-evaluation

# Conditional edges from Supervisor
workflow.add_conditional_edges(
    "supervisor",
    lambda x: x["next"],
    {
        "coder": "coder",
        "reviewer": "reviewer",
        "executor": "executor",
        "FINISH": END
    }
)

# Nodes usually go back to Supervisor, unless they called a tool
def should_continue(state):
    last_message = state['messages'][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tool_node"
    return "supervisor"

workflow.add_conditional_edges("coder", should_continue, {"tool_node": "tool_node", "supervisor": "supervisor"})
workflow.add_conditional_edges("executor", should_continue, {"tool_node": "tool_node", "supervisor": "supervisor"})
workflow.add_edge("reviewer", "supervisor")

graph = workflow.compile()
