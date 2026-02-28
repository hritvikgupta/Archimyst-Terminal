"""Vector store service layer for ArchCode terminal search."""

from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models


class QdrantCodeVectorStoreService:
    """Handles local Qdrant persistence and semantic search."""

    def __init__(
        self,
        storage_path: str = "./qdrant_storage",
        collection_name: str = "archcode",
    ):
        self.collection_name = collection_name
        self.client = QdrantClient(path=storage_path)

    def create_collection(self, vector_size: int = 1024):
        """Create collection if it does not exist."""
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="file_path",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="language",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

    def upsert_code_chunks(self, chunks: List[Dict[str, Any]]):
        """Upsert code chunks and vectors into Qdrant."""
        points = [
            models.PointStruct(
                id=chunk["id"],
                vector=chunk["vector"],
                payload=chunk["payload"],
            )
            for chunk in chunks
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform semantic search with optional metadata filtering."""
        query_filter = None
        if filters:
            must_filters = []
            for key, value in filters.items():
                must_filters.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    )
                )
            query_filter = models.Filter(must=must_filters)

        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=query_filter,
        )

        return [
            {
                "score": hit.score,
                "content": hit.payload.get("content"),
                "file_path": hit.payload.get("file_path"),
                "start_line": hit.payload.get("start_line"),
                "end_line": hit.payload.get("end_line"),
                "symbol_name": hit.payload.get("symbol_name"),
            }
            for hit in results
        ]


# Backward-compatible alias
CodeVectorStore = QdrantCodeVectorStoreService


__all__ = ["QdrantCodeVectorStoreService", "CodeVectorStore"]
