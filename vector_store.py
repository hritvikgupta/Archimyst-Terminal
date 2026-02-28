"""Backward-compatible vector store module.

This module preserves historical imports while delegating implementation
into the class-based core service layer.
"""

from core.search.vector_store_service import (
    CodeVectorStore,
    QdrantCodeVectorStoreService,
)


__all__ = ["CodeVectorStore", "QdrantCodeVectorStoreService"]


if __name__ == "__main__":
    store = CodeVectorStore()
    store.create_collection()
    print(f"Collection '{store.collection_name}' ready in local mode.")
