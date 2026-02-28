import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional

class VectorStore:
    """Manages local vector storage using ChromaDB."""
    
    def __init__(self, persist_directory: str = ".archcode/chroma_db"):
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)
        
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False)
        )
        self._get_collection()

    def _get_collection(self):
        self.collection = self.client.get_or_create_collection(name="code_chunks")

    def add_chunks(self, chunks: List[Dict[str, Any]], embeddings: List[List[float]]):
        import hashlib

        # 1) Deduplicate identical (file_path, type, start, end, content) within the batch
        seen = set()
        dedup_chunks = []
        dedup_embeddings = []

        for c, emb in zip(chunks, embeddings):
            meta = c["metadata"]
            key = (
                meta.get("file_path"),
                meta.get("type"),
                meta.get("start_line"),
                meta.get("end_line"),
                c["content"],
            )
            if key in seen:
                continue
            seen.add(key)
            dedup_chunks.append(c)
            dedup_embeddings.append(emb)

        chunks = dedup_chunks
        embeddings = dedup_embeddings

        # 2) Create IDs that are unique even if content repeats
        ids = []
        id_counts = {}  # base_id -> count

        for c in chunks:
            meta = c["metadata"]
            fp = meta["file_path"]
            s = meta.get("start_line", 0)
            e = meta.get("end_line", 0)
            t = meta.get("type", "chunk")

            h = hashlib.sha1(c["content"].encode("utf-8", errors="ignore")).hexdigest()[:10]
            base_id = f"{fp}_{t}_{s}_{e}_{h}"

            n = id_counts.get(base_id, 0)
            id_counts[base_id] = n + 1

            # If duplicate base_id occurs, suffix it
            ids.append(base_id if n == 0 else f"{base_id}_{n}")

        documents = [c["content"] for c in chunks]

        # 3) Clean metadatas (Chroma needs primitives)
        metadatas = []
        for c in chunks:
            clean_meta = {}
            for k, v in c["metadata"].items():
                if v is not None and isinstance(v, (str, int, float, bool)):
                    clean_meta[k] = v
            metadatas.append(clean_meta)

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

    def delete_file_chunks(self, file_path: str):
        """Removes all chunks associated with a specific file."""
        self.collection.delete(where={"file_path": file_path})

    def search(self, query_embedding: List[float], n_results: int = 5) -> List[Dict[str, Any]]:
        n_results = max(10, n_results)
        """Performs a similarity search."""
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        formatted_results = []
        if results['documents']:
            for i in range(len(results['documents'][0])):
                formatted_results.append({
                    "content": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "id": results['ids'][0][i],
                    "distance": results['distances'][0][i]
                })
        return formatted_results
