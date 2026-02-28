"""
Plan File Manager — Persistent .archcode/archcode.md plan file.

Saves the accepted plan to disk so the AI can stay grounded during execution,
and updates task checkboxes as work progresses.
"""

import os
import re
from datetime import datetime
from typing import Optional


_PLAN_DIR = ".archcode"
_PLAN_FILE = os.path.join(_PLAN_DIR, "archcode.md")


def _plan_path() -> str:
    """Return the absolute path to the plan file in the current working directory."""
    return os.path.join(os.getcwd(), _PLAN_FILE)


def save_plan(plan_markdown: str) -> str:
    """Write the accepted plan to .archcode/archcode.md with a timestamp header.

    Returns the absolute path to the saved file.
    """
    path = _plan_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    header = (
        f"<!-- ArchCode Plan — saved {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -->\n"
        f"<!-- Status: IN_PROGRESS -->\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + plan_markdown)

    return path


def get_plan_context() -> Optional[str]:
    """Read the current plan file and return its contents for prompt injection.

    Returns None if no plan file exists.
    """
    path = _plan_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def update_plan_status(task_description: str, status: str = "done") -> None:
    """Mark a task in the plan file as done or failed.

    Finds unchecked checkboxes ``[ ]`` whose line contains *task_description*
    (case-insensitive substring match) and replaces them:
      - "done"   → ``[x]``
      - "failed" → ``[!]``
    """
    path = _plan_path()
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return

    marker = "[x]" if status == "done" else "[!]"
    needle = task_description.lower()

    lines = content.split("\n")
    changed = False
    for i, line in enumerate(lines):
        if "[ ]" in line and needle in line.lower():
            lines[i] = line.replace("[ ]", marker, 1)
            changed = True
            break  # one at a time

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


def update_file_status(file_path: str, status: str = "done") -> None:
    """Mark a file-related task in the plan as done/failed by matching the file path."""
    path = _plan_path()
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return

    # Extract just the filename for matching
    file_name = os.path.basename(file_path)
    marker = "[x]" if status == "done" else "[!]"

    lines = content.split("\n")
    changed = False
    for i, line in enumerate(lines):
        if "[ ]" in line and file_name in line:
            lines[i] = line.replace("[ ]", marker, 1)
            changed = True
            break

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


def mark_plan_complete() -> None:
    """Update the plan file header to mark the plan as COMPLETED."""
    path = _plan_path()
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return

    content = content.replace("<!-- Status: IN_PROGRESS -->", "<!-- Status: COMPLETED -->")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def clear_plan() -> None:
    """Remove the plan file."""
    path = _plan_path()
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
