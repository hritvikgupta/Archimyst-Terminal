"""
Background Task Manager — Task Lifecycle for /task Commands

Each background task runs agent.run() in its own daemon thread with:
- Its own Agno Agent instance
- Its own DiffManager instance
- Its own HistoryManager instance (per-task rewind)
- A cancel_event for cooperative cancellation
- A StringIO log_buffer for captured output
"""

import io
import os
import uuid
import threading
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from diff_manager import DiffManager
from history import HistoryManager
from task_context import set_task_context, clear_task_context, is_cancellation_requested
from file_lock_registry import get_file_lock_registry


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    task_id: str
    display_id: int
    query: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    thread: Optional[threading.Thread] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    log_buffer: io.StringIO = field(default_factory=io.StringIO)
    final_response: str = ""
    error_message: str = ""
    changed_files: List[str] = field(default_factory=list)
    token_usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    history_manager: Optional[HistoryManager] = None
    diff_manager: Optional[DiffManager] = None
    session_id: str = ""


class BackgroundTaskManager:
    """Manages background task lifecycle."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[int, BackgroundTask] = {}  # display_id → BackgroundTask
        self._next_id = 1
        self._completed_queue: List[int] = []  # display_ids of newly completed tasks

    def submit_task(self, query: str) -> Tuple[int, str]:
        """Submit a new background task. Returns (display_id, task_id)."""
        task_id = uuid.uuid4().hex[:12]

        with self._lock:
            display_id = self._next_id
            self._next_id += 1

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"task{display_id}_{timestamp}_{uuid.uuid4().hex[:6]}"

        task = BackgroundTask(
            task_id=task_id,
            display_id=display_id,
            query=query,
            session_id=session_id,
        )

        thread = threading.Thread(
            target=self._run_task,
            args=(task,),
            name=f"bg-task-{display_id}",
            daemon=True,
        )
        task.thread = thread

        with self._lock:
            self._tasks[display_id] = task

        thread.start()
        return display_id, task_id

    def cancel_task(self, display_id: int) -> Tuple[bool, str]:
        """Request cancellation of a running task."""
        with self._lock:
            task = self._tasks.get(display_id)
        if task is None:
            return False, f"Task #{display_id} not found."
        if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return False, f"Task #{display_id} is already {task.status.value}."
        task.cancel_event.set()
        return True, f"Cancellation requested for task #{display_id}."

    def get_task(self, display_id: int) -> Optional[BackgroundTask]:
        with self._lock:
            return self._tasks.get(display_id)

    def get_all_tasks(self) -> List[Tuple[int, BackgroundTask]]:
        with self._lock:
            return sorted(self._tasks.items())

    def drain_completed(self) -> List[BackgroundTask]:
        """Return and clear newly completed tasks for notification."""
        with self._lock:
            ids = list(self._completed_queue)
            self._completed_queue.clear()
        return [self._tasks[did] for did in ids if did in self._tasks]

    # ------------------------------------------------------------------ #
    #  Thread target
    # ------------------------------------------------------------------ #

    def _run_task(self, task: BackgroundTask):
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        # Per-task instances
        task_dm = DiffManager()
        task_dm.begin_tracking()
        task.diff_manager = task_dm

        task_hm = HistoryManager(os.getcwd())
        task_hm.session_id = task.session_id  # override with our scoped id
        task.history_manager = task_hm

        set_task_context(task.task_id, task_dm, task_hm, task.cancel_event)

        try:
            from agent_agno import create_agent

            agent = create_agent(session_id=task.session_id)
            self._log(task, f"[task #{task.display_id}] Starting: {task.query}")

            if task.cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                self._log(task, "[cancelled by user]")
                return

            # Run the agent (blocking, non-streaming for background tasks)
            run_output = agent.run(task.query)

            # Extract final response
            if run_output and hasattr(run_output, 'content'):
                task.final_response = run_output.content or ""
                self._log(task, f"[completed] {task.final_response[:200]}")

            # Extract metrics (token usage)
            if run_output and hasattr(run_output, 'metrics') and run_output.metrics:
                metrics = run_output.metrics
                if hasattr(metrics, 'input_tokens'):
                    task.token_usage["input_tokens"] = getattr(metrics, 'input_tokens', 0) or 0
                if hasattr(metrics, 'output_tokens'):
                    task.token_usage["output_tokens"] = getattr(metrics, 'output_tokens', 0) or 0
                if hasattr(metrics, 'total_tokens'):
                    task.token_usage["total_tokens"] = getattr(metrics, 'total_tokens', 0) or 0

            # Ensure total_tokens is set
            if task.token_usage.get("total_tokens", 0) == 0:
                task.token_usage["total_tokens"] = (
                    task.token_usage.get("input_tokens", 0)
                    + task.token_usage.get("output_tokens", 0)
                )

            task.status = TaskStatus.COMPLETED
            self._log(task, f"[completed] Changed files: {len(task_dm.get_changed_files())}")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            self._log(task, f"[error] {e}")
        finally:
            # Always release locks and record changed files
            get_file_lock_registry().release_all(task.task_id)
            if task.diff_manager:
                task.changed_files = [
                    os.path.relpath(f) for f in task.diff_manager.get_changed_files()
                ]
            task.completed_at = datetime.now()
            clear_task_context()

            with self._lock:
                self._completed_queue.append(task.display_id)

    def _log(self, task: BackgroundTask, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        task.log_buffer.write(f"[{ts}] {message}\n")


# Module-level singleton
_manager = BackgroundTaskManager()


def get_task_manager() -> BackgroundTaskManager:
    return _manager
