from typing import List, Dict, Any, Optional
import re
from .store import VectorStore
from .embedder import Embedder

class SearchEngine:
    """Orchestrates hybrid search combining semantic and keyword results with metadata awareness."""
    
    def __init__(self, store: VectorStore, embedder: Embedder):
        self.store = store
        self.embedder = embedder

    def _extract_language_hint(self, query: str) -> tuple[str, Optional[str]]:
        """Extract language filter hints from query without stripping words."""
        language_keywords = {
            'python': ['python', 'py'],
            'typescript': ['typescript', 'ts', 'tsx'],
            'javascript': ['javascript', 'js', 'jsx'],
            'java': ['java'],
            'go': ['go', 'golang'],
            'rust': ['rust', 'rs'],
            'cpp': ['cpp', 'c++'],
            'sql': ['sql'],
        }
        
        query_lower = query.lower()
        detected_lang = None
        for lang, keywords in language_keywords.items():
            if any(kw in query_lower for kw in keywords):
                detected_lang = lang
                break
        
        return query, detected_lang
    def search(
        self, 
        query: str, 
        limit: int = 5,
        file_extension: Optional[str] = None,
        language: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Performs semantic search with soft-boost reranking for code structures."""
        # 1. Detect language but keep query intact for OpenAI
        _, detected_lang = self._extract_language_hint(query)
        language = language or detected_lang
        
        # 2. Generate embedding
        query_embedding = self.embedder.embed_query(query)
        
        # 3. Retrieve more results than needed for reranking
        results = self.store.search(query_embedding, n_results=limit * 4)
        
        filtered_results = []
        for res in results:
            meta = res.get('metadata', {})
            distance = res.get('distance', 1.0) 
            
            # Metadata filtering: Language
            if language:
                result_lang = (meta.get('language') or "").lower()
                result_ext = (meta.get('ext') or "").lower()
                lang_match = (
                    result_lang == language or
                    (language == 'python' and result_ext == '.py') or
                    (language == 'typescript' and result_ext in ['.ts', '.tsx']) or
                    (language == 'javascript' and result_ext in ['.js', '.jsx'])
                )
                if not lang_match:
                    continue
            
            # Metadata filtering: Extension
            if file_extension and meta.get('ext', '').lower() != file_extension.lower():
                continue
            
            # 🚀 SOFT BOOSTING: Give symbols a 20% relevance "nudge"
            boosted_distance = distance
            if meta.get('type') in ['function', 'class', 'method', 'symbol', 'class_definition', 'function_definition']:
                boosted_distance *= 0.8  # Lower distance = Higher relevance
            
            res['_boosted_distance'] = boosted_distance
            filtered_results.append(res)
        
        # Sort by weighted distance
        filtered_results.sort(key=lambda x: x['_boosted_distance'])
        
        return filtered_results[:limit]

    def search_with_context(
        self, 
        query: str, 
        limit: int = 5,
        include_surrounding: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Search and optionally include surrounding context for each result.
        """
        results = self.search(query, limit=limit)
        
        if not include_surrounding:
            return results
        
        # Enhance results with related symbols from same file/scope
        enhanced = []
        for res in results:
            enhanced.append(res)
            
            # Find related chunks (same file, nearby lines or same scope)
            meta = res.get('metadata', {})
            # This could query the store for related items, but requires store enhancements
            # For now, just return the main results
            
        return results

    def get_context_for_query(self, query: str, limit: int = 3) -> str:
        """Helper to format search results as a prompt-friendly context string."""
        limit = max(10, limit)
        results = self.search(query, limit=limit)
        # print(results)
        if not results:
            return f"// No results found for: {query}\n"
        
        context_parts = []
        for i, res in enumerate(results, 1):
            meta = res.get('metadata', {})
            content = res.get('content', '')
            
            scope = meta.get('scope', '')
            scope_info = f" | Scope: {scope}" if scope else ""
            type_info = f" ({meta.get('type', 'code')})"
            
            header = f"[{i}] {meta.get('file_path', 'unknown')} | Lines {meta.get('start_line', 0)}-{meta.get('end_line', 0)}{type_info}{scope_info}"
            
            # ✅ Clean up the [FILE:...] tags added by the parser
            content_lines = content.split('\n')
            if content_lines and (content_lines[0].startswith('[FILE:') or content_lines[0].startswith('//')):
                content = '\n'.join(content_lines[1:])
            
            context_parts.append(f"{'='*60}\n{header}\n{'='*60}\n{content.strip()}\n")
            
        return "\n".join(context_parts)

    def explain_results(self, query: str, results: List[Dict[str, Any]]) -> str:
        """Provide a human-readable explanation of why these results were chosen."""
        if not results:
            return f"No code found matching '{query}'. Try:\n- Using more specific function/class names\n- Adding language hints (e.g., 'python function', 'typescript interface')\n- Checking if the codebase is indexed"
        
        lines = [f"Found {len(results)} relevant code snippet(s) for '{query}':\n"]
        
        for res in results:
            meta = res.get('metadata', {})
            chunk_type = meta.get('type', 'unknown')
            
            type_description = {
                'function': 'Function implementation',
                'class': 'Class definition',
                'method': 'Class method',
                'symbol': 'Exported symbol',
                'module': 'Module/file level code',
            }.get(chunk_type, f'{chunk_type} block')
            
            lines.append(f"- {meta.get('file_path', 'unknown')} ({type_description})")
        
        return '\n'.join(lines)