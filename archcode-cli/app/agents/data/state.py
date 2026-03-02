"""Data agent state definition."""
from typing import TypedDict, Sequence
from langchain_core.messages import BaseMessage


class DataAgentState(TypedDict):
    """State for the data analysis agent."""
    messages: Sequence[BaseMessage]
    next: str
    data_context: str  # Store loaded data info