import atexit
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

# Try standard import, fallback if needed
try:
    from prompt_toolkit.completion import NestedCompleter
except ImportError:
    from prompt_toolkit.contrib.completers import NestedCompleter

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.theme import Theme

from config import config
from file_completer import (
    ArchimystCompleter,
    AtFileCompleter,
    SlashCommandCompleter,
    get_at_file_key_bindings,
    parse_at_file_references,
)
from logo import get_banner_info, get_logo
from mcp_manager import mcp_manager
from app.runtime.plan_file import save_plan, get_plan_context, update_file_status, mark_plan_complete
from app.runtime.plan_tracker import create_tracker, get_tracker, set_tracker


class CliTheme:
    """Centralized CLI visual theme configuration."""

    PROMPT_STYLE = Style.from_dict(
        {
            "prompt": "#ff8888 bold",
            "border": "#555555",  # dim box-drawing characters
            "completion-menu": "bg:#161616 #ffffff",
            "completion-menu.completion.current": "bg:#444444 #ffffff bold",
            "completion-menu.meta": "bg:#161616 #888888",
            "completion-menu.meta.completion.current": "bg:#444444 #888888",
            "scrollbar.background": "bg:#161616",
            "scrollbar.button": "bg:#444444",
        }
    )

    RICH_THEME = Theme(
        {
            "markdown.h1": "bold white",
            "markdown.h2": "bold white",
            "markdown.h3": "bold white",
            "markdown.h4": "bold white",
            "markdown.h5": "bold white",
            "markdown.h6": "bold white",
            "markdown.link": "#ff8888",
            "markdown.code": "#ff8888",
            "markdown.item.bullet": "#ff8888",
            "markdown.item.number": "#ff8888",
            "markdown.block_quote": "white dim",
        }
    )


SYSTEM_PROMPT = """You are Archimyst (ArchCode), a Council of Agents.
Your goal is to assist the user by planning, coding, and reviewing.
"""


def _set_terminal_background() -> None:
    """Set terminal background color (OSC 11) on startup, best effort."""
    sys.stdout.write("\x1b]11;#161616\x07")
    sys.stdout.flush()


class PlanActionSelector:
    """Inline selector used for plan approval actions."""

    @staticmethod
    def select(session):
        """
        Inline toggle selector for Accept / Reject / Discuss.
        Returns ("accept" | "reject" | "discuss", feedback_or_none).
        Uses arrow keys to navigate, Enter to select.
        """
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit, Layout, Window
        from prompt_toolkit.layout import FormattedTextControl

        options = ["Accept", "Reject", "Discuss"]
        state = {"selected": 0}

        def get_formatted_text():
            from prompt_toolkit.formatted_text import FormattedText

            parts = [
                ("bold", "\n  Review plan: "),
            ]
            for i, opt in enumerate(options):
                if i > 0:
                    parts.append(("", "   "))
                if i == state["selected"]:
                    parts.append(("#ff8888 bold reverse", f" {opt} "))
                else:
                    parts.append(("ansicyan", f" {opt} "))
            parts.append(("", "\n  "))
            parts.append(("dim italic", "← → or h/l to select • Enter to confirm\n"))
            return FormattedText(parts)

        control = FormattedTextControl(get_formatted_text)
        layout = Layout(HSplit([Window(content=control)]))

        kb = KeyBindings()
        result = [None]

        @kb.add("left")
        @kb.add("h")
        def _left(event):
            if state["selected"] > 0:
                state["selected"] -= 1

        @kb.add("right")
        @kb.add("l")
        def _right(event):
            if state["selected"] < len(options) - 1:
                state["selected"] += 1

        @kb.add("enter")
        def _select(event):
            result[0] = options[state["selected"]].lower()
            event.app.exit()

        app = Application(layout=layout, key_bindings=kb, full_screen=False)
        app.run()

        choice = result[0]
        if choice == "accept":
            return "accept", None
        if choice == "reject":
            return "reject", None

        from prompt_toolkit.formatted_text import FormattedText

        feedback = session.prompt(
            "", placeholder=FormattedText([("class:dim", "Type your feedback...")])
        ).strip()
        return "discuss", feedback


class VersionManager:
    """Encapsulates CLI update/version checks."""

    def __init__(self, console: Console):
        self.console = console

    def check_for_updates(self):
        """
        Checks the backend for CLI updates.
        Returns: dict version info or None.
        Raises: SystemExit if a hard update is required.
        """
        import requests
        from packaging import version as v_parser

        backend_url = os.getenv("BACKEND_URL") or "https://archflow-backend.fly.dev"
        try:
            resp = requests.get(
                f"{backend_url}/api/archcode/system/version", timeout=3
            )
            if resp.status_code == 200:
                data = resp.json()
                latest = data.get("latest_version", "1.0.0")
                min_req = data.get("min_required_version", "1.0.0")

                # 1. Hard check (forced)
                if v_parser.parse(config.version) < v_parser.parse(min_req):
                    self.console.print("\n[bold red]✘ Critical Update Required[/bold red]")
                    self.console.print(
                        f"[red]Your version ({config.version}) is no longer supported.[/red]"
                    )
                    self.console.print(
                        f"[yellow]Minimum version required: {min_req}[/yellow]"
                    )
                    self.console.print(
                        f"[white]Please download the latest release: {data.get('download_url')}[/white]\n"
                    )
                    sys.exit(1)

                # 2. Soft check (notify)
                if v_parser.parse(config.version) < v_parser.parse(latest):
                    return data

        except Exception:
            pass  # Don't block startup if backend is down or no internet
        return None


@dataclass
class RuntimeImports:
    """Lazy-loaded runtime dependencies for faster startup banner rendering."""

    RunEvent: Any
    create_agent: Any
    CommandHandler: Any
    get_diff_manager: Any
    set_task_context: Any
    get_file_lock_registry: Any
    get_task_manager: Any


class MockAgentForCommands:
    """Helper to satisfy CommandHandler constructor signature."""

    def __init__(self):
        pass


class ArchCodeCliRuntime:
    """Class-based runtime orchestrator for ArchCode terminal CLI."""

    TOKEN_DISPLAY_FACTOR = 0.1

    def __init__(self):
        self.console = Console(theme=CliTheme.RICH_THEME, style="white on #161616")
        self.version_manager = VersionManager(self.console)
        self.runtime: Optional[RuntimeImports] = None
        self.cmd_handler = None
        self.session = None
        self.agent = None
        self.run_event_cls = None  # Set by _build_agent; differs per agent framework
        self.session_id = "N/A"

    def _load_runtime_imports(self) -> RuntimeImports:
        if self.runtime is not None:
            return self.runtime

        with self.console.status(
            "[bold #ff8888]●[/bold #ff8888] Loading agents...",
            spinner="dots",
            spinner_style="#ff8888",
        ):
            import requests  # noqa: F401  # warm import only
            from packaging import version as v_parser  # noqa: F401  # warm import only

            from app.agents.agent_graph import RunEvent, create_langgraph_agent
            from background_task_manager import get_task_manager
            from commands import CommandHandler
            from diff_manager import get_diff_manager
            from file_lock_registry import get_file_lock_registry
            from task_context import set_task_context

        self.runtime = RuntimeImports(
            RunEvent=RunEvent,
            create_agent=create_langgraph_agent,
            CommandHandler=CommandHandler,
            get_diff_manager=get_diff_manager,
            set_task_context=set_task_context,
            get_file_lock_registry=get_file_lock_registry,
            get_task_manager=get_task_manager,
        )
        return self.runtime

    def _estimate_prompt_tokens(self) -> int:
        try:
            from prompts import get_enriched_agent_prompt

            return len(get_enriched_agent_prompt()) // 3
        except Exception:
            return 0

    def _display_tokens(self, raw_tokens: int) -> int:
        """Scale user-visible token counts without changing real accounting."""
        return max(0, int(raw_tokens * self.TOKEN_DISPLAY_FACTOR))

    def _show_banner(self) -> None:
        self.console.clear()
        self.console.print(get_logo())

        config.new_version_available = self.version_manager.check_for_updates()

        import uuid

        self.session_id = str(uuid.uuid4())

        self.console.print(
            get_banner_info(
                config.version,
                config.model,
                config.mode,
                os.getcwd(),
                config.user_email,
            )
        )

        if config.access_token and config.user_email:
            self.console.print(f"[dim]Logged in as {config.user_email}[/dim]")

        if config.new_version_available:
            latest = config.new_version_available["latest_version"]
            url = config.new_version_available["download_url"]
            self.console.print(
                Panel(
                    f"[bold green]🚀 New Version Available: v{latest}[/bold green]\n"
                    f"[dim]Run [/dim][bold #ff8888]/update[/bold #ff8888][dim] or visit {url}[/dim]",
                    border_style="green",
                    padding=(0, 1),
                )
            )

        self.console.print("[dim]Type '/shortcuts' or '?' for help[/dim]\n")

    def _bootstrap_rag(self) -> None:
        """Trigger an initial RAG sync on startup ( extremely fast via Merkle Tree )."""
        try:
            from RAG.tools import get_rag_manager
            manager = get_rag_manager()
            manager.sync_codebase(console=self.console)
            self.console.print("[green]✓[/green] [dim]Professional RAG system active[/dim]\n")
        except Exception as e:
            self.console.print(f"[dim]○ RAG sync skipped: {e}[/dim]\n")

    # ------------------------------------------------------------------
    # Axon index helpers — fingerprint-based skip & incremental update
    # ------------------------------------------------------------------
    _AXON_IGNORE_DIRS = {
        '.git', 'node_modules', 'venv', '.venv', '__pycache__', '.next',
        'dist', 'build', '.archcode', '.axon', '.tox', '.mypy_cache',
        '.pytest_cache', 'env', '.env',
    }
    _AXON_EXTENSIONS = {
        '.py', '.ts', '.tsx', '.js', '.jsx', '.java', '.go', '.rs',
        '.cpp', '.c', '.h', '.cs', '.php', '.rb', '.swift', '.kt',
        '.scala', '.sh', '.bash', '.zsh',
    }

    @staticmethod
    def _axon_source_fingerprint(root: str) -> str:
        """Return a fast SHA-256 fingerprint of all source files under *root*.

        Uses file path + mtime + size (no content reads) so it's O(readdir),
        not O(file-bytes).  Any added / deleted / modified source file will
        change the fingerprint.
        """
        import hashlib
        h = hashlib.sha256()
        entries = []
        for dirpath, dirnames, filenames in os.walk(root):
            # prune ignored directories in-place
            dirnames[:] = [
                d for d in dirnames
                if d not in ArchCodeCliRuntime._AXON_IGNORE_DIRS
            ]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in ArchCodeCliRuntime._AXON_EXTENSIONS:
                    continue
                full = os.path.join(dirpath, fname)
                try:
                    st = os.stat(full)
                    entries.append(f"{full}\x00{st.st_mtime_ns}\x00{st.st_size}")
                except OSError:
                    pass
        entries.sort()
        for e in entries:
            h.update(e.encode())
        return h.hexdigest()

    def _bootstrap_axon(self):
        """Index codebase with Axon on startup.

        * First run  → full ``axon analyze .``
        * Later runs → skip entirely if no source files changed since the
          last successful index (checked via a lightweight mtime+size
          fingerprint stored in ``.axon/fingerprint``).
        """
        import subprocess
        from rich.status import Status

        cwd = os.getcwd()
        axon_dir = os.path.join(cwd, ".axon")
        fp_file = os.path.join(axon_dir, "fingerprint")

        try:
            check = subprocess.run(
                "axon --version", shell=True,
                capture_output=True, text=True, timeout=5,
            )
            if check.returncode != 0:
                self.console.print("[dim]Axon not found, skipping graph index.[/dim]")
                return

            # --- Fingerprint check: skip if nothing changed ---------------
            if os.path.isdir(axon_dir):
                current_fp = self._axon_source_fingerprint(cwd)
                try:
                    with open(fp_file, "r") as f:
                        stored_fp = f.read().strip()
                except (FileNotFoundError, OSError):
                    stored_fp = None

                if stored_fp == current_fp:
                    self.console.print("[green]✓ Code graph ready (unchanged).[/green]")
                    return

                # Files changed → re-index
                label = "Updating"
            else:
                current_fp = self._axon_source_fingerprint(cwd)
                label = "Building"

            with Status(f"[bold cyan]{label} code graph index...", console=self.console):
                result = subprocess.run(
                    "axon analyze .", shell=True,
                    capture_output=True, text=True, timeout=300,
                )

            if result.returncode == 0:
                # Persist fingerprint so next startup can skip
                os.makedirs(axon_dir, exist_ok=True)
                with open(fp_file, "w") as f:
                    f.write(current_fp)
                self.console.print("[green]✓ Code graph ready.[/green]")
            else:
                self.console.print(
                    f"[yellow]Axon indexing warning: {result.stderr[:200]}[/yellow]"
                )
        except Exception as e:
            self.console.print(f"[dim]Axon init skipped: {e}[/dim]")

    def _bootstrap_skills(self) -> None:
        """On first run, auto-download the skills bundle. On subsequent runs, show count."""
        try:
            from skill_manager import skill_manager as _sm

            global_count = _sm.global_skill_count()
            total_count = len(_sm.list_skills())

            if global_count > 0:
                self.console.print(
                    f"[green]✓[/green] [dim]{total_count} skills available ({global_count} bundled)[/dim]\n"
                )
                return

            if total_count > 0:
                # Project-local skills only (no global bundle)
                self.console.print(
                    f"[green]✓[/green] [dim]{total_count} project skills loaded[/dim]\n"
                )
                return

            # No skills at all — try to download the bundle from the backend
            import io
            import tarfile as _tarfile
            import zipfile as _zipfile

            import requests as _req

            backend_url = os.getenv("BACKEND_URL") or "https://archflow-backend.fly.dev"
            bundle_url = f"{backend_url}/api/archcode/skills/bundle"

            with self.console.status(
                "[bold #ff8888]●[/bold #ff8888] Downloading skills...",
                spinner="dots",
                spinner_style="#ff8888",
            ):
                # Try backend bundle first
                try:
                    resp = _req.get(bundle_url, timeout=45, stream=False)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        _sm.global_skills_dir.mkdir(parents=True, exist_ok=True)
                        buf = io.BytesIO(resp.content)
                        with _tarfile.open(fileobj=buf, mode="r:gz") as tar:
                            tar.extractall(path=str(_sm.global_skills_dir))
                        _sm.refresh_registry()
                        new_count = _sm.global_skill_count()
                        if new_count > 0:
                            self.console.print(
                                f"[green]✓[/green] [dim]{new_count} skills downloaded[/dim]\n"
                            )
                            return
                except Exception:
                    pass

                # Backend bundle unavailable or empty — fall back to GitHub ZIP download
                try:
                    gh_count = self._download_github_skills_zip(_sm, _req, _zipfile)
                    if gh_count > 0:
                        self.console.print(
                            f"[green]✓[/green] [dim]{gh_count} skills downloaded from skills.sh[/dim]\n"
                        )
                        return
                except Exception:
                    pass

            # All download attempts failed
            self.console.print(
                "[dim]○ No skills installed — use [/dim][bold]/connect[/bold][dim] to add skills[/dim]\n"
            )
        except Exception:
            pass

    def _download_github_skills_zip(self, skill_manager, requests_lib, zipfile_lib, limit: int = 200) -> int:
        """
        Download the agno-agi/agent-skills GitHub repo ZIP and extract skill
        directories into the global skills dir. Returns number of skills extracted.
        """
        import io
        import re

        owner = "agno-agi"
        repo = "agent-skills"

        zip_content = None
        for branch in ("main", "master"):
            try:
                url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
                resp = requests_lib.get(url, timeout=120, stream=False)
                if resp.status_code == 200:
                    zip_content = resp.content
                    break
            except Exception:
                continue

        if not zip_content:
            return 0

        skill_manager.global_skills_dir.mkdir(parents=True, exist_ok=True)

        extracted = 0
        buf = io.BytesIO(zip_content)
        with zipfile_lib.ZipFile(buf) as zf:
            names = zf.namelist()

            # Find root prefix (e.g., "agent-skills-main/")
            root_prefix = ""
            for name in names:
                if name.endswith("/") and name.count("/") == 1:
                    root_prefix = name
                    break

            skills_prefix = f"{root_prefix}skills/"

            # Collect unique skill directories
            skill_dirs = set()
            for name in names:
                if name.startswith(skills_prefix):
                    remaining = name[len(skills_prefix):]
                    parts = remaining.split("/")
                    if parts[0]:
                        skill_dirs.add(parts[0])

            for skill_dir in sorted(skill_dirs)[:limit]:
                skill_prefix = f"{skills_prefix}{skill_dir}/"
                skill_path = skill_manager.global_skills_dir / skill_dir
                skill_path.mkdir(parents=True, exist_ok=True)

                # Determine the actual skill name from SKILL.md
                actual_name = skill_dir
                for name in names:
                    if name == f"{skill_prefix}SKILL.md":
                        try:
                            with zf.open(name) as f:
                                text = f.read().decode("utf-8", errors="ignore")
                            m = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
                            if m:
                                actual_name = m.group(1).strip().strip('"').strip("'")
                        except Exception:
                            pass
                        break

                # Extract all files for this skill
                for name in names:
                    if not name.startswith(skill_prefix):
                        continue
                    relative = name[len(skill_prefix):]
                    if not relative:
                        continue
                    dest = skill_path / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with zf.open(name) as src:
                            dest.write_bytes(src.read())
                    except Exception:
                        pass

                # Rename dir if SKILL.md had a different name
                if actual_name != skill_dir:
                    named_path = skill_manager.global_skills_dir / actual_name
                    if not named_path.exists():
                        skill_path.rename(named_path)

                extracted += 1

        if extracted > 0:
            skill_manager.refresh_registry()

        return extracted

    def _bootstrap_mcp(self) -> None:
        if mcp_manager.config_path.exists():
            try:
                mcp_manager.connect_all_sync()
                if mcp_manager.is_connected():
                    self.console.print(
                        f"[green]✓[/green] [dim]MCP: {mcp_manager.get_summary()}[/dim]\n"
                    )
                atexit.register(mcp_manager.cleanup)
            except Exception as e:
                self.console.print(f"[dim]○ MCP servers skipped: {e}[/dim]\n")

    def _build_command_handler(self, runtime: RuntimeImports):
        self.cmd_handler = runtime.CommandHandler(
            MockAgentForCommands(), version=config.version, session_id=self.session_id
        )

    def _build_prompt_session(self) -> PromptSession:
        slash_completer = SlashCommandCompleter()
        at_file_completer = AtFileCompleter(project_root=os.getcwd())
        merged_completer = ArchimystCompleter(slash_completer, at_file_completer)

        self.session = PromptSession(
            history=FileHistory(".archcode_history"),
            style=CliTheme.PROMPT_STYLE,
            completer=merged_completer,
            complete_while_typing=True,
            key_bindings=get_at_file_key_bindings(),
        )
        return self.session

    def _build_agent(self, runtime: RuntimeImports):
        import uuid as _uuid

        _agent_session_id = f"cli_{_uuid.uuid4().hex[:8]}"

        # Collect extra tools from MCP
        _extra_tools = []
        _agno_skills = None
        try:
            from skill_manager import skill_manager as _sm

            _agno_skills = _sm.agno_skills
            _extra_tools.extend(_sm.get_research_tools())
        except Exception:
            pass
        try:
            from mcp_manager import mcp_manager as _mcp_mgr

            _extra_tools.extend(_mcp_mgr.get_tools())
        except Exception:
            pass

        # Check agent mode and create appropriate agent
        if config.agent_mode == "data":
            from app.agents.data.agent import create_data_agent
            from agno.agent import RunEvent as AgnoRunEvent
            self.agent = create_data_agent(
                session_id=_agent_session_id,
                extra_tools=_extra_tools if _extra_tools else None,
            )
            self.run_event_cls = AgnoRunEvent
        else:
            self.agent = runtime.create_agent(
                session_id=_agent_session_id,
                extra_tools=_extra_tools if _extra_tools else None,
                skills=_agno_skills,
            )
            self.run_event_cls = runtime.RunEvent
        return self.agent

    @staticmethod
    def _tool_desc(tool_name: str, tool_args: dict, tool_descriptions: dict) -> str:
        """Return a human-friendly description of a tool call."""
        if tool_name == "view_context":
            fp = tool_args.get("file_path", "")
            ln = tool_args.get("line_number", 0)
            name = os.path.basename(fp) if fp else ""
            return f"Viewing {name}:{ln}" if name else "Viewing code context"
        if tool_name == "read_file_chunked":
            fp = tool_args.get("file_path", "")
            ch = tool_args.get("chunk_number", 0)
            name = os.path.basename(fp) if fp else ""
            return f"Reading {name} (chunk {ch})" if name else f"Reading file section {ch}"
        if tool_name == "search_codebase":
            q = tool_args.get("query", "")
            return f"Searching codebase: {q[:40]}" if q else "Searching codebase (RAG)"
        if tool_name == "search_codebase_graph":
            q = tool_args.get("query", "")
            return f"Searching code graph: {q[:50]}" if q else "Searching code graph"
        if tool_name == "axon_context":
            s = tool_args.get("symbol", "")
            return f"Analyzing symbol: {s[:50]}" if s else "Analyzing symbol context"
        if tool_name == "axon_impact":
            s = tool_args.get("symbol", "")
            return f"Checking blast radius: {s[:50]}" if s else "Analyzing blast radius"
        if tool_name == "list_dir":
            directory = tool_args.get("directory", ".")
            recursive = bool(tool_args.get("recursive", False))
            suffix = " (recursive)" if recursive else ""
            return f"Exploring directory: {directory}{suffix}"
        if tool_name == "run_terminal_command":
            cmd = tool_args.get("command", "")
            return f"Running: {cmd}" if cmd else "Executing system command"
        if tool_name == "read_file":
            fp = tool_args.get("file_path", "")
            name = os.path.basename(fp) if fp else ""
            return f"Reading {name}" if name else "Analyzing file content"
        if tool_name == "edit_file":
            fp = tool_args.get("file_path", "")
            name = os.path.basename(fp) if fp else ""
            return f"Editing {name}" if name else "Modifying existing codebase"
        if tool_name == "write_to_file_tool":
            fp = tool_args.get("file_path", "")
            name = os.path.basename(fp) if fp else ""
            return f"Writing {name}" if name else "Implementing new file"
        # --- Data agent tools ---
        if tool_name == "search_files":
            pat = tool_args.get("pattern", "")
            return f"Searching files: {pat}" if pat else "Searching files"
        if tool_name == "save_file":
            fn = tool_args.get("file_name", "")
            return f"Saving {fn}" if fn else "Saving file"
        if tool_name == "read_file_chunk":
            fn = tool_args.get("file_name", "")
            return f"Reading {fn}" if fn else "Reading file chunk"
        if tool_name == "list_files":
            return "Listing files"
        if tool_name == "run_query":
            q = tool_args.get("query", "")
            return f"DuckDB: {q[:60]}" if q else "Running DuckDB query"
        if tool_name == "show_tables":
            return "Listing DuckDB tables"
        if tool_name in ("describe_table", "summarize_table"):
            tbl = tool_args.get("table", "") or tool_args.get("table_name", "")
            label = "Describing" if tool_name == "describe_table" else "Summarizing"
            return f"{label} table: {tbl}" if tbl else f"{label} table"
        if tool_name == "inspect_query":
            q = tool_args.get("query", "")
            return f"Inspecting query: {q[:50]}" if q else "Inspecting query plan"
        if tool_name in ("create_table_from_path", "load_local_path_to_table", "load_local_csv_to_table"):
            p = tool_args.get("path", "")
            name = os.path.basename(p) if p else ""
            return f"Loading {name} into DuckDB" if name else "Loading file into DuckDB"
        if tool_name == "export_table_to_path":
            tbl = tool_args.get("table", "")
            fmt = tool_args.get("format", "")
            return f"Exporting {tbl} as {fmt}" if tbl else "Exporting table"
        if tool_name == "run_sql_query":
            q = tool_args.get("query", "")
            return f"SQL: {q[:60]}" if q else "Running SQL query"
        if tool_name == "list_tables":
            return "Listing SQL tables"
        if tool_name == "run_python_code":
            code = tool_args.get("code", "")
            first_line = code.split("\n")[0][:50] if code else ""
            return f"Python: {first_line}" if first_line else "Running Python code"
        if tool_name == "run_python_file_return_variable":
            fn = tool_args.get("file_name", "")
            return f"Running {fn}" if fn else "Running Python file"
        if tool_name == "run_shell_command":
            args_list = tool_args.get("args", [])
            cmd = " ".join(args_list)[:60] if isinstance(args_list, list) else str(args_list)[:60]
            return f"Shell: {cmd}" if cmd else "Running shell command"
        if tool_name == "read_csv_file":
            fn = tool_args.get("csv_name", "")
            return f"Reading CSV: {fn}" if fn else "Reading CSV file"
        if tool_name == "query_csv_file":
            fn = tool_args.get("csv_name", "")
            q = tool_args.get("sql_query", "")
            return f"Querying {fn}: {q[:40]}" if fn else "Querying CSV file"
        if tool_name in ("generate_json_file", "generate_csv_file", "generate_pdf_file", "generate_text_file"):
            fn = tool_args.get("filename", "")
            ext = tool_name.replace("generate_", "").replace("_file", "").upper()
            return f"Generating {ext}: {fn}" if fn else f"Generating {ext} file"
        return tool_descriptions.get(tool_name, tool_name)

    def _prompt_user(self, session: PromptSession) -> str:
        """
        Render a boxed multiline input (top border + input area + bottom border)
        using a custom prompt_toolkit Application so BOTH borders are visible while
        the user types. The box grows as the user adds new lines (Alt/Esc + Enter).
        Tab completion and history (↑ ↓) are preserved.
        """
        from prompt_toolkit import Application
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import FloatContainer, Float, HSplit, Window
        from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.layout.menus import CompletionsMenu

        w = self.console.width
        dim_border = "class:border"
        result = []

        # --- Buffer (reuses history + completer from the PromptSession) ---
        buf = Buffer(
            name="main",
            multiline=True,
            history=session.history,
            completer=session.completer,
            complete_while_typing=True,
        )

        # --- Key bindings ---
        kb = KeyBindings()

        @kb.add("enter")
        def _submit(event):
            text = buf.text
            if text.strip():
                result.append(text)
            else:
                result.append(text)
            event.app.exit()

        @kb.add("escape", "enter")
        def _newline(event):
            buf.insert_text("\n")

        @kb.add("up")
        def _hist_up(event):
            buf.history_backward(count=1)

        @kb.add("down")
        def _hist_down(event):
            buf.history_forward(count=1)

        @kb.add("tab")
        def _complete(event):
            buf.start_completion(select_first=True)

        @kb.add("c-c")
        def _cancel(event):
            result.append("")
            event.app.exit()

        final_kb = merge_key_bindings([get_at_file_key_bindings(), kb])

        # Compute exact visual line count for the buffer (accounts for wrap).
        # "│ " prefix = 2 chars, so usable width per visual line = w - 2.
        def _visual_lines() -> int:
            usable = max(1, w - 2)
            total = 0
            for line in buf.text.split("\n"):
                total += max(1, (len(line) + usable - 1) // usable)
            return max(1, total)

        # --- Layout: top border | input | bottom border, with floating completions ---
        top_border = Window(
            content=FormattedTextControl(
                FormattedText([(dim_border, f"╭{'─' * (w - 2)}")])
            ),
            height=1,
        )

        input_window = Window(
            content=BufferControl(
                buffer=buf,
                focusable=True,
            ),
            get_line_prefix=lambda lineno, wrap: FormattedText(
                [(dim_border, "│ ")]
            ),
            wrap_lines=True,
            # Dynamic height: exactly as many lines as the buffer content needs.
            # This keeps the box tight (no gap) and grows as the user types.
            height=lambda: Dimension(min=1, preferred=_visual_lines(), max=_visual_lines()),
        )

        bottom_border = Window(
            content=FormattedTextControl(
                FormattedText([(dim_border, f"╰{'─' * (w - 2)}")])
            ),
            height=1,
        )

        body = FloatContainer(
            content=HSplit([top_border, input_window, bottom_border]),
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=8, scroll_offset=1),
                )
            ],
        )

        layout = Layout(body, focused_element=input_window)

        app = Application(
            layout=layout,
            key_bindings=final_kb,
            full_screen=False,
            style=CliTheme.PROMPT_STYLE,
            mouse_support=False,
        )

        print()  # blank line before the box
        app.run()
        return result[0] if result else ""

    def _handle_exit_request(self, user_input: str, runtime: RuntimeImports) -> bool:
        if user_input.strip().lower() not in ["exit", "quit", ":q", ":wq", "bye"]:
            return False

        running = [
            t
            for _, t in runtime.get_task_manager().get_all_tasks()
            if t.status.value in ("pending", "running")
        ]
        if running:
            self.console.print(f"[yellow]{len(running)} background task(s) still running.[/yellow]")
            self.console.print("[dim]Cancel all and exit? (y/n)[/dim] ", end="")
            confirm = input().strip().lower()
            if confirm != "y":
                return False
            for t in running:
                t.cancel_event.set()

        self.console.print("[#ff8888]Goodbye![/#ff8888]")
        return True

    def _run_repl_loop(self, runtime: RuntimeImports) -> None:
        if self.cmd_handler is None or self.session is None or self.agent is None:
            raise RuntimeError("CLI runtime was not initialized before REPL loop")

        cmd_handler = self.cmd_handler
        session = self.session
        agent = self.agent
        _per_call_prompt_tokens = self._estimate_prompt_tokens()

        while True:
            try:
                # 0. Notify about completed background tasks
                for done_task in runtime.get_task_manager().drain_completed():
                    status_label = (
                        "[green]completed[/green]"
                        if done_task.status.value == "completed"
                        else f"[red]{done_task.status.value}[/red]"
                    )
                    self.console.print(
                        f"[dim]Background task #{done_task.display_id} {status_label}: {done_task.query[:60]}[/dim]"
                    )

                # 1. Pre-turn: check token balance
                if not cmd_handler.check_token_limit():
                    # Blocked state: only allow special commands
                    raw_input = session.prompt("\n❯ (blocked) ").strip().lower()
                    if raw_input in [
                        "/upgrade",
                        "/help",
                        "/shortcuts",
                        "?",
                        "/logout",
                        "exit",
                        "quit",
                    ]:
                        if cmd_handler.handle_command(raw_input, []):
                            continue
                        if raw_input in ["exit", "quit"]:
                            break
                    else:
                        self.console.print(
                            "[dim]Type [/dim][bold]/upgrade[/bold][dim] to continue.[/dim]\n"
                        )
                        continue

                # -- Notify about completed background tasks --
                completed = runtime.get_task_manager().drain_completed()
                for done in completed:
                    emoji = "✓" if done.status.value == "completed" else "✗"
                    self.console.print()
                    self.console.print(
                        f"[bold #ff8888]{emoji} Task #{done.display_id} finished:[/bold #ff8888] {done.query[:60]}"
                    )
                    if done.final_response:
                        self.console.print(
                            Panel(
                                Markdown(escape(done.final_response[:500])),
                                border_style="dim",
                            )
                        )
                    if done.changed_files:
                        self.console.print(
                            f"  [dim]Modified: {', '.join(done.changed_files[:5])}[/dim]"
                        )
                    self.console.print()

                user_input = self._prompt_user(session)

                if not user_input.strip():
                    continue

                if self._handle_exit_request(user_input, runtime):
                    break

                # Handle slash commands (pass empty list — Agno manages history internally)
                if cmd_handler.handle_command(user_input, []):
                    # If the model, API key, or agent mode was changed via slash commands, recreate agent
                    current_agent_model_id = getattr(self.agent.model, "id", None) if self.agent else None
                    current_agent_api_key = getattr(self.agent.model, "api_key", None) if self.agent else None
                    agent_mode_changed = getattr(config, "_agent_mode_changed", False)

                    if self.agent and (agent_mode_changed or current_agent_model_id != config.model or current_agent_api_key != config.openrouter_api_key):
                        try:
                            old_session_id = getattr(self.agent, "session_id", None)
                            _extra = []
                            try:
                                from skill_manager import skill_manager as _sm
                                _extra.extend(_sm.get_research_tools())
                            except Exception:
                                pass
                            try:
                                from mcp_manager import mcp_manager as _mcp_mgr
                                _extra.extend(_mcp_mgr.get_tools())
                            except Exception:
                                pass
                            # Create the right agent based on current mode
                            if config.agent_mode == "data":
                                from app.agents.data.agent import create_data_agent
                                from agno.agent import RunEvent as AgnoRunEvent
                                self.agent = create_data_agent(
                                    session_id=old_session_id,
                                    extra_tools=_extra if _extra else None,
                                )
                                self.run_event_cls = AgnoRunEvent
                            else:
                                self.agent = runtime.create_agent(
                                    session_id=old_session_id,
                                    extra_tools=_extra if _extra else None,
                                    skills=None,
                                )
                                self.run_event_cls = runtime.RunEvent
                            agent = self.agent  # keep local alias in sync
                            config._agent_mode_changed = False  # reset the flag
                        except Exception as _e:
                            self.console.print(f"[dim]Agent recreation failed: {_e}[/dim]")
                    continue

                has_any_key = (
                    getattr(config, "openrouter_api_key", None)
                    or getattr(config, "groq_api_key", None)
                    or getattr(config, "openai_api_key", None)
                    or getattr(config, "anthropic_api_key", None)
                    or getattr(config, "together_api_key", None)
                    or getattr(config, "access_token", None)
                )
                if not has_any_key:
                    self.console.print("\n[bold red]✘ Authentication Required[/bold red]")
                    self.console.print("You are not logged in and no API key was found.")
                    self.console.print("Please run [bold cyan]/login[/bold cyan] to authenticate with your Archimyst account,")
                    self.console.print("or run [bold cyan]/config[/bold cyan] to enter your API key.\n")
                    continue

                # --- Parse @file references and attach file contents ---
                display_input, file_context = parse_at_file_references(user_input)
                if file_context:
                    refs = re.findall(r"@([\w./\-]+)", user_input)
                    for ref in refs:
                        ref_path = os.path.normpath(os.path.join(os.getcwd(), ref))
                        if os.path.isfile(ref_path):
                            rel = os.path.relpath(ref_path, os.getcwd())
                            self.console.print(f"[dim]  📎 Attached: {rel}[/dim]")
                    enriched_input = user_input + "\n" + file_context
                else:
                    enriched_input = user_input

                # Start tracking file changes for this prompt
                dm = runtime.get_diff_manager()
                dm.begin_tracking()

                from tools.approval_gate import approval_gate
                approval_gate.reset()

                # Professional tool event mapping
                TOOL_DESCRIPTIONS = {
                    "read_file": "Analyzing file content",
                    "list_dir": "Exploring directory structure",
                    "write_to_file_tool": "Implementing new file",
                    "edit_file": "Modifying existing codebase",
                    "delete_file": "Removing file from project",
                    "view_context": "Viewing code context",
                    "search_codebase": "Searching codebase (RAG)",
                    "run_terminal_command": "Executing system command",
                    "search_web": "Searching the web",
                    "whole_file_update": "Applying file update",
                    "test_code": "Verifying code output",
                    "github_repo_info": "Viewing repo info",
                    "github_list_issues": "Listing issues",
                    "github_view_issue": "Viewing issue details",
                    "github_list_prs": "Listing pull requests",
                    "github_view_pr": "Viewing PR details",
                    "github_list_branches": "Listing branches",
                    "github_list_commits": "Listing commits",
                    "github_list_tags": "Listing tags",
                    "github_create_issue": "Creating issue",
                    "github_create_pr": "Creating pull request",
                    "github_merge_pr": "Merging pull request",
                    "github_close_issue": "Closing issue",
                    "github_create_comment": "Adding comment",
                    "github_create_branch": "Creating branch",
                    "github_push_commits": "Pushing commits",
                    "execute_github_command": "Running GitHub command",
                    "list_available_skills": "Discovering capabilities",
                    "search_skills": "Searching capabilities",
                    "read_skill_blueprint": "Reading skill blueprint",
                    "read_file_chunked": "Reading file section",
                    "search_codebase_graph": "Searching code graph",
                    "axon_context": "Analyzing symbol context",
                    "axon_impact": "Analyzing blast radius",
                    # Data agent tools
                    "search_files": "Searching files",
                    "save_file": "Saving file",
                    "read_file_chunk": "Reading file chunk",
                    "run_query": "Running DuckDB query",
                    "show_tables": "Listing tables",
                    "describe_table": "Describing table",
                    "inspect_query": "Inspecting query",
                    "summarize_table": "Summarizing table",
                    "create_table_from_path": "Loading file into table",
                    "export_table_to_path": "Exporting table",
                    "load_local_path_to_table": "Loading file into table",
                    "load_local_csv_to_table": "Loading CSV into table",
                    "run_sql_query": "Running SQL query",
                    "list_tables": "Listing tables",
                    "run_python_code": "Running Python code",
                    "run_python_file_return_variable": "Running Python file",
                    "run_shell_command": "Running shell command",
                    "read_csv_file": "Reading CSV file",
                    "query_csv_file": "Querying CSV file",
                    "generate_json_file": "Generating JSON file",
                    "generate_csv_file": "Generating CSV file",
                    "generate_pdf_file": "Generating PDF file",
                    "generate_text_file": "Generating text file",
                }

                # Loop: run agent, handle PLAN_PENDING until user accepts/rejects or we finish
                final_response = ""
                total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
                consulted_skills = set()
                consulted_skills_meta = {}  # Maps skill dir names to friendly names

                # Build reverse mapping: dir name -> friendly skill name
                skill_dir_to_name = {}
                try:
                    from skill_manager import skill_manager as _sm

                    for s in _sm.list_skills():
                        s_path = s.get("path", "")
                        s_name = s.get("name", "")
                        if s_path and s_name:
                            dir_name = os.path.basename(s_path)
                            skill_dir_to_name[dir_name] = s_name
                except Exception:
                    pass

                executed_skills = set()
                plan_rejected = False

                # --- Professional Tracking State ---
                current_phase_start = time.time()
                tool_use_count = 0
                current_tool_tokens = 0
                supervisor_call_count = 0
                model_request_count = 0

                current_input = enriched_input
                while True:
                    content_buffer = ""
                    run_metrics = None

                    with self.console.status(
                        f"[bold #ff8888]●[/bold #ff8888] Thinking...",
                        spinner="dots",
                        spinner_style="#ff8888",
                    ) as status:
                        approval_gate.set_status(status)
                        stream = agent.run(
                            current_input, stream=True, stream_events=True
                        )

                        # Feed the stream on a daemon thread so the main thread
                        # can enforce a per-chunk timeout. Without this, a hung
                        # tool or a dropped provider connection blocks forever.
                        _CHUNK_TIMEOUT = 420  # seconds to wait for next event (7 minutes)
                        _chunk_q: queue.Queue = queue.Queue()

                        def _feed_stream():
                            try:
                                for _c in stream:
                                    _chunk_q.put(("chunk", _c))
                                _chunk_q.put(("done", None))
                            except Exception as _e:
                                _chunk_q.put(("error", _e))

                        _feeder = threading.Thread(
                            target=_feed_stream, daemon=True
                        )
                        _feeder.start()

                        _stream_stalled = False
                        while True:
                            try:
                                _kind, chunk = _chunk_q.get(
                                    timeout=_CHUNK_TIMEOUT
                                )
                            except queue.Empty:
                                _stream_stalled = True
                                status.update(
                                    "[bold red]⚠  No response from provider "
                                    f"for {_CHUNK_TIMEOUT}s — aborting[/bold red]"
                                )
                                self.console.print(
                                    f"\n[bold red]⚠  Stream timed out — "
                                    f"no response from provider for "
                                    f"{_CHUNK_TIMEOUT}s. "
                                    "Check your API key / network and retry.[/bold red]"
                                )
                                break
                            if _kind == "done":
                                break
                            if _kind == "error":
                                raise chunk

                            if approval_gate.is_rejected():
                                break
                            if chunk.event == self.run_event_cls.tool_call_started:
                                tool_name = (
                                    chunk.tool.tool_name
                                    if hasattr(chunk, "tool") and chunk.tool
                                    else ""
                                )
                                tool_args = {}
                                if (
                                    hasattr(chunk, "tool")
                                    and chunk.tool
                                    and hasattr(chunk.tool, "tool_args")
                                ):
                                    tool_args = chunk.tool.tool_args or {}

                                tool_use_count += 1

                                # Derive tool description
                                if tool_name and tool_name.startswith("mcp__"):
                                    _parts = tool_name.split("__")
                                    _mcp_server = _parts[1] if len(_parts) > 1 else ""
                                    _mcp_fn = (
                                        _parts[2]
                                        if len(_parts) > 2
                                        else tool_name
                                    )
                                    desc = f"{_mcp_fn} via {_mcp_server}"
                                else:
                                    desc = self._tool_desc(
                                        tool_name,
                                        tool_args,
                                        TOOL_DESCRIPTIONS,
                                    )

                                # Detect skill execution
                                is_skill_exec = False
                                is_resolving = False
                                is_searching = False
                                skill_exec_name = None
                                if tool_name == "run_terminal_command":
                                    cmd_arg = tool_args.get("command", "")
                                    if ".archcode/skills/" in cmd_arg and (
                                        "from tools import" in cmd_arg
                                        or "python3" in cmd_arg
                                    ):
                                        is_skill_exec = True
                                        skill_match = re.search(
                                            r"\.archcode/skills/([^/\s]+)", cmd_arg
                                        )
                                        if skill_match:
                                            skill_exec_name = skill_match.group(1)
                                    elif any(
                                        kw in cmd_arg
                                        for kw in [
                                            "cat .env",
                                            "export ",
                                            "pip install",
                                            "npm install",
                                            ".env",
                                        ]
                                    ):
                                        is_resolving = True
                                        desc = f"Running: {cmd_arg}"

                                if is_skill_exec:
                                    display_name = (
                                        skill_dir_to_name.get(
                                            skill_exec_name, skill_exec_name
                                        )
                                        if skill_exec_name
                                        else "skill"
                                    )
                                    desc = f"Running {display_name}"
                                    executed_skills.add(display_name)

                                # Professional tool block header
                                if tool_use_count == 1:
                                    if is_skill_exec:
                                        phase = "Executing capability"
                                    elif is_searching or tool_name == "search_codebase":
                                        phase = "Search"
                                    elif is_resolving:
                                        phase = "Setup"
                                    elif tool_name in [
                                        "read_file",
                                        "list_dir",
                                        "search_skills",
                                        "view_context",
                                        "read_file_chunked",
                                        "search_files",
                                        "list_files",
                                        "read_file_chunk",
                                        "show_tables",
                                        "describe_table",
                                        "list_tables",
                                        "summarize_table",
                                        "inspect_query",
                                        "read_csv_file",
                                    ]:
                                        phase = "Explore"
                                    elif tool_name in [
                                        "write_to_file_tool",
                                        "edit_file",
                                        "whole_file_update",
                                        "save_file",
                                        "generate_json_file",
                                        "generate_csv_file",
                                        "generate_pdf_file",
                                        "generate_text_file",
                                        "export_table_to_path",
                                    ]:
                                        phase = "Implement"
                                    elif tool_name in [
                                        "run_query",
                                        "run_sql_query",
                                        "query_csv_file",
                                        "create_table_from_path",
                                        "load_local_path_to_table",
                                        "load_local_csv_to_table",
                                    ]:
                                        phase = "Data Query"
                                    elif tool_name in [
                                        "run_python_code",
                                        "run_python_file_return_variable",
                                        "run_shell_command",
                                    ]:
                                        phase = "Execute"
                                    elif tool_name == "run_terminal_command":
                                        phase = "Verify"
                                    elif tool_name and tool_name.startswith("mcp__"):
                                        _srv = (
                                            tool_name.split("__")[1]
                                            if "__" in tool_name
                                            else "mcp"
                                        )
                                        phase = f"Using MCP · {_srv}"
                                    else:
                                        phase = "System Action"

                                    self.console.print()
                                    self.console.print(
                                        f"● [bold #ff8888]{phase}[/bold #ff8888] ([{tool_name}] {desc})"
                                    )

                                self.console.print(
                                    f"  L [dim][{tool_name}] {desc}[/dim]"
                                )

                                # Update spinner
                                total_toks = total_usage.get("total_tokens", 0)
                                shown_toks = self._display_tokens(total_toks)
                                status.update(
                                    f"[bold #ff8888]●[/bold #ff8888] Running tools... ({shown_toks/1000:.1f}k tokens)"
                                )

                                # Update plan tracker on tool start
                                _active_tracker = get_tracker()
                                if _active_tracker:
                                    _affected = _active_tracker.update_from_tool_call(tool_name, tool_args)
                                    if _affected:
                                        self.console.print(_active_tracker.render())

                            elif chunk.event == self.run_event_cls.tool_call_completed:
                                supervisor_call_count += 1

                                # Update plan tracker on tool completion
                                _active_tracker = get_tracker()
                                if _active_tracker:
                                    _affected = _active_tracker.update_from_tool_completion(
                                        tool_name if 'tool_name' in dir() else "",
                                        tool_args if 'tool_args' in dir() else {},
                                        success=True,
                                    )
                                    if _affected:
                                        self.console.print(_active_tracker.render())
                                        # Update the plan file too
                                        if _affected.file_path:
                                            try:
                                                update_file_status(_affected.file_path, "done")
                                            except Exception:
                                                pass

                            elif (
                                chunk.event
                                == self.run_event_cls.model_request_completed
                            ):
                                # Live token tracking — ModelRequestCompletedEvent
                                # has input_tokens/output_tokens/total_tokens as direct attrs
                                model_request_count += 1
                                _in = getattr(chunk, "input_tokens", 0) or 0
                                _out = getattr(chunk, "output_tokens", 0) or 0
                                _tot = getattr(chunk, "total_tokens", 0) or 0
                                if _in or _out or _tot:
                                    total_usage["input_tokens"] += _in
                                    total_usage["output_tokens"] += _out
                                    total_usage["total_tokens"] += (
                                        _tot if _tot else (_in + _out)
                                    )
                                    current_tool_tokens = total_usage[
                                        "total_tokens"
                                    ]
                                    shown_toks = self._display_tokens(
                                        total_usage["total_tokens"]
                                    )
                                    status.update(
                                        f"[bold #ff8888]●[/bold #ff8888] Running tools... ({shown_toks/1000:.1f}k tokens)"
                                    )

                            elif chunk.event == self.run_event_cls.run_content:
                                if hasattr(chunk, "content") and chunk.content:
                                    content_buffer += chunk.content

                            elif chunk.event == self.run_event_cls.run_completed:
                                # Extract final metrics from completed run
                                if hasattr(chunk, "metrics") and chunk.metrics:
                                    run_metrics = chunk.metrics
                                elif hasattr(chunk, "run_output") and chunk.run_output:
                                    if hasattr(chunk.run_output, "metrics"):
                                        run_metrics = chunk.run_output.metrics

                    # Extract final response
                    final_response = content_buffer

                    # Extract token usage — multiple fallback strategies
                    # 1. From RunCompletedEvent metrics (if populated during streaming)
                    if run_metrics:
                        if isinstance(run_metrics, dict):
                            total_usage["input_tokens"] = (
                                run_metrics.get("input_tokens", 0) or 0
                            )
                            total_usage["output_tokens"] = (
                                run_metrics.get("output_tokens", 0) or 0
                            )
                            total_usage["total_tokens"] = (
                                run_metrics.get("total_tokens", 0) or 0
                            )
                        else:
                            _in = getattr(run_metrics, "input_tokens", 0) or 0
                            _out = (
                                getattr(run_metrics, "output_tokens", 0) or 0
                            )
                            _tot = (
                                getattr(run_metrics, "total_tokens", 0) or 0
                            )
                            if _in or _out or _tot:
                                total_usage["input_tokens"] = _in
                                total_usage["output_tokens"] = _out
                                total_usage["total_tokens"] = (
                                    _tot if _tot else (_in + _out)
                                )

                    # 2. Fallback: read from agent's run_output after stream ends
                    if total_usage.get("total_tokens", 0) == 0:
                        try:
                            _last = agent.run_output
                            if _last and hasattr(_last, "metrics") and _last.metrics:
                                m = _last.metrics
                                total_usage["input_tokens"] = (
                                    getattr(m, "input_tokens", 0) or 0
                                )
                                total_usage["output_tokens"] = (
                                    getattr(m, "output_tokens", 0) or 0
                                )
                                total_usage["total_tokens"] = (
                                    getattr(m, "total_tokens", 0) or 0
                                )
                        except Exception:
                            pass

                    # 3. Last resort: read from session metrics (persistent DB)
                    if total_usage.get("total_tokens", 0) == 0:
                        try:
                            session_metrics = agent.get_session_metrics()
                            if session_metrics:
                                total_usage["input_tokens"] = (
                                    session_metrics.input_tokens or 0
                                )
                                total_usage["output_tokens"] = (
                                    session_metrics.output_tokens or 0
                                )
                                total_usage["total_tokens"] = (
                                    session_metrics.total_tokens or 0
                                )
                        except Exception:
                            pass

                    if total_usage.get("total_tokens", 0) == 0:
                        total_usage["total_tokens"] = total_usage.get(
                            "input_tokens", 0
                        ) + total_usage.get("output_tokens", 0)

                    current_tool_tokens = total_usage.get("total_tokens", 0)

                    # Rejection flow: user rejected a file edit
                    if approval_gate.is_rejected():
                        self.console.print("\n[dim]Editing stopped by user. No further changes will be made.[/dim]")
                        break

                    # Plan approval flow: detect plan in the response
                    if final_response and "PLAN AWAITING APPROVAL" in final_response:
                        plan_content = final_response
                        self.console.print()
                        self.console.print(
                            Panel(
                                Markdown(plan_content),
                                title="[bold #ffffff]✎ Proposed Changes[/bold #ffffff]",
                                border_style="white",
                                padding=(1, 2),
                            )
                        )
                        action, feedback = PlanActionSelector.select(session)

                        if action == "accept":
                            # Save plan to .archcode/archcode.md
                            try:
                                plan_path = save_plan(plan_content)
                                self.console.print(f"  [dim]Plan saved to {plan_path}[/dim]")
                            except Exception:
                                pass

                            # Create and render task tracker
                            try:
                                tracker = create_tracker(self.console, plan_content)
                                self.console.print(tracker.render())
                            except Exception:
                                pass

                            current_input = (
                                "User APPROVED the plan. Execute it NOW.\n"
                                "RULES:\n"
                                "1. Do NOT call search_codebase, rg, sed, grep, ls, or any read/search tool.\n"
                                "2. Go DIRECTLY to edit_file / write_to_file using the exact SEARCH/REPLACE from your plan.\n"
                                "3. After all edits, run the verification command from your plan.\n"
                                "4. Report completion."
                            )
                            continue
                        if action == "reject":
                            plan_rejected = True
                            self.console.print(
                                "[dim]Plan rejected. No changes will be made.[/dim]"
                            )
                            break

                        current_input = (
                            feedback
                            if feedback
                            else "Please revise the plan. What would you like to change?"
                        )
                        continue

                    break

                # Print tracker summary and finalize plan file
                _active_tracker = get_tracker()
                if _active_tracker and _active_tracker.execution:
                    _active_tracker.print_summary()
                    try:
                        mark_plan_complete()
                    except Exception:
                        pass
                    set_tracker(None)

                if plan_rejected:
                    continue  # Skip usage/diff output, back to main prompt

                _prompt_overhead = _per_call_prompt_tokens * max(
                    1, model_request_count
                )

                # Close any remaining open tool block
                if tool_use_count > 0:
                    duration = int(time.time() - current_phase_start)
                    net_tool_tokens = max(0, current_tool_tokens - _prompt_overhead)
                    shown_net_tool_tokens = self._display_tokens(net_tool_tokens)
                    self.console.print(
                        f"  L [#ff8888]Done[/#ff8888] ({tool_use_count} tool uses · {shown_net_tool_tokens/1000:.1f}k tokens · {duration}s)"
                    )
                    self.console.print("  [dim](ctrl+o to expand)[/dim]")
                    tool_use_count = 0
                    current_tool_tokens = 0

                # Print usage info
                usage_parts = []
                if total_usage.get("total_tokens", 0) > 0:
                    raw_in = total_usage["input_tokens"]
                    net_in = max(0, raw_in - _prompt_overhead)
                    out = total_usage["output_tokens"]
                    shown_net_in = self._display_tokens(net_in)
                    shown_out = self._display_tokens(out)
                    usage_parts.append(
                        f"~{shown_net_in/1000:.1f}k task tokens · {shown_out/1000:.1f}k generated"
                    )

                skill_interactions = len(consulted_skills | executed_skills)
                if skill_interactions > 0:
                    usage_parts.append(
                        f"Skills Consulted: {len(consulted_skills)} | Skills Executed: {len(executed_skills)}"
                    )

                if usage_parts:
                    self.console.print()  # breathing room before usage
                    self.console.print(f"[dim]Usage: {' | '.join(usage_parts)}[/dim]")

                # Post-task: report tokens to backend
                if total_usage.get("total_tokens", 0) > 0:
                    cmd_handler.report_usage(total_usage["total_tokens"])

                # Print final response cleanly
                if final_response:
                    self.console.print(Markdown(escape(final_response)))
                elif total_usage.get("output_tokens", 0) > 0:
                    self.console.print("[dim]Agent completed with no summary.[/dim]")

                # --- Show Diffs and Finalize ---
                changed = dm.get_changed_files()
                if changed:
                    # Shows terminal diffs AND writes manifest for editor
                    dm.finalize()

                    self.console.print()  # breathing room before diff summary
                    self.console.print(
                        f"[bold #ff8888]✎ Agent modified {len(changed)} file(s). Review in your editor.[/bold #ff8888]"
                    )
                    for fp in changed:
                        self.console.print(f"  [dim]• {os.path.relpath(fp)}[/dim]")
                    self.console.print()  # breathing room after diff summary

                # Release foreground file locks after each query
                runtime.get_file_lock_registry().release_all("foreground")

            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            except Exception as e:
                self.console.print("[bold red]Error:[/bold red]", escape(str(e)))

    def run(self) -> None:
        self._show_banner()

        if not config.validate():
            sys.exit(1)

        runtime = self._load_runtime_imports()
        # self._bootstrap_rag()  # RAG index creation disabled for now
        self._bootstrap_mcp()
        self._bootstrap_axon()
        self._bootstrap_skills()
        self._build_command_handler(runtime)
        session = self._build_prompt_session()
        agent = self._build_agent(runtime)

        # Set foreground task context so tools use global singletons
        from tools.filesystem import get_history_manager as _get_fg_hm

        runtime.set_task_context(
            "foreground", runtime.get_diff_manager(), _get_fg_hm()
        )

        # Keep local names aligned with existing flow
        self.session = session
        self.agent = agent

        self._run_repl_loop(runtime)


def main() -> None:
    runtime = ArchCodeCliRuntime()
    runtime.run()


if __name__ == "__main__":
    _set_terminal_background()
    main()
