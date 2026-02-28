from langchain_core.tools import tool
from .manager import RAGManager
import os

# Create a singleton manager instance for the tool
# We use the current working directory as the repository root
_rag_manager = None

def get_rag_manager():
    global _rag_manager
    if _rag_manager is None:
        _rag_manager = RAGManager(os.getcwd())
    return _rag_manager

@tool
def search_codebase(query: str, limit: int = 5) -> str:
    """
    Search the codebase using a professional RAG system (Vector Search + Structural AST).
    
    This tool is superior to simple symbol search as it understands the semantics 
    of your query and retrieves complete logical blocks (functions, classes, components) 
    with their structural breadcrumbs.
    
    Use this to:
    - Locate specific functionality by description (e.g., "where is the auth logic?")
    - Find components by their visuals or behavior (e.g., "the frontend archcode file")
    - Understand how complex features are implemented across the codebase.

    Args:
        query: Semantic search query (e.g., "how are agents initialized?")
        limit: Number of relevant code chunks to retrieve (default: 5)
    """
    if not query or len(query.strip()) < 3:
        return (
            "ERROR: Search query is too short or empty. "
            "You must provide a specific semantic query (at least 3 characters). "
            "Example: 'auth logic' or 'landing page hero component'."
        )
    manager = get_rag_manager()
    # Ensure codebase is synced (Merkle Tree makes this extremely fast if no changes)
    manager.sync_codebase()
    
    # Perform search
    return manager.query(query, limit)
