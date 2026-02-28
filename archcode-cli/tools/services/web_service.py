"""Web tool service implementation."""

import json
import urllib.request

from config import config


class WebSearchService:
    """Service for Tavily-based web search."""

    def search_web(self, query: str) -> str:
        api_key = config.tavily_api_key
        if not api_key:
            return "Error: TAVILY_API_KEY not configured. Set it in your .env file."

        try:
            data = json.dumps(
                {
                    "api_key": api_key,
                    "query": query,
                    "num_results": 5,
                }
            ).encode("utf-8")

            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=data,
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                results = json.loads(resp.read().decode("utf-8"))

            formatted = []
            for res in results.get("results", []):
                formatted.append(
                    f"Title: {res.get('title', 'N/A')}\n"
                    f"Link: {res.get('url', 'N/A')}\n"
                    f"Snippet: {res.get('content', res.get('snippet', 'N/A'))}\n"
                )
            return "\n".join(formatted) if formatted else "No results found."
        except Exception as e:
            return f"Error searching web: {str(e)}"


__all__ = ["WebSearchService"]
