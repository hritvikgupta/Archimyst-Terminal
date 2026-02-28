import os
import json
import shutil
import tempfile
import uuid
import difflib
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

console = Console()

# Baselines dir lives in /tmp so it's ephemeral
_BASELINES_ROOT = Path(tempfile.gettempdir()) / ".archcode_baselines"

# Manifest location — the VS Code extension watches this
MANIFEST_DIR = ".archcode"
MANIFEST_FILE = "pending_diffs.json"

class DiffManager:
    """Manages file baselines and writes a manifest for the editor extension."""

    def __init__(self):
        self.session_id = uuid.uuid4().hex[:8]
        self.session_dir = _BASELINES_ROOT / self.session_id
        self.baselines = {}  # abs_file_path -> baseline_copy_path
        self._tracking = False

    def begin_tracking(self):
        """Start a new tracking cycle. Clears all previous baselines."""
        self._cleanup_session()
        self.session_id = uuid.uuid4().hex[:8]
        self.session_dir = _BASELINES_ROOT / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.baselines = {}
        self._tracking = True

    def snapshot_baseline(self, file_path: str):
        """Save the ORIGINAL state of a file BEFORE the AI changes it."""
        if not self._tracking:
            return

        abs_path = os.path.abspath(file_path)
        if abs_path in self.baselines:
            return

        safe_name = abs_path.replace("/", "__").replace("\\", "__")
        baseline_path = self.session_dir / safe_name

        if os.path.exists(abs_path):
            shutil.copy2(abs_path, baseline_path)
        else:
            # New file — create an empty baseline
            baseline_path.write_text("")

        self.baselines[abs_path] = str(baseline_path)

    def show_terminal_diffs(self):
        """Print a colored diff for all changed files to the terminal."""
        for abs_path, baseline_path in self.baselines.items():
            rel_path = os.path.relpath(abs_path)
            try:
                with open(baseline_path, 'r', encoding='utf-8', errors='replace') as f:
                    old_lines = f.read().splitlines()
                with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                    new_lines = f.read().splitlines()

                diff = difflib.unified_diff(
                    old_lines, new_lines,
                    fromfile=f"original/{rel_path}",
                    tofile=f"ai_changes/{rel_path}",
                    lineterm=""
                )

                diff_text = []
                has_changes = False
                for line in diff:
                    has_changes = True
                    if line.startswith("+++") or line.startswith("---"):
                        diff_text.append(f"[bold]{line}[/bold]")
                    elif line.startswith("@@"):
                        diff_text.append(f"[cyan]{line}[/cyan]")
                    elif line.startswith("+"):
                        diff_text.append(f"[green]{line}[/green]")
                    elif line.startswith("-"):
                        diff_text.append(f"[red]{line}[/red]")
                    else:
                        diff_text.append(f" {line}")

                if has_changes:
                    console.print(
                        Panel(
                            "\n".join(diff_text),
                            title=f"✎ [bold #ff8888]Diff: {rel_path}[/bold #ff8888]",
                            border_style="#ff8888",
                            padding=(1, 2),
                        )
                    )
            except Exception as e:
                console.print(
                    f"  [red]⚠ Could not show diff for {rel_path}: {e}[/red]"
                )

    def write_manifest(self):
        """
        Write a manifest JSON that the VS Code extension reads.
        """
        if not self.baselines:
            return

        # Write manifest to the project's .archcode directory
        manifest_dir = Path(os.getcwd()) / MANIFEST_DIR
        manifest_dir.mkdir(parents=True, exist_ok=True)

        entries = []
        for abs_path, baseline_path in self.baselines.items():
            if self._file_has_changes(abs_path, baseline_path):
                entries.append({
                    "file": abs_path,
                    "baseline": baseline_path,
                    "relative": os.path.relpath(abs_path),
                    "is_new_file": self._is_new_file(baseline_path),
                })

        if not entries:
            return

        manifest = {
            "session_id": self.session_id,
            "timestamp": str(uuid.uuid1()),
            "files": entries,
        }

        manifest_path = manifest_dir / MANIFEST_FILE
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        console.print(
            f"  [dim]📋 Diff manifest written → .archcode/pending_diffs.json "
            f"({len(entries)} file{'s' if len(entries) != 1 else ''})[/dim]"
        )


    def finalize(self):
        """
        Called after AI finishes all edits for a prompt.
        Shows terminal diffs only. Editor decorations are disabled.
        """
        self.show_terminal_diffs()


    def _file_has_changes(self, file_path: str, baseline_path: str) -> bool:
        """Check if a file actually differs from its baseline."""
        try:
            with open(baseline_path, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                new = f.read()
            return old != new
        except Exception:
            return True  # Assume changed if we can't read

    def _is_new_file(self, baseline_path: str) -> bool:
        """Check if baseline is empty (meaning file was newly created)."""
        try:
            return os.path.getsize(baseline_path) == 0
        except Exception:
            return False

    def get_changed_files(self) -> list:
        """Return list of files that have actual changes."""
        changed = []
        for abs_path, baseline_path in self.baselines.items():
            if self._file_has_changes(abs_path, baseline_path):
                changed.append(abs_path)
        return changed

    def _cleanup_session(self):
        if self.session_dir and self.session_dir.exists():
            try:
                shutil.rmtree(self.session_dir)
            except Exception:
                pass
        self.baselines = {}
        self._tracking = False


# Global singleton
_diff_manager = None

def get_diff_manager() -> DiffManager:
    global _diff_manager
    if _diff_manager is None:
        _diff_manager = DiffManager()
    return _diff_manager
