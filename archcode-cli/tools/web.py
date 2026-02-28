"""Web search tool wrapper with LangChain @tool decorator."""

from langchain_core.tools import tool

from tools.services.web_service import WebSearchService

_web_service = WebSearchService()


@tool
def search_web(query: str) -> str:
    """Search the web for up-to-date information, documentation, or answers not present in the codebase."""
    return _web_service.search_web(query)


__all__ = ["search_web", "WebSearchService"]
