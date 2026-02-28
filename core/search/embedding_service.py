"""Embeddings service layer for ArchCode terminal search."""

import os
from typing import List

import voyageai


class VoyageEmbeddingService:
    """Wrapper for Voyage AI embeddings specialized for code."""

    def __init__(self, api_key: str = None, model: str = "voyage-code-3"):
        self.api_key = api_key or os.getenv("VOYAGE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "VOYAGE_API_KEY must be set in environment or passed to constructor."
            )

        self.client = voyageai.Client(api_key=self.api_key)
        self.model = model

    def embed_code(self, code_snippets: List[str]) -> List[List[float]]:
        """Embed a list of code snippets."""
        result = self.client.embed(
            code_snippets,
            model=self.model,
            input_type="document",
        )
        return result.embeddings

    def embed_query(self, query: str) -> List[float]:
        """Embed a natural language query for code search."""
        result = self.client.embed(
            [query],
            model=self.model,
            input_type="query",
        )
        return result.embeddings[0]


# Backward-compatible alias
VoyageIndexer = VoyageEmbeddingService


__all__ = ["VoyageEmbeddingService", "VoyageIndexer"]
