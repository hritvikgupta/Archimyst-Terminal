"""
History Manager — Pure File Snapshot System
Saves copies of affected files BEFORE each AI change so that
/rewind can restore them. No git involved at all.
"""

import os
import json
import uuid
import shutil
import difflib
import threading
from pathlib import Path
from datetime import datetime

# Module-level lock shared by ALL HistoryManager instances so that
# concurrent writes to the same index.json don't clobber each other.
_index_lock = threading.Lock()


class HistoryManager:
    """Manages file-level snapshots for undo/rewind functionality.
    
    Saves copies of affected files BEFORE each AI change so that
    /rewind can restore them without touching git at all.
    """

    def __init__(self, root_path):
        self.root = Path(root_path)
        self.history_dir = self.root / ".archcode" / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.history_dir / "index.json"
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.history = self._load_history()

    def _load_history(self):
        if self.index_file.exists():
            try:
                with open(self.index_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_history(self):
        """Thread-safe save using merge-on-save to avoid clobbering."""
        with _index_lock:
            # Re-load the current state from disk (another thread may have written)
            current = self._load_history()
            # Keep entries from OTHER sessions, replace ours
            other_entries = [e for e in current if e["session_id"] != self.session_id]
            my_entries = [e for e in self.history if e["session_id"] == self.session_id]
            merged = other_entries + my_entries
            merged.sort(key=lambda e: e["id"])
            with open(self.index_file, 'w') as f:
                json.dump(merged, f, indent=2)

    def create_checkpoint(self, user_msg, affected_files, is_initial=False):
        """Create a file-level snapshot checkpoint.
        
        Copies the CURRENT state of affected_files into a snapshot directory
        so we can restore them later if the user wants to revert.
        """
        timestamp = datetime.now().isoformat()
        checkpoint_id = len(self.history) + 1
        
        snapshot_dir = self.history_dir / self.session_id / str(checkpoint_id)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        stats = {"added": 0, "removed": 0}
        files_saved = []
        
        for f in affected_files:
            # Ensure f is relative to the root for snapshot path joining
            try:
                # If f is absolute, make it relative to root. If already relative, this is fine.
                rel_f = os.path.relpath(f, self.root)
            except ValueError:
                # In case f is on a different drive or something unexpected, just use basename
                rel_f = os.path.basename(f)

            file_path = self.root / rel_f
            if file_path.exists():
                # Save a copy of the file BEFORE the AI changes it
                dest = snapshot_dir / rel_f
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest)
                files_saved.append(str(rel_f))
                
                # Calculate simple line stats
                try:
                    content = file_path.read_text(errors='replace')
                    line_count = len(content.splitlines())
                    stats["added"] += line_count
                except Exception:
                    pass
            else:
                # File doesn't exist yet — mark it so revert knows to delete it
                marker = snapshot_dir / f"{rel_f}.NEW_FILE_MARKER"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("This file did not exist before the AI created it.")
                files_saved.append(str(rel_f))
        
        entry = {
            "id": checkpoint_id,
            "session_id": self.session_id,
            "timestamp": timestamp,
            "user_msg": user_msg,
            "type": "snapshot",
            "snapshot_path": str(snapshot_dir.relative_to(self.root)),
            "files": files_saved,
            "stats": stats,
            "is_initial": is_initial
        }
        
        self.history.append(entry)
        self._save_history()
        return entry

    def get_session_history(self):
        return [e for e in self.history if e["session_id"] == self.session_id]

    def get_all_history(self):
        return self.history

    def _restore_snapshot(self, entry):
        """Restore files from a single checkpoint's snapshot."""
        snapshot_path = self.root / entry.get("snapshot_path", "")
        if not snapshot_path.exists():
            return [], []

        restored_files = []
        deleted_files = []

        for root_dir, dirs, files in os.walk(snapshot_path):
            for name in files:
                src = Path(root_dir) / name

                if name.endswith(".NEW_FILE_MARKER"):
                    original_name = name.replace(".NEW_FILE_MARKER", "")
                    target = self.root / src.relative_to(snapshot_path).parent / original_name
                    if target.exists():
                        target.unlink()
                        deleted_files.append(str(target.relative_to(self.root)))
                    continue

                rel = src.relative_to(snapshot_path)
                dest = self.root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                restored_files.append(str(rel))

        return restored_files, deleted_files

    def revert_to(self, checkpoint_id):
        """Revert ALL changes from checkpoint_id onwards.
        
        Walks backwards from newest to the target, restoring each
        checkpoint's snapshot. So if you select [4], it also undoes [5], [6], etc.
        """
        entry = next((e for e in self.history if e["id"] == checkpoint_id), None)
        if not entry:
            return False, "Checkpoint not found"

        # Undo all checkpoints >= target, newest first
        to_undo = sorted(
            [e for e in self.history if e["id"] >= checkpoint_id],
            key=lambda e: e["id"],
            reverse=True
        )

        all_restored = []
        all_deleted = []

        for undo_entry in to_undo:
            restored, deleted = self._restore_snapshot(undo_entry)
            all_restored.extend(restored)
            all_deleted.extend(deleted)

        # Deduplicate
        all_restored = list(dict.fromkeys(all_restored))
        all_deleted = list(dict.fromkeys(all_deleted))

        # Trim history: remove target and everything after
        self.history = [e for e in self.history if e["id"] < checkpoint_id]
        self._save_history()

        parts = []
        if all_restored:
            parts.append(f"Restored {len(all_restored)} file(s): {', '.join(all_restored)}")
        if all_deleted:
            parts.append(f"Deleted {len(all_deleted)} AI-created file(s): {', '.join(all_deleted)}")

        if not parts:
            return True, f"Checkpoint {checkpoint_id} had no files to restore"

        return True, " | ".join(parts)

    def get_diff_for_checkpoint(self, checkpoint_id):
        """Get a diff between the checkpoint snapshot and current files.
        
        Returns a list of dicts with 'file', 'diff_lines', and 'status'.
        Used by the interactive rewind selector to preview changes.
        """
        entry = next((e for e in self.history if e["id"] == checkpoint_id), None)
        if not entry:
            return []

        snapshot_path = self.root / entry.get("snapshot_path", "")
        if not snapshot_path.exists():
            return []

        diffs = []

        for root_dir, dirs, files in os.walk(snapshot_path):
            for name in files:
                src = Path(root_dir) / name
                
                if name.endswith(".NEW_FILE_MARKER"):
                    original_name = name.replace(".NEW_FILE_MARKER", "")
                    rel = src.relative_to(snapshot_path).parent / original_name
                    diffs.append({
                        "file": str(rel),
                        "status": "created_by_ai",
                        "diff_lines": ["(This file was created by the AI and will be deleted on revert)"]
                    })
                    continue
                
                rel = src.relative_to(snapshot_path)
                current_file = self.root / rel
                
                try:
                    snapshot_content = src.read_text(errors='replace').splitlines()
                except Exception:
                    snapshot_content = ["<binary file>"]
                
                if current_file.exists():
                    try:
                        current_content = current_file.read_text(errors='replace').splitlines()
                    except Exception:
                        current_content = ["<binary file>"]
                    
                    diff = list(difflib.unified_diff(
                        current_content, snapshot_content,
                        fromfile=f"current: {rel}",
                        tofile=f"revert to: {rel}",
                        lineterm=""
                    ))
                    
                    if diff:
                        diffs.append({
                            "file": str(rel),
                            "status": "modified",
                            "diff_lines": diff
                        })
                    # else: no changes, skip
                else:
                    diffs.append({
                        "file": str(rel),
                        "status": "deleted",
                        "diff_lines": [f"(File was deleted — snapshot has {len(snapshot_content)} lines to restore)"]
                    })

        return diffs
