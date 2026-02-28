"""
Task Context — Thread-Local Task Identity

Uses threading.local() so tool functions can discover which task they
belong to without changing their signatures (the LLM calls them — we
can't add a task_id param).

Foreground thread : task_id = "foreground", global DiffManager/HistoryManager
Background threads: task_id = UUID,         per-task DiffManager/HistoryManager
"""

import threading

_ctx = threading.local()


def set_task_context(task_id, diff_manager, history_manager, cancel_event=None):
    """Set the task context for the current thread."""
    _ctx.task_id = task_id
    _ctx.diff_manager = diff_manager
    _ctx.history_manager = history_manager
    _ctx.cancel_event = cancel_event


def clear_task_context():
    """Clear the task context for the current thread."""
    _ctx.task_id = None
    _ctx.diff_manager = None
    _ctx.history_manager = None
    _ctx.cancel_event = None


def get_current_task_id():
    """Return the task_id for the current thread, or 'foreground' if unset."""
    return getattr(_ctx, "task_id", None) or "foreground"


def get_current_diff_manager():
    """Return the DiffManager for the current thread.

    Falls back to the global singleton when no context is set (e.g. during
    startup before the foreground context is initialised).
    """
    dm = getattr(_ctx, "diff_manager", None)
    if dm is not None:
        return dm
    from diff_manager import get_diff_manager
    return get_diff_manager()


def get_current_history_manager():
    """Return the HistoryManager for the current thread.

    Falls back to the global singleton when no context is set.
    """
    hm = getattr(_ctx, "history_manager", None)
    if hm is not None:
        return hm
    from tools.filesystem import get_history_manager
    return get_history_manager()


def is_cancellation_requested():
    """Check whether the current background task has been cancelled."""
    evt = getattr(_ctx, "cancel_event", None)
    if evt is None:
        return False
    return evt.is_set()
