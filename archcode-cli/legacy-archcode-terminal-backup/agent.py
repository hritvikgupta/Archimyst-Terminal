import json
from typing import TypedDict, Annotated, Sequence
import operator
from rich.console import Console

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from config import config
from tools import filesystem, terminal, web, rag

console = Console()

# Define the state
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]

class Agent:
    def __init__(self):
        # Initialize LLM with OpenRouter base URL
        self.llm = ChatOpenAI(
            model=config.model,
            openai_api_key=config.openrouter_api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0,
            streaming=True
        )

        # Define tools
        self.tools = [
            filesystem.read_file,
            filesystem.write_file,
            filesystem.list_dir,
            terminal.run_terminal_command,
            web.search_web,
            rag.search_codebase
        ]
        
        # Bind tools to LLM
        self.model = self.llm.bind_tools(self.tools)

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        # Define nodes
        workflow.add_node("agent", self._call_model)
        workflow.add_node("tools", ToolNode(self.tools))

        # Define edges
        workflow.set_entry_point("agent")
        
        # Conditional edge: if tool calls, go to tools, else end
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "end": END
            }
        )
        
        # Edge from tools back to agent
        workflow.add_edge("tools", "agent")

        return workflow.compile()

    def _call_model(self, state: AgentState):
        messages = state["messages"]
        response = self.model.invoke(messages)
        return {"messages": [response]}

    def _should_continue(self, state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        
        if last_message.tool_calls:
            return "continue"
        return "end"

    def chat_generator(self, user_input: str, history: list):
        """
        Stream events from the graph.
        """
        inputs = {"messages": history + [HumanMessage(content=user_input)]}
        
        # Yield events to the CLI
        for event in self.graph.stream(inputs, stream_mode="updates"):
            yield event
