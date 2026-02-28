"""
Plan Task Tracker — Live execution progress for approved plans.

Parses approved plans and displays a live task checklist that updates
as the AI executes each item.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


@dataclass
class PlanTask:
    """Single task item from a plan."""
    id: int
    description: str
    file_path: Optional[str] = None
    task_type: str = "modify"  # modify, new, verify, command
    status: TaskStatus = TaskStatus.PENDING
    line_info: Optional[str] = None


@dataclass
class PlanExecution:
    """Parsed plan with tasks ready for execution tracking."""
    goal: str = ""
    tasks: List[PlanTask] = field(default_factory=list)
    verification_steps: List[str] = field(default_factory=list)


class PlanTaskTracker:
    """
    Tracks and displays plan execution progress.
    
    Usage:
        tracker = PlanTaskTracker(console)
        execution = tracker.parse_plan(plan_markdown)
        
        # During execution loop:
        tracker.update_from_tool_call(tool_name, tool_args)
        tracker.render()  # or use live display
    """
    
    STATUS_ICONS = {
        TaskStatus.PENDING: "⏳",
        TaskStatus.IN_PROGRESS: "🔄",
        TaskStatus.DONE: "✅",
        TaskStatus.FAILED: "❌",
    }
    
    STATUS_COLORS = {
        TaskStatus.PENDING: "dim",
        TaskStatus.IN_PROGRESS: "bold #ff8888",
        TaskStatus.DONE: "bold green",
        TaskStatus.FAILED: "bold red",
    }
    
    def __init__(self, console: Console):
        self.console = console
        self.execution: Optional[PlanExecution] = None
        self._task_map: Dict[str, PlanTask] = {}  # file_path -> task
        self._current_task_id: Optional[int] = None
        self._live: Optional[Live] = None
        
    def parse_plan(self, plan_markdown: str) -> PlanExecution:
        """Parse a plan markdown to extract tasks."""
        execution = PlanExecution()
        
        # Extract goal from "Goal & Rationale" section
        goal_match = re.search(r'\*\*Goal\*\*:\s*(.+?)(?:\n|$)', plan_markdown)
        if goal_match:
            execution.goal = goal_match.group(1).strip()
        
        # Parse Impact Analysis table for file changes
        # Look for table rows: | `path/to/file` | [MODIFY] | description |
        table_pattern = r'\|\s*`([^`]+)`\s*\|\s*\[([^\]]+)\]\s*\|\s*([^|]+)\|'
        for match in re.finditer(table_pattern, plan_markdown):
            file_path = match.group(1).strip()
            change_type = match.group(2).strip().upper()
            description = match.group(3).strip()
            
            task_type = "modify" if "MODIFY" in change_type else "new" if "NEW" in change_type else "other"
            
            task = PlanTask(
                id=len(execution.tasks) + 1,
                description=description,
                file_path=file_path,
                task_type=task_type,
            )
            execution.tasks.append(task)
            if file_path:
                self._task_map[file_path] = task
        
        # Parse "Exact Changes" section for line info
        file_section_pattern = r'##\s*File:\s*`([^`]+)`\s*\[([^\]]+)\]'
        for match in re.finditer(file_section_pattern, plan_markdown):
            file_path = match.group(1).strip()
            change_type = match.group(2).strip()
            
            # Find line numbers if present
            lines_match = re.search(r'\*\*Lines\*\*:\s*(.+?)(?:\n|$)', plan_markdown[match.end():match.end()+500])
            if lines_match and file_path in self._task_map:
                self._task_map[file_path].line_info = lines_match.group(1).strip()
        
        # Parse verification steps
        verify_section = re.search(r'#\s*4\.\s*Verification Plan.*?(?=#|$)', plan_markdown, re.DOTALL)
        if verify_section:
            verify_lines = re.findall(r'\*\s*\[\s*\]\s*(.+?)(?:\n|$)', verify_section.group(0))
            execution.verification_steps = [v.strip() for v in verify_lines]
            
            # Add verification as final task
            if execution.verification_steps:
                execution.tasks.append(PlanTask(
                    id=len(execution.tasks) + 1,
                    description="Run verification checks",
                    task_type="verify",
                ))
        
        self.execution = execution
        return execution
    
    def update_from_tool_call(self, tool_name: str, tool_args: Dict) -> Optional[PlanTask]:
        """
        Update task status based on tool call.
        Returns the affected task if any.
        """
        if not self.execution:
            return None
        
        file_path = tool_args.get("file_path", "")
        
        # Map tool calls to task updates
        if tool_name in ("edit_file", "whole_file_update"):
            # Mark file edit as in-progress
            for task in self.execution.tasks:
                if task.file_path and (task.file_path in file_path or file_path in task.file_path):
                    if task.status == TaskStatus.PENDING:
                        task.status = TaskStatus.IN_PROGRESS
                        self._current_task_id = task.id
                        return task
                    elif task.status == TaskStatus.IN_PROGRESS:
                        task.status = TaskStatus.DONE
                        return task
                        
        elif tool_name == "write_to_file_tool":
            # New file creation
            for task in self.execution.tasks:
                if task.file_path and (task.file_path in file_path or file_path in task.file_path):
                    if task.status == TaskStatus.PENDING:
                        task.status = TaskStatus.IN_PROGRESS
                        self._current_task_id = task.id
                        return task
                    elif task.status == TaskStatus.IN_PROGRESS:
                        task.status = TaskStatus.DONE
                        return task
                        
        elif tool_name == "run_terminal_command":
            command = tool_args.get("command", "")
            # Check if this is a verification command
            if any(v in command.lower() for v in ["verify", "test", "check", "compile", "build", "pytest", "npm test"]):
                for task in self.execution.tasks:
                    if task.task_type == "verify" and task.status == TaskStatus.PENDING:
                        task.status = TaskStatus.IN_PROGRESS
                        self._current_task_id = task.id
                        return task
                    elif task.task_type == "verify" and task.status == TaskStatus.IN_PROGRESS:
                        task.status = TaskStatus.DONE
                        return task
        
        return None
    
    def mark_task_done(self, file_path: str) -> None:
        """Mark a specific file task as done."""
        if file_path in self._task_map:
            self._task_map[file_path].status = TaskStatus.DONE
    
    def mark_task_failed(self, file_path: str) -> None:
        """Mark a specific file task as failed."""
        if file_path in self._task_map:
            self._task_map[file_path].status = TaskStatus.FAILED
    
    def get_progress(self) -> tuple:
        """Returns (completed_count, total_count)."""
        if not self.execution:
            return 0, 0
        completed = sum(1 for t in self.execution.tasks if t.status in (TaskStatus.DONE, TaskStatus.FAILED))
        return completed, len(self.execution.tasks)
    
    def is_complete(self) -> bool:
        """Check if all tasks are done or failed."""
        if not self.execution:
            return True
        return all(t.status in (TaskStatus.DONE, TaskStatus.FAILED) for t in self.execution.tasks)
    
    def render(self) -> Panel:
        """Render the task tracker as a Rich Panel."""
        if not self.execution or not self.execution.tasks:
            return Panel("[dim]No tasks to track[/dim]")
        
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("icon", width=3)
        table.add_column("task", ratio=1)
        
        for task in self.execution.tasks:
            icon = self.STATUS_ICONS[task.status]
            color = self.STATUS_COLORS[task.status]
            
            # Build task description
            desc_parts = []
            file_name = None
            if task.file_path:
                file_name = task.file_path.split("/")[-1] if "/" in task.file_path else task.file_path
                desc_parts.append(f"[{color}]{file_name}[/]")
            if task.description and (file_name is None or task.description != file_name):
                desc_parts.append(f"[dim]{task.description}[/dim]")
            if task.line_info:
                desc_parts.append(f"[dim italic]({task.line_info})[/]")
            
            desc = " — ".join(desc_parts) if desc_parts else task.description
            table.add_row(icon, desc)
        
        completed, total = self.get_progress()
        progress_text = f"[{completed}/{total}]"
        
        return Panel(
            table,
            title=f"[bold white]📋 Plan Execution {progress_text}[/bold white]",
            border_style="#ff8888" if completed < total else "green",
            padding=(0, 1),
        )
    
    def get_status_summary(self) -> str:
        """Return a text summary of all tasks and their statuses for AI context injection."""
        if not self.execution or not self.execution.tasks:
            return ""
        lines = ["## Current Plan Execution Status"]
        for task in self.execution.tasks:
            icon = self.STATUS_ICONS[task.status]
            status_label = task.status.value.upper()
            file_part = f" (`{task.file_path}`)" if task.file_path else ""
            lines.append(f"- {icon} [{status_label}] {task.description}{file_part}")
        completed, total = self.get_progress()
        lines.append(f"\nProgress: {completed}/{total} tasks completed")
        return "\n".join(lines)

    def update_from_tool_completion(self, tool_name: str, tool_args: dict, success: bool) -> Optional[PlanTask]:
        """Update task status when a tool call completes (as opposed to starts).

        Marks the currently in-progress task as DONE or FAILED based on *success*.
        """
        if not self.execution:
            return None

        file_path = tool_args.get("file_path", "")

        # Find the in-progress task that matches this tool completion
        for task in self.execution.tasks:
            if task.status != TaskStatus.IN_PROGRESS:
                continue
            # Match by file path
            if task.file_path and file_path and (task.file_path in file_path or file_path in task.file_path):
                task.status = TaskStatus.DONE if success else TaskStatus.FAILED
                return task
            # Match verify tasks by tool name
            if task.task_type == "verify" and tool_name == "run_terminal_command":
                task.status = TaskStatus.DONE if success else TaskStatus.FAILED
                return task

        return None

    def start_live(self) -> Live:
        """Start a live display of the task tracker."""
        self._live = Live(self.render(), refresh_per_second=2, console=self.console)
        self._live.start()
        return self._live
    
    def update_live(self) -> None:
        """Update the live display."""
        if self._live:
            self._live.update(self.render())
    
    def stop_live(self) -> None:
        """Stop the live display."""
        if self._live:
            self._live.stop()
            self._live = None
    
    def print_summary(self) -> None:
        """Print final execution summary."""
        if not self.execution:
            return
        
        completed, total = self.get_progress()
        success = all(t.status == TaskStatus.DONE for t in self.execution.tasks)
        
        if success:
            self.console.print(f"\n[bold green]✅ All {total} tasks completed successfully[/bold green]")
        else:
            done_count = sum(1 for t in self.execution.tasks if t.status == TaskStatus.DONE)
            failed_count = sum(1 for t in self.execution.tasks if t.status == TaskStatus.FAILED)
            self.console.print(f"\n[bold yellow]⚠️ Plan execution finished: {done_count} done, {failed_count} failed[/bold yellow]")


# Global tracker instance for the current session
_current_tracker: Optional[PlanTaskTracker] = None


def get_tracker(console: Optional[Console] = None) -> Optional[PlanTaskTracker]:
    """Get the current plan tracker if active."""
    return _current_tracker


def set_tracker(tracker: Optional[PlanTaskTracker]) -> None:
    """Set the global plan tracker."""
    global _current_tracker
    _current_tracker = tracker


def create_tracker(console: Console, plan_markdown: str) -> PlanTaskTracker:
    """Create and initialize a new plan tracker."""
    tracker = PlanTaskTracker(console)
    tracker.parse_plan(plan_markdown)
    set_tracker(tracker)
    return tracker
