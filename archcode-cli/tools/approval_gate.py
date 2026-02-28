import difflib
import sys
import io
from rich.console import Console
from rich.panel import Panel

_console = Console(style="white on #161616")


class _CPRWarningFilter:
    """Filters out prompt_toolkit's CPR warning from stderr."""
    def __init__(self, real_stderr):
        self._real = real_stderr

    def write(self, text):
        if "CPR" not in text and "cursor position" not in text:
            self._real.write(text)

    def flush(self):
        self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


def _run_toggle(label: str, options=("Apply", "Reject")) -> str:
    """
    Inline arrow-key toggle selector (same style as PlanActionSelector).
    Returns the selected option string, lowercased.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window

    opts = list(options)
    state = {"selected": 0}

    def get_text():
        parts = [("bold", f"\n  {label} ")]
        for i, opt in enumerate(opts):
            if i > 0:
                parts.append(("", "   "))
            if i == state["selected"]:
                parts.append(("#ff8888 bold reverse", f" {opt} "))
            else:
                parts.append(("ansicyan", f" {opt} "))
        parts.append(("", "\n  "))
        parts.append(("dim italic", "← → or h/l to select • Enter to confirm\n"))
        return FormattedText(parts)

    control = FormattedTextControl(get_text)
    layout = Layout(HSplit([Window(content=control)]))
    kb = KeyBindings()
    result = [opts[0].lower()]

    @kb.add("left")
    @kb.add("h")
    def _left(event):
        if state["selected"] > 0:
            state["selected"] -= 1

    @kb.add("right")
    @kb.add("l")
    def _right(event):
        if state["selected"] < len(opts) - 1:
            state["selected"] += 1

    @kb.add("enter")
    def _select(event):
        result[0] = opts[state["selected"]].lower()
        event.app.exit()

    # Suppress the "your terminal doesn't support CPR" warning from prompt_toolkit
    old_stderr = sys.stderr
    sys.stderr = _CPRWarningFilter(old_stderr)
    try:
        Application(layout=layout, key_bindings=kb, full_screen=False).run()
    finally:
        sys.stderr = old_stderr

    return result[0]


class EditApprovalGate:
    """Singleton gate that asks the user to approve or reject each file edit before it is written."""

    def __init__(self):
        self._rejected = False
        self._status = None  # Rich Status handle from the REPL loop

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self):
        """Call at the start of every user prompt to clear rejection state."""
        self._rejected = False
        self._status = None

    def set_status(self, status):
        """Store the active Rich Status handle so tools can pause/resume it."""
        self._status = status

    def is_rejected(self) -> bool:
        return self._rejected

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stop_spinner(self):
        try:
            if self._status is not None:
                self._status.stop()
        except Exception:
            pass

    def _start_spinner(self):
        try:
            if self._status is not None:
                self._status.start()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public approval API
    # ------------------------------------------------------------------

    def request_approval(self, file_path: str, old_content: str, new_content: str) -> bool:
        """
        Show a diff panel then an inline toggle (Apply / Reject).

        Returns True  → user approved, caller should write to disk.
        Returns False → user rejected, caller should abort.
        """
        self._stop_spinner()

        try:
            old_lines = old_content.splitlines()
            new_lines = new_content.splitlines()
            is_new_file = (old_content == "")

            if is_new_file:
                content_lines = [f"[green]+{line}[/green]" for line in new_lines]
                panel_title = f"[bold white]✎ New File — {file_path}[/bold white]"
                panel_content = "\n".join(content_lines) if content_lines else "[dim](empty file)[/dim]"
            else:
                diff = difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{file_path}",
                    tofile=f"b/{file_path}",
                    lineterm="",
                )
                diff_lines = []
                has_changes = False
                for line in diff:
                    has_changes = True
                    if line.startswith("+++") or line.startswith("---"):
                        diff_lines.append(f"[bold]{line}[/bold]")
                    elif line.startswith("@@"):
                        diff_lines.append(f"[cyan]{line}[/cyan]")
                    elif line.startswith("+"):
                        diff_lines.append(f"[green]{line}[/green]")
                    elif line.startswith("-"):
                        diff_lines.append(f"[red]{line}[/red]")
                    else:
                        diff_lines.append(f" {line}")

                if not has_changes:
                    # No effective diff — auto-approve silently
                    self._start_spinner()
                    return True

                panel_title = f"[bold white]✎ Proposed Edit — {file_path}[/bold white]"
                panel_content = "\n".join(diff_lines)

            _console.print()
            _console.print(
                Panel(
                    panel_content,
                    title=panel_title,
                    border_style="#ff8888",
                    padding=(0, 1),
                )
            )

            choice = _run_toggle("Apply this change?")
            if choice == "apply":
                _console.print("  [green]✔ Applied[/green]\n")
                self._start_spinner()
                return True
            else:
                _console.print("  [red]✗ Rejected — stopping all edits[/red]\n")
                self._rejected = True
                self._start_spinner()
                return False

        except Exception:
            # On any unexpected error, default to approving so tools still work
            self._start_spinner()
            return True

    def request_delete_approval(self, file_path: str) -> bool:
        """
        Show a deletion warning panel then an inline toggle (Delete / Cancel).

        Returns True  → user approved deletion.
        Returns False → user rejected.
        """
        self._stop_spinner()

        try:
            _console.print()
            _console.print(
                Panel(
                    f"[red]The following file will be permanently deleted:[/red]\n\n"
                    f"  [bold]{file_path}[/bold]",
                    title="[bold white]✎ Proposed Deletion[/bold white]",
                    border_style="#ff8888",
                    padding=(0, 1),
                )
            )

            choice = _run_toggle("Delete this file?", options=("Delete", "Cancel"))
            if choice == "delete":
                _console.print("  [green]✔ Deletion approved[/green]\n")
                self._start_spinner()
                return True
            else:
                _console.print("  [red]✗ Rejected — stopping all edits[/red]\n")
                self._rejected = True
                self._start_spinner()
                return False

        except Exception:
            self._start_spinner()
            return True


# Module-level singleton
approval_gate = EditApprovalGate()
