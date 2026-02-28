from typing import List, Optional
import os
import chromadb.utils.embedding_functions as embedding_functions

class Embedder:
    """Generates embeddings for code chunks using OpenAI (cloud) or local ONNX fallback."""
    
    # 🚀 INCREASED from 3000 to 25000: OpenAI text-embedding-3-small supports 8192 tokens
    # (~32,000 characters). This ensures your full 160-line code chunks are NEVER cut off!
    MAX_CHARS = 25000
    
    def __init__(self):
        self.openai_api_key = "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"
        self.embedding_fn = None
        self.use_openai = False
        
        # Prefer OpenAI for top-tier code understanding if API key is available
        if self.openai_api_key:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=self.openai_api_key)
                self.use_openai = True
                print("✅ Using OpenAI 'text-embedding-3-small' for code embeddings")
            except ImportError:
                print("⚠️ 'openai' package not installed. Run 'pip install openai'. Falling back to local model.")
                self._init_local()
            except Exception as e:
                print(f"⚠️ OpenAI init failed: {e}, falling back to local model.")
                self._init_local()
        else:
            self._init_local()

    def _init_local(self):
        """Initialize local ONNX model as fallback (all-MiniLM-L6-v2)."""
        if not self.embedding_fn:
            self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
            print("✅ Using local all-MiniLM-L6-v2 embeddings (Set OPENAI_API_KEY for much better code context)")

    def embed_chunks(self, chunks: List[str]) -> List[List[float]]:
        """Embeds code chunks with truncation at semantic boundaries."""
        safe_chunks =[]
        for chunk in chunks:
            if not chunk or not chunk.strip():
                safe_chunks.append(" ")  # Avoid empty sequences
            elif len(chunk) > self.MAX_CHARS:
                # Truncate at a line boundary to preserve context if it's ridiculously huge
                truncated = self._smart_truncate(chunk, self.MAX_CHARS)
                safe_chunks.append(truncated)
            else:
                safe_chunks.append(chunk)

        if self.use_openai:
            return self._embed_openai(safe_chunks)
        else:
            return self._embed_local(safe_chunks)
    
    def _smart_truncate(self, text: str, max_chars: int) -> str:
        """Truncate at line boundary to avoid cutting mid-function."""
        if len(text) <= max_chars:
            return text
        
        # Find the last newline before max_chars
        truncate_at = text.rfind('\n', 0, max_chars)
        if truncate_at == -1:
            # No newline found, truncate at max_chars but add indicator
            return text[:max_chars] + "\n# ... [truncated]"
        
        return text[:truncate_at] + "\n# ... [truncated]"

    def _embed_openai(self, chunks: List[str]) -> List[List[float]]:
        """Embed using OpenAI's text-embedding-3-small."""
        # OpenAI handles large batches well (up to 2048 array size)
        BATCH_SIZE = 100 
        all_embeddings =[]
        
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            try:
                response = self.openai_client.embeddings.create(
                    input=batch,
                    model="text-embedding-3-small"
                )
                # Extract vectors from the response data
                batch_embeddings = [data.embedding for data in response.data]
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                print(f"⚠️ OpenAI embedding failed for batch {i}: {e}")
                # Fall back to local for this batch if API hits a rate limit or network error
                self._init_local()
                batch_embeddings = self.embedding_fn(batch)
                all_embeddings.extend(batch_embeddings)
        
        return all_embeddings

    def _embed_local(self, chunks: List[str]) -> List[List[float]]:
        """Embed using local ONNX model."""
        BATCH_SIZE = 100
        all_embeddings =[]
        
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            try:
                batch_embeddings = self.embedding_fn(batch)
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                print(f"⚠️ Local Embedding exception in batch {i}: {str(e)}")
                raise

        return all_embeddings
    
    def embed_query(self, query: str) -> List[float]:
        """Embeds a single query string for vector search."""
        if self.use_openai:
            try:
                response = self.openai_client.embeddings.create(
                    input=[query],
                    model="text-embedding-3-small"
                )
                return response.data[0].embedding
            except Exception as e:
                print(f"⚠️ OpenAI query embedding failed: {e}, using local fallback")
        
        self._init_local()
        return self.embedding_fn([query])[0]