"""LangGraph state definition for the ArchCode CLI agent."""

import operator
from typing import Annotated, List, Sequence, TypedDict

from langchain_core.messages import BaseMessage


def merge_usage(a: dict, b: dict) -> dict:
    """Robustly merge token usage dicts, handling nested structures."""
    if not a:
        return b or {}
    if not b:
        return a or {}
    res = a.copy()
    for k, v in b.items():
        if isinstance(v, (int, float)):
            res[k] = res.get(k, 0) + v
        elif isinstance(v, dict):
            res[k] = merge_usage(res.get(k, {}), v)
    return res


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next: str
    token_usage: Annotated[dict, merge_usage]
    active_skills: Annotated[List[str], operator.add]
    skills_read: Annotated[List[str], operator.add]
