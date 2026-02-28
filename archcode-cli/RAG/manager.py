import os
from typing import List, Dict, Any, Set
from .indexer import MerkleIndexer
from .parser import ASTParser
from .embedder import Embedder
from .store import VectorStore
from .search import SearchEngine

class RAGManager:
    """The central hub for the RAG system, coordinating all sub-components."""
    
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.indexer = MerkleIndexer()
        self.parser = ASTParser()
        self.embedder = Embedder()
        self.store = VectorStore()
        self.search_engine = SearchEngine(self.store, self.embedder)

        # ✅ Index "everything that is code/config/docs" (you can expand anytime)
        # Avoid binaries by excluding common binary formats here.
        self.supported_extensions = {
            # code
            ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".cpp", ".c", ".h",
            ".cs", ".php", ".rb", ".swift", ".kt", ".scala", ".sh", ".bash", ".zsh", ".ps1",
            # web
            ".css", ".scss", ".sass", ".less", ".html",
            # config/data
            ".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".cfg", ".conf",
            ".xml", ".proto",
            # docs
            ".md", ".mdx", ".txt", ".rst",
            # infra
            ".tf", ".tfvars", ".dockerfile", ".sql"
        }

    def sync_codebase(self, console=None):
        """Indexes the codebase, parses new/modified files, and updates the vector store."""
        changes = self.indexer.get_changed_files(self.root_dir, self.supported_extensions)
        total = len(changes)
        
        if total == 0:
            return

        if console:
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
            if total > 5:
                # Large sync -> 0 to 100% progress bar
                with Progress(
                    SpinnerColumn(spinner_name="dots", style="#ff8888"),
                    TextColumn("[bold #ff8888]Syncing RAG Index ({task.completed}/{task.total})[/bold #ff8888]"),
                    BarColumn(bar_width=40, style="dim", complete_style="#ff8888"),
                    TaskProgressColumn(),
                    console=console,
                    transient=True,
                ) as progress:
                    task = progress.add_task("indexing", total=total)
                    for rel_path, status in changes.items():
                        self._process_file(rel_path, status)
                        progress.advance(task)
            else:
                # Small sync -> silent spinner
                with console.status(
                    f"[bold #ff8888]●[/bold #ff8888] Syncing {total} file(s)...",
                    spinner="dots",
                    spinner_style="#ff8888",
                ):
                    for rel_path, status in changes.items():
                        self._process_file(rel_path, status)
        else:
            for rel_path, status in changes.items():
                self._process_file(rel_path, status)
        
        self.indexer.save_state()

    def _process_file(self, rel_path: str, status: str):
        full_path = os.path.join(self.root_dir, rel_path)
        
        if status == "deleted":
            self.store.delete_file_chunks(rel_path)
            return
        
        if status in ("added", "modified"):
            if status == "modified":
                self.store.delete_file_chunks(rel_path)
            
            chunks = self.parser.parse_file(full_path)
            if not chunks:
                return
            
            # 1. Update chunks with the RELATIVE path so the tags are clean
            for c in chunks:
                c.file_path = rel_path
            
            # 2. Convert to dictionaries (this generates the [FILE:...] tagged content)
            chunk_dicts = [c.to_dict() for c in chunks]
            
            # 3. Embed the TAGGED content (the 'content' key in the dict)
            # This allows OpenAI to "see" filenames and languages during vector search
            chunk_texts_for_embedding = [d["content"] for d in chunk_dicts]
            embeddings = self.embedder.embed_chunks(chunk_texts_for_embedding)
                
            # 4. Add to store
            self.store.add_chunks(chunk_dicts, embeddings)

    def query(self, user_query: str, limit: int = 5) -> str:
        """Helper to get context for a specific user query."""
        return self.search_engine.get_context_for_query(user_query, limit)

