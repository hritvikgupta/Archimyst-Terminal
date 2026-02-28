"""Top-level engine orchestration service for indexing and search."""

import os
import uuid
from typing import Any, Dict, List, Optional

from .embedding_service import VoyageEmbeddingService
from .parser_service import TreeSitterCodeParserService
from .vector_store_service import QdrantCodeVectorStoreService


class ArchCodeSearchEngineService:
    """Main orchestrator for the ArchCode terminal indexing platform."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        storage_path: str = "./qdrant_storage",
    ):
        self.embeddings = VoyageEmbeddingService(api_key=api_key)
        self.vector_store = QdrantCodeVectorStoreService(storage_path=storage_path)
        self.parser = TreeSitterCodeParserService()
        self.vector_store.create_collection()

    def index_directory(
        self,
        root_dir: str,
        include_extensions: List[str] = None,
    ):
        """Recursively index all relevant files in a directory."""
        if include_extensions is None:
            include_extensions = [".py", ".ts", ".js", ".tsx"]

        print(f"Indexing directory: {root_dir}")
        all_chunks: List[Dict[str, Any]] = []

        for root, _, files in os.walk(root_dir):
            if any(part.startswith(".") for part in root.split(os.sep)):
                continue

            for file in files:
                if any(file.endswith(ext) for ext in include_extensions):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, root_dir)

                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                        file_chunks = self.parser.chunk_file(content, file_path)
                        print(f"  Parsed {rel_path}: {len(file_chunks)} symbols found.")

                        chunk_texts = [c["content"] for c in file_chunks]
                        if not chunk_texts:
                            continue

                        vectors = self.embeddings.embed_code(chunk_texts)

                        for chunk, vector in zip(file_chunks, vectors):
                            all_chunks.append(
                                {
                                    "id": str(uuid.uuid4()),
                                    "vector": vector,
                                    "payload": {
                                        "content": chunk["content"],
                                        "file_path": rel_path,
                                        "start_line": chunk["start_line"],
                                        "end_line": chunk["end_line"],
                                        "symbol_name": chunk["name"],
                                        "language": chunk["language"],
                                    },
                                }
                            )

                    except Exception as e:
                        print(f"  Error indexing {rel_path}: {e}")

        if all_chunks:
            print(f"Uploading {len(all_chunks)} chunks to Qdrant...")
            self.vector_store.upsert_code_chunks(all_chunks)
            print("Indexing complete.")
        else:
            print("No suitable files found to index.")

    def search(self, query: str, limit: int = 5):
        """Search for code snippets matching a query."""
        query_vector = self.embeddings.embed_query(query)
        return self.vector_store.search(query_vector, limit=limit)


# Backward-compatible alias
ArchCodeEngine = ArchCodeSearchEngineService


__all__ = ["ArchCodeSearchEngineService", "ArchCodeEngine"]
