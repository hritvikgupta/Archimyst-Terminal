"""
File Lock Registry — Per-File Mutex for Background Tasks

Prevents two tasks (or a foreground + background task) from editing the
same file at the same time.  Read operations are NOT locked — only
mutation tools (write, edit, delete, whole_file_update) acquire locks.
"""

import os
import threading
from typing import Dict, Optional, Set, Tuple


class FileLockRegistry:
    """Singleton registry that tracks which task owns each file."""

    def __init__(self):
        self._lock = threading.Lock()
        self._file_locks: Dict[str, str] = {}       # abs_path → task_id
        self._task_files: Dict[str, Set[str]] = {}   # task_id → set of abs_paths

    def acquire(self, file_path: str, task_id: str) -> Tuple[bool, Optional[str]]:
        """Try to lock *file_path* for *task_id*.

        Returns (True, None)          on success (including idempotent re-acquire).
        Returns (False, holder_id)    when the file is held by a different task.
        """
        abs_path = os.path.abspath(os.path.normpath(file_path))
        with self._lock:
            holder = self._file_locks.get(abs_path)
            if holder is not None and holder != task_id:
                return False, holder

            self._file_locks[abs_path] = task_id
            self._task_files.setdefault(task_id, set()).add(abs_path)
            return True, None

    def release_all(self, task_id: str) -> int:
        """Release every lock held by *task_id*.  Returns number released."""
        with self._lock:
            paths = self._task_files.pop(task_id, set())
            for p in paths:
                self._file_locks.pop(p, None)
            return len(paths)

    def get_locks_for_task(self, task_id: str) -> Set[str]:
        """Return the set of absolute paths currently locked by *task_id*."""
        with self._lock:
            return set(self._task_files.get(task_id, set()))


# Module-level singleton
_registry = FileLockRegistry()


def get_file_lock_registry() -> FileLockRegistry:
    return _registry
