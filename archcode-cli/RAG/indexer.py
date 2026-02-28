import os
import hashlib
import json
import pathspec
from typing import Dict, Set, Optional

class MerkleIndexer:
    """Uses Merkle Trees (Hashes) to track file changes, respecting .gitignore."""
    
    def __init__(self, state_file: str = ".archcode/rag_state.json"):
        self.state_file = state_file
        self.file_hashes: Dict[str, str] = {}
        self.gitignore: Optional[pathspec.PathSpec] = None
        self.load_state()

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    self.file_hashes = json.load(f)
            except Exception:
                self.file_hashes = {}
        
    def _load_gitignore(self, root_dir: str):
        gitignore_path = os.path.join(root_dir, ".gitignore")
        patterns = []
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r') as f:
                patterns = f.read().splitlines()
        
        # Always ignore common artifacts even if .gitignore is missing
        patterns.extend(['node_modules/', '.git/', '__pycache__/', '.venv/', 'venv/'])
        self.gitignore = pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, patterns)

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(self.file_hashes, f, indent=2)

    def compute_hash(self, file_path: str) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    def get_changed_files(self, root_dir: str, extensions: Set[str]) -> Dict[str, str]:
        if self.gitignore is None:
            self._load_gitignore(root_dir)
            
        changes = {}
        current_files = set()

        for root, dirs, files in os.walk(root_dir):
            # Apply gitignore to directories to prune early
            rel_root = os.path.relpath(root, root_dir)
            if rel_root == ".":
                rel_root = ""
            
            # Prune directories (append / for correct gitignore directory matching)
            dirs[:] = [d for d in dirs if not self.gitignore.match_file(os.path.join(rel_root, d) + '/')]

            for file in files:
                rel_path = os.path.join(rel_root, file)
                if self.gitignore.match_file(rel_path):
                    continue
                
                if os.path.splitext(file)[1] in extensions:
                    full_path = os.path.join(root, file)
                    current_files.add(rel_path)
                    
                    new_hash = self.compute_hash(full_path)
                    old_hash = self.file_hashes.get(rel_path)

                    if not old_hash:
                        changes[rel_path] = "added"
                    elif old_hash != new_hash:
                        changes[rel_path] = "modified"
                    
                    self.file_hashes[rel_path] = new_hash

        deleted = set(self.file_hashes.keys()) - current_files
        for rel_path in deleted:
            changes[rel_path] = "deleted"
            del self.file_hashes[rel_path]

        return changes
