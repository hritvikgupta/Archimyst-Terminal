"""Backward-compatible embeddings module.

This module preserves historical imports while delegating implementation
into the class-based core service layer.
"""

from core.search.embedding_service import VoyageEmbeddingService, VoyageIndexer


__all__ = ["VoyageEmbeddingService", "VoyageIndexer"]


if __name__ == "__main__":
    try:
        indexer = VoyageIndexer()
        test_code = "def hello_world(): print('Hello, world!')"
        embedding = indexer.embed_code([test_code])
        print(f"Embedding length: {len(embedding[0])}")
    except Exception as e:
        print(f"Error (likely missing API key): {e}")
