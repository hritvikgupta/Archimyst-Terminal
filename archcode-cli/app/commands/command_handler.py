import os
import sys
import json
import difflib
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown
from rich.markup import escape
from config import config
from skill_manager import skill_manager
from mcp_manager import mcp_manager, MCP_SERVER_REGISTRY


console = Console()


def interactive_rewind_selector(entries, hm):
    """
    Interactive TUI selector for /rewind using prompt_toolkit.

    Since cli.py already uses prompt_toolkit for the main REPL,
    using it here avoids terminal state conflicts that break
    manual raw mode, ANSI codes, and curses.

    - UP/DOWN to navigate within visible entries
    - 'm' to show more entries (loads 5 more)
    - Tab or 'd' for diff preview
    - Enter to select, q/ESC to cancel
    """
    if not entries:
        return None

    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import FormattedText

    PAGE_SIZE = 5
    state = {
        "selected": 0,
        "visible_count": min(PAGE_SIZE, len(entries)),
        "result": None,
        "done": False,
    }
    all_count = len(entries)

    def get_formatted_text():
        lines = []
        sel = state["selected"]
        vis = state["visible_count"]

        lines.append(("bold", "\n"))
        lines.append(("#ff8888 bold", "  Code Checkpoints"))
        lines.append(("gray italic", "  (↑↓ navigate • Enter revert • d diff • m more • q quit)\n"))
        lines.append(("", "\n"))

        current_session = None
        for i in range(vis):
            entry = entries[i]

            if entry["session_id"] != current_session:
                current_session = entry["session_id"]
                label = "CURRENT SESSION" if current_session == hm.session_id else f"SESSION: {current_session}"
                lines.append(("ansiblue bold", f"  ━━ {label} ━━\n"))

            stats = entry.get("stats", {"added": 0, "removed": 0})
            added = stats.get("added", 0)
            removed = stats.get("removed", 0)

            ts = entry.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts).strftime("%H:%M")
            except Exception:
                dt = ts[:10] if ts else "?"

            msg = entry["user_msg"][:50]

            if i == sel:
                lines.append(("#ff8888 bold reverse", f"  ❯ [{entry['id']}] {dt}  {msg}"))
                lines.append(("", " "))
                lines.append(("ansigreen", f"+{added}"))
                lines.append(("", " "))
                lines.append(("ansired", f"-{removed}"))
                lines.append(("", "\n"))
            else:
                lines.append(("", f"    [{entry['id']}] {dt}  {msg}"))
                lines.append(("", " "))
                lines.append(("ansigreen", f"+{added}"))
                lines.append(("", " "))
                lines.append(("ansired", f"-{removed}"))
                lines.append(("", "\n"))

        lines.append(("", "\n"))
        remaining = all_count - vis
        if remaining > 0:
            lines.append(("gray italic", f"  Showing {vis}/{all_count} — press 'm' for {min(PAGE_SIZE, remaining)} more\n"))
        else:
            lines.append(("gray italic", f"  All {all_count} checkpoints shown\n"))
        lines.append(("", "\n"))

        return FormattedText(lines)

    text_control = FormattedTextControl(get_formatted_text)

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def move_up(event):
        if state["selected"] > 0:
            state["selected"] -= 1

    @kb.add("down")
    @kb.add("j")
    def move_down(event):
        if state["selected"] < state["visible_count"] - 1:
            state["selected"] += 1

    @kb.add("m")
    def load_more(event):
        remaining = all_count - state["visible_count"]
        if remaining > 0:
            state["visible_count"] = min(state["visible_count"] + PAGE_SIZE, all_count)

    @kb.add("enter")
    def select_entry(event):
        state["result"] = entries[state["selected"]]
        event.app.exit()

    @kb.add("q")
    @kb.add("escape")
    @kb.add("c-c")
    def cancel(event):
        state["result"] = None
        event.app.exit()

    @kb.add("d")
    @kb.add("tab")
    def show_diff(event):
        # Exit the app temporarily to show diff with Rich
        state["result"] = "__DIFF__"
        state["_diff_entry"] = entries[state["selected"]]
        event.app.exit()

    layout = Layout(HSplit([Window(content=text_control)]))

    while True:
        app = Application(layout=layout, key_bindings=kb, full_screen=False)
        app.run()

        if state["result"] == "__DIFF__":
            # Show diff, then loop back to the selector
            _show_diff_rich(state["_diff_entry"], hm)
            state["result"] = None
            # Rebuild control for next loop
            text_control = FormattedTextControl(get_formatted_text)
            layout = Layout(HSplit([Window(content=text_control)]))
            continue
        else:
            break

    if state["result"] is None:
        console.print("[dim]Cancelled.[/dim]")

    return state["result"]


def _show_diff_rich(entry, hm):
    """Show diff preview using Rich console."""
    console.clear()
    console.print(f"\n  [bold #ff8888]Diff Preview — Checkpoint [{entry['id']}]: {entry['user_msg']}[/bold #ff8888]\n")

    diffs = hm.get_diff_for_checkpoint(entry["id"])

    if not diffs:
        console.print("  [dim]No differences — files match the current state.[/dim]")
    else:
        for d in diffs:
            if d["status"] == "created_by_ai":
                console.print(f"\n  [yellow]⚠ {d['file']}[/yellow] — [dim]created by AI, will be deleted on revert[/dim]")
            elif d["status"] == "deleted":
                console.print(f"\n  [red]✘ {d['file']}[/red] — [dim]file was deleted, snapshot will restore it[/dim]")
            else:
                console.print(f"\n  [bold yellow]╭─ {d['file']}[/bold yellow]")
                for line in d["diff_lines"]:
                    if line.startswith("+++") or line.startswith("---"):
                        console.print(f"  [bold]{line}[/bold]")
                    elif line.startswith("@@"):
                        console.print(f"  [cyan]{line}[/cyan]")
                    elif line.startswith("+"):
                        console.print(f"  [green]{line}[/green]")
                    elif line.startswith("-"):
                        console.print(f"  [red]{line}[/red]")
                    else:
                        console.print(f"  [dim]{line}[/dim]")
                console.print(f"  [bold yellow]╰───[/bold yellow]")

    console.print(f"\n  [dim]Press Enter to return...[/dim]")
    input()


class CommandHandler:
    def __init__(self, agent, version="1.0.0", session_id=None):
        self.agent = agent
        self.version = version
        self.session_id = session_id or "N/A"

    def handle_command(self, user_input: str, history: list) -> bool:
        cmd = user_input.strip().lower()

        if cmd == "/shortcuts" or cmd == "?":
            self.show_shortcuts()
            return True

        if cmd == "/login":
            console.print("\n[bold #ff8888]☁ ArchCode Cloud is coming soon![/bold #ff8888]")
            console.print("[dim]Managed authentication is not yet available.[/dim]")
            console.print("[dim]Use [bold]/config[/bold] to set your own API key and get started now.[/dim]\n")
            return True

        if cmd == "/logout":
            console.print("\n[bold #ff8888]☁ ArchCode Cloud is coming soon![/bold #ff8888]")
            console.print("[dim]Managed authentication is not yet available. Nothing to log out from.[/dim]\n")
            return True

        if cmd == "/config":
            self.handle_config()
            return True

        if cmd == "/rewind":
            self.interactive_rewind()
            return True

        if cmd == "/status":
            self.handle_status()
            return True

        if cmd == "/upgrade":
            self.handle_upgrade()
            return True

        if cmd == "/update":
            self.handle_update()
            return True

        if cmd.startswith("/revert"):
            self.handle_revert(user_input)
            return True

        if cmd == "/clear":
            console.clear()
            return True

        if cmd == "/reset" or cmd == "/new":
            history.clear()
            console.print("[green]Session reset. Starting fresh![/green]")
            return True

        if cmd.startswith("/model"):
            self.change_model(user_input)
        if cmd.startswith("/mode"):
            self.change_mode(user_input)
            return True

        elif cmd.startswith("/skills"):
            self.handle_skills(user_input)
            return True
        elif cmd.startswith("/mcp"):
            self.handle_mcp(user_input)
            return True

        if cmd == "/tasks" or cmd.startswith("/tasks "):
            self._task_list()
            return True

        if cmd == "/task" or cmd.startswith("/task "):
            self._handle_task_commands(user_input, history)
            return True

        if cmd.startswith("/"):
            console.print(f"[#ff8888]Unknown command: {cmd}[/#ff8888]")
            return True
        return False

    def show_shortcuts(self):
        table = Table(title="Available Shortcuts", style="#ff8888")
        table.add_column("Command", style="#ffcccc")
        table.add_column("Description", style="white")

        table.add_row("/shortcuts", "Show this help menu")
        table.add_row("?", "Alias for /shortcuts")
        table.add_row("/status", "Show session, account, and model status")
        table.add_row("/config", "Configure API keys for model providers")
        table.add_row("/upgrade", "Upgrade your plan to increase token limits")
        table.add_row("/rewind", "Interactive checkpoint browser (↑↓ Tab Enter)")
        table.add_row("/clear", "Clear the terminal screen")
        table.add_row("/reset", "Start a new session (clear history)")
        table.add_row("/model <name>", "Switch AI model (e.g. /model gpt-4)")
        table.add_row("/model/providers", "List all available model providers")
        table.add_row("/model/provider", "Browse models by provider")
        table.add_row("/model/provider/<name>", "Browse models from specific provider (e.g. /model/provider/openai)")
        table.add_row("/skills [list|connect|view|delete]", "Manage AI skills (connect with Canva URL)")
        table.add_row("/task <query>", "Run a query as a background task")
        table.add_row("/tasks", "List all background tasks")
        table.add_row("/task status|logs|cancel|result|rewind <id>", "Manage a background task")
        table.add_row("/login", "Cloud login (coming soon)")
        table.add_row("/logout", "Cloud logout (coming soon)")
        table.add_row("exit / quit", "Exit the CLI")


        console.print(table)

    def handle_status(self):
        """Displays the current session status in a professional layout."""
        # Refresh usage info from backend before displaying
        self.check_token_limit()

        from rich.table import Table

        # Header line
        console.print("[dim]───────────────────────────────────────────────────────────────────────────────────────[/dim]")

        # Main Info Grid
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", width=15)
        table.add_column()

        email = config.user_email or "Not Logged In"
        
        # Determine login method display
        if config.using_own_key:
            login_method = "[green]Own API Key[/green] (Private Mode)"
            plan_display = "UNLIMITED"
        elif config.access_token:
            login_method = "Archimyst Account"
            plan_display = config.mode.upper()
        else:
            login_method = "Not Authenticated"
            plan_display = "LIMITED"

        table.add_row("Version:", f"{self.version}")
        table.add_row("Session ID:", f"{self.session_id}")
        table.add_row("cwd:", f"{os.getcwd()}")
        table.add_row("Login method:", f"{login_method}")
        table.add_row("Account:", f"[bold white]{email}[/bold white]")
        table.add_row("", "") # Spacer
        table.add_row("Model:", f"[bold #ff8888]archimyst/archcode-1.0-fast[/bold #ff8888] · {plan_display} Plan")

        # Memory/Usage - only show for non-private mode
        if config.using_own_key:
            table.add_row("Usage:", "[green]✓ Unlimited[/green] [dim](your API key)[/dim]")
        else:
            progress = (config.token_usage / config.token_limit) * 100 if config.token_limit > 0 else 0
            progress_color = "green" if progress < 70 else "yellow" if progress < 90 else "red"

            # Create a simple loader bar (10 blocks)
            filled_blocks = min(10, int(progress / 10))
            bar = "█" * filled_blocks + "░" * (10 - filled_blocks)

            usage_str = f"[{progress_color}]{bar} {progress:.4f}% used[/{progress_color}]"
            table.add_row("Usage:", usage_str)
        
        table.add_row("Memory:", "[dim]Local Context · Graph-based persistence[/dim]")

        console.print(table)
        console.print("[dim]───────────────────────────────────────────────────────────────────────────────────────[/dim]")

    def handle_upgrade(self):
        """Opens the pricing page in the browser."""
        import webbrowser
        url = "https://www.archimyst.com/#pricing"
        console.print(f"[bold #ff8888]Redirecting to Archimyst Pricing...[/bold #ff8888]")
        console.print(f"[dim]If the browser doesn't open, visit: {url}[/dim]")
        webbrowser.open(url)

    def handle_update(self):
        """Checks for updates and runs the install script to update."""
        import subprocess
        import requests
        from packaging import version as v_parser

        backend_url = os.getenv("BACKEND_URL") or "https://archflow-backend.fly.dev"
        console.print("\n[bold #ff8888] ArchCode Update [/bold #ff8888]")

        with console.status("[dim]Checking for updates...[/dim]", spinner="dots"):
            try:
                resp = requests.get(f"{backend_url}/api/archcode/system/version", timeout=5)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                console.print(f"[red]✘ Could not reach update server:[/red] {e}")
                return

        latest = data.get("latest_version", config.version)
        changelog = data.get("changelog", [])

        if v_parser.parse(config.version) >= v_parser.parse(latest):
            console.print(f"[green]✔ You are already on the latest version (v{config.version}).[/green]")
            return

        console.print(f"[bold green]New version available: v{latest}[/bold green]")
        if changelog:
            console.print("\n[bold white]What's New:[/bold white]")
            for item in changelog:
                console.print(f" • {item}")
            console.print()

        console.print("[dim]Installing update...[/dim]\n")
        try:
            result = subprocess.run(
                ["bash", "-c", "curl -fsSL https://www.archimyst.com/install.sh | bash"],
                timeout=300
            )
            if result.returncode == 0:
                console.print(f"\n[bold green]✔ Updated to v{latest}![/bold green] Please restart ArchCode.")
            else:
                console.print(f"\n[red]✘ Update failed (exit code {result.returncode})[/red]")
        except Exception as e:
            console.print(f"\n[red]✘ Update failed:[/red] {e}")

    def check_token_limit(self) -> bool:
        """Checks the backend for the current token limit status."""
        import requests
        
        # Skip token limit check if user is using their own API key (private mode)
        if config.using_own_key:
            return True
        
        if not config.access_token:
            return True 

        backend_url = os.getenv("BACKEND_URL") or "https://archflow-backend.fly.dev"
        headers = {"Authorization": f"Bearer {config.access_token}"}

        try:
            resp = requests.get(f"{backend_url}/api/usage/status", headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                config.token_usage = data.get("token_usage", 0)
                config.token_limit = data.get("token_limit", 50000)
                config.is_blocked = data.get("is_blocked", False)

                if config.is_blocked:
                    console.print("\n[bold red]✘ Plan Limit Exceeded[/bold red]")
                    console.print(f"[red]You have used {config.token_usage:,} / {config.token_limit:,} tokens.[/red]")
                    console.print("[yellow]Please type [bold]/upgrade[/bold] to continue building with the Council.[/yellow]\n")
                    return False
            return True
        except Exception:
            return config.token_usage < config.token_limit

    def report_usage(self, token_count: int):
        """Reports token usage to the backend after a turn."""
        import requests
        
        # Skip reporting if user is using their own API key (private mode)
        if config.using_own_key:
            return
        
        if not config.access_token or token_count <= 0:
            config.token_usage += token_count 
            return

        backend_url = os.getenv("BACKEND_URL") or "https://archflow-backend.fly.dev"
        headers = {"Authorization": f"Bearer {config.access_token}"}

        try:
            requests.post(
                f"{backend_url}/api/usage/report", 
                json={"tokens": int(token_count)}, 
                headers=headers, 
                timeout=5
            )
        except Exception as e:
            config.token_usage += token_count

    def interactive_rewind(self):
        """Interactive rewind with arrow key navigation and diff preview."""
        from tools.filesystem import get_history_manager
        hm = get_history_manager()
        # history = hm.get_all_history()
        history = hm.get_session_history()

        if not history:
            console.print("[yellow]No code checkpoints found yet.[/yellow]")
            return

        entries = list(reversed(history))

        chosen = interactive_rewind_selector(entries, hm)
        if chosen is None:
            return

        console.print(f"\n[bold yellow]Revert to checkpoint [{chosen['id']}]: {chosen['user_msg']}?[/bold yellow]")
        console.print("[dim]Press Y to confirm, any other key to cancel.[/dim]")

        confirm = input().strip().lower()
        if confirm != 'y':
            console.print("[dim]Cancelled.[/dim]")
            return

        success, message = hm.revert_to(chosen['id'])
        if success:
            console.print(f"[green]✔ {message}[/green]")
            console.print("[dim]Note: File content has been reverted. Review your files.[/dim]")
        else:
            console.print(f"[red]✘ Error: {message}[/red]")

    def show_code_history(self):
        from tools.filesystem import get_history_manager
        hm = get_history_manager()
        history = hm.get_all_history()

        if not history:
            console.print("[yellow]No code checkpoints found yet.[/yellow]")
            return

        console.print("\n[bold #ff8888]Code Checkpoints & History[/bold #ff8888]")

        current_session = None
        for entry in reversed(history):
            if entry["session_id"] != current_session:
                current_session = entry["session_id"]
                session_label = "CURRENT SESSION" if current_session == hm.session_id else f"SESSION: {current_session}"
                console.print(f"\n[bold blue]━━ {session_label} ━━[/bold blue]")

            stats = entry.get("stats", {"added": 0, "removed": 0})
            stat_str = f"[green]+{stats.get('added', 0)}[/green] [red]-{stats.get('removed', 0)}[/red]"

            ts = entry.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts).strftime("%H:%M")
            except Exception:
                dt = ts[:10]

            console.print(f"[{entry['id']}] [dim]{dt}[/dim] [white]{entry['user_msg']}[/white] ({stat_str})")
        console.print("\n[dim]Use /revert <id> to restore code to that state.[/dim]\n")

    def handle_revert(self, user_input):
        parts = user_input.split()
        if len(parts) < 2:
            console.print("[#ff8888]Usage: /revert <checkpoint_id>[/#ff8888]")
            return

        try:
            checkpoint_id = int(parts[1])
        except ValueError:
            console.print("[#ff8888]Invalid ID. Please provide a numeric checkpoint ID.[/#ff8888]")
            return

        from tools.filesystem import get_history_manager
        hm = get_history_manager()

        success, message = hm.revert_to(checkpoint_id)
        if success:
            console.print(f"[green]✔ {message}[/green]")
            console.print("[dim]Note: File content has been reverted. Review your files.[/dim]")
        else:
            console.print(f"[red]✘ Error: {message}[/red]")

    def change_mode(self, input_str: str):
        """Handle /mode command to switch between coding and data agents."""
        parts = input_str.split()
        
        if len(parts) < 2:
            console.print(f"[dim]Current mode: {config.agent_mode}[/dim]")
            console.print("[bold]Available modes:[/bold]")
            console.print("  [cyan]coding[/cyan]  - Coding agent (LangGraph)")
            console.print("  [cyan]data[/cyan]    - Data analysis agent (Agno)")
            return
        
        mode = parts[1].lower()
        if mode not in ["coding", "data"]:
            console.print("[red]Invalid mode. Use: /mode coding or /mode data[/red]")
            return
        
        old_mode = config.agent_mode
        config.agent_mode = mode
        config.save_persisted_config()
        console.print(f"[green]Switched to {mode} mode.[/green]")
        if old_mode != mode:
            console.print("[dim]Agent will be recreated for the new mode.[/dim]")
            config._agent_mode_changed = True
        else:
            console.print("[dim]Already in {mode} mode.[/dim]")

    def change_model(self, input_str):
        # Load providers from JSON (for OpenRouter provider browsing)
        from app.utils import get_resource_path
        from app.utils.model_store import (
            get_available_models,
            OPENAI_DIRECT_MODELS,
            ANTHROPIC_DIRECT_MODELS,
            GROQ_DIRECT_MODELS,
            TOGETHER_DIRECT_MODELS,
        )
        providers_path = get_resource_path("app/utils/openrouter_chat_models_by_provider.json")
        try:
            with open(providers_path, 'r') as f:
                providers = json.load(f)["providers"]
        except Exception:
            providers = {}

        # --- Reusable interactive selector ---
        def _interactive_select(items, title, subtitle="", footer="  ↑ ↓ to move • Enter to confirm • Esc to go back"):
            """Generic interactive arrow-key selector.
            items: list of display strings.
            Returns selected index or None if cancelled.
            """
            from prompt_toolkit import Application
            from prompt_toolkit.formatted_text import FormattedText
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window
            import shutil

            if not items:
                return None

            term_h = shutil.get_terminal_size().lines
            max_vis = max(term_h - 6, 10)
            st = {"selected": 0, "scroll": 0}
            res = [None]

            def _text():
                sel = st["selected"]
                if sel < st["scroll"]:
                    st["scroll"] = sel
                elif sel >= st["scroll"] + max_vis:
                    st["scroll"] = sel - max_vis + 1
                scroll = st["scroll"]
                visible = items[scroll:scroll + max_vis]

                parts = [
                    ("bold", f"\n  {title}  "),
                    ("dim", subtitle),
                    ("", "\n"),
                ]
                if scroll > 0:
                    parts.append(("dim", f"    ▲ {scroll} more above\n"))
                else:
                    parts.append(("", "\n"))

                for vi, label in enumerate(visible):
                    actual_i = scroll + vi
                    if actual_i == sel:
                        parts.append(("#ff8888 bold reverse", f"  ❯ {label}  "))
                    else:
                        parts.append(("", f"    {label}  "))
                    parts.append(("", "\n"))

                remaining = len(items) - (scroll + max_vis)
                if remaining > 0:
                    parts.append(("dim", f"    ▼ {remaining} more below\n"))
                else:
                    parts.append(("", "\n"))
                parts.append(("dim italic", f"{footer}\n"))
                return FormattedText(parts)

            kb = KeyBindings()

            @kb.add("up")
            @kb.add("k")
            def _up(event):
                if st["selected"] > 0:
                    st["selected"] -= 1

            @kb.add("down")
            @kb.add("j")
            def _down(event):
                if st["selected"] < len(items) - 1:
                    st["selected"] += 1

            @kb.add("pageup")
            def _pgup(event):
                st["selected"] = max(0, st["selected"] - max_vis)

            @kb.add("pagedown")
            def _pgdn(event):
                st["selected"] = min(len(items) - 1, st["selected"] + max_vis)

            @kb.add("enter")
            def _select(event):
                res[0] = st["selected"]
                event.app.exit()

            @kb.add("c-c")
            @kb.add("escape")
            def _cancel(event):
                event.app.exit()

            control = FormattedTextControl(_text)
            layout = Layout(HSplit([Window(content=control)]))
            Application(layout=layout, key_bindings=kb, full_screen=False).run()
            return res[0]

        # --- Provider org helpers ---
        # Providers that have org-level grouping
        _ORG_PROVIDERS = {"openrouter", "together", "groq"}

        def _get_provider_orgs(provider_name):
            """Return sorted list of (org_key, org_display, model_count) for a provider."""
            if provider_name == "openrouter":
                return [
                    (p, p, len(providers[p].get("models", [])))
                    for p in sorted(providers.keys())
                ]
            elif provider_name == "together":
                orgs = {}
                for mid, lbl in TOGETHER_DIRECT_MODELS:
                    parts = lbl.split("—")
                    org = parts[-1].strip() if len(parts) > 1 else "Unknown"
                    orgs.setdefault(org, 0)
                    orgs[org] += 1
                return [(o, o, c) for o, c in sorted(orgs.items())]
            elif provider_name == "groq":
                orgs = {}
                for mid, lbl in GROQ_DIRECT_MODELS:
                    parts = lbl.split("—")
                    org = parts[-1].strip() if len(parts) > 1 else "Unknown"
                    orgs.setdefault(org, 0)
                    orgs[org] += 1
                return [(o, o, c) for o, c in sorted(orgs.items())]
            return []

        def _get_org_models(provider_name, org_filter):
            """Return (models_list, add_after_select) for a specific org within a provider."""
            org_lower = org_filter.lower()
            if provider_name == "openrouter":
                if org_filter in providers:
                    prov_data = providers[org_filter]
                    ml = []
                    for m in prov_data["models"]:
                        cost = float(m.get('pricing', {}).get('completion', 0))
                        if cost > 0.000003 and not config.using_own_key:
                            ml.append((m["id"], f"{m['name']} — {m.get('canonical_slug', m['id'])} [Upgrade to enterprise]"))
                        else:
                            ml.append((m["id"], f"{m['name']} — {m.get('canonical_slug', m['id'])}"))
                    return ml, True
                return [], False
            elif provider_name == "together":
                filtered = [
                    (mid, lbl) for mid, lbl in TOGETHER_DIRECT_MODELS
                    if lbl.split("—")[-1].strip().lower() == org_lower
                ]
                return filtered, False
            elif provider_name == "groq":
                filtered = [
                    (mid, lbl) for mid, lbl in GROQ_DIRECT_MODELS
                    if lbl.split("—")[-1].strip().lower() == org_lower
                ]
                return filtered, False
            return [], False

        def _show_org_selector(provider_name, provider_display):
            """Show interactive org selector for a provider. Returns (models_list, add_after_select) or None."""
            org_list = _get_provider_orgs(provider_name)
            if not org_list:
                console.print(f"[red]No organizations found for {provider_display}.[/red]")
                return None
            labels = [f"{org_display:20s} [{count} model{'s' if count != 1 else ''}]" for _, org_display, count in org_list]
            idx = _interactive_select(
                labels,
                f"Organizations",
                f"({provider_display})",
                "  ↑ ↓ to navigate • Enter to browse models • Esc to go back",
            )
            if idx is None:
                console.print("[dim]Selection cancelled.[/dim]")
                return None
            org_key = org_list[idx][0]
            return _get_org_models(provider_name, org_key)

        # --- Build the default display list from all active providers ---
        models_list = get_available_models(config)
        model_ids = [m[0] for m in models_list]

        # Parse command using slashes
        parts = input_str.split('/')
        if len(parts) < 2 or parts[1] != 'model':
            console.print("[red]Invalid command. Use /model subcommands.[/red]")
            return

        sub_parts = parts[2:]
        add_after_select = False

        if len(sub_parts) == 0:
            # /model — show interactive selector with all active-provider models
            pass
        elif len(sub_parts) == 1:
            arg = sub_parts[0]
            if arg in ('providers', 'provider'):
                # /model/providers — interactive provider selector (only providers with API keys)
                provider_entries = []  # (key, display_label)
                if config._openrouter_api_key or config.access_token:
                    total_or = sum(len(providers[p].get("models", [])) for p in providers)
                    provider_entries.append(("openrouter", f"OpenRouter         [{total_or} models across {len(providers)} orgs]"))
                if config._together_api_key:
                    tog_orgs = _get_provider_orgs("together")
                    provider_entries.append(("together", f"Together AI        [{len(TOGETHER_DIRECT_MODELS)} models across {len(tog_orgs)} orgs]"))
                if config._groq_api_key:
                    groq_orgs = _get_provider_orgs("groq")
                    provider_entries.append(("groq", f"Groq               [{len(GROQ_DIRECT_MODELS)} models across {len(groq_orgs)} orgs]"))
                if config._openai_api_key:
                    provider_entries.append(("openai", f"OpenAI (Direct)    [{len(OPENAI_DIRECT_MODELS)} models]"))
                if config._anthropic_api_key:
                    provider_entries.append(("anthropic", f"Anthropic (Direct) [{len(ANTHROPIC_DIRECT_MODELS)} models]"))

                if not provider_entries:
                    console.print("[red]No providers configured. Set an API key to get started.[/red]")
                    return

                labels = [lbl for _, lbl in provider_entries]
                idx = _interactive_select(
                    labels,
                    "Available Providers",
                    "",
                    "  ↑ ↓ to navigate • Enter to browse • Esc to close",
                )
                if idx is None:
                    console.print("[dim]Selection cancelled.[/dim]")
                    return

                selected_provider = provider_entries[idx][0]

                # Org-based providers → show org selector first
                if selected_provider in _ORG_PROVIDERS:
                    result = _show_org_selector(selected_provider, provider_entries[idx][1].split("[")[0].strip())
                    if result is None:
                        return
                    models_list, add_after_select = result
                    model_ids = [m[0] for m in models_list]
                elif selected_provider == "openai":
                    models_list = list(OPENAI_DIRECT_MODELS)
                    model_ids = [m[0] for m in models_list]
                elif selected_provider == "anthropic":
                    models_list = list(ANTHROPIC_DIRECT_MODELS)
                    model_ids = [m[0] for m in models_list]
            else:
                # Assume direct model ID or provider name
                possible_id = arg

                # /model/openai — direct to models (small list)
                if possible_id == "openai" and config._openai_api_key:
                    models_list = list(OPENAI_DIRECT_MODELS)
                    model_ids = [m[0] for m in models_list]
                # /model/anthropic — direct to models (small list)
                elif possible_id == "anthropic" and config._anthropic_api_key:
                    models_list = list(ANTHROPIC_DIRECT_MODELS)
                    model_ids = [m[0] for m in models_list]
                # /model/groq — show org selector
                elif possible_id == "groq" and config._groq_api_key:
                    result = _show_org_selector("groq", "Groq")
                    if result is None:
                        return
                    models_list, add_after_select = result
                    model_ids = [m[0] for m in models_list]
                # /model/together — show org selector
                elif possible_id == "together" and config._together_api_key:
                    result = _show_org_selector("together", "Together AI")
                    if result is None:
                        return
                    models_list, add_after_select = result
                    model_ids = [m[0] for m in models_list]
                # /model/openrouter — show org selector
                elif possible_id == "openrouter" and (config._openrouter_api_key or config.access_token):
                    result = _show_org_selector("openrouter", "OpenRouter")
                    if result is None:
                        return
                    models_list, add_after_select = result
                    model_ids = [m[0] for m in models_list]
                # /model/<openrouter-org> — direct OpenRouter org shortcut
                elif possible_id in providers:
                    prov_data = providers[possible_id]
                    mods = prov_data["models"]
                    models_list = []
                    for m in mods:
                        cost = float(m.get('pricing', {}).get('completion', 0))
                        if cost > 0.000003 and not config.using_own_key:
                            models_list.append((m["id"], f"{m['name']} — {m.get('canonical_slug', m['id'])} [Upgrade to enterprise]"))
                        else:
                            models_list.append((m["id"], f"{m['name']} — {m.get('canonical_slug', m['id'])}"))
                    model_ids = [m[0] for m in models_list]
                    add_after_select = True
                elif possible_id in [m[0] for m in get_available_models(config)]:
                    config.model = possible_id
                    config.save_persisted_config()
                    console.print(f"[green]✓[/green] Model changed to [bold #ff8888]{possible_id}[/bold #ff8888]")
                    console.print("[dim]The new model will be used for your next message.[/dim]")
                    return
                else:
                    console.print(f"[red]Unknown model ID: {possible_id}[/red]")
                    return
        elif len(sub_parts) == 2:
            # /model/<provider>/<org> — filter by org within a provider
            prov_key = sub_parts[0].lower()
            org_key = sub_parts[1]

            if prov_key == "openrouter" and (config._openrouter_api_key or config.access_token):
                ml, aas = _get_org_models("openrouter", org_key)
                if not ml:
                    console.print(f"[red]No OpenRouter org matching '{org_key}'.[/red]")
                    console.print(f"[dim]Available orgs: {', '.join(sorted(providers.keys())[:10])}...[/dim]")
                    return
                models_list, add_after_select = ml, aas
                model_ids = [m[0] for m in models_list]
            elif prov_key == "together" and config._together_api_key:
                ml, aas = _get_org_models("together", org_key)
                if not ml:
                    orgs = set()
                    for mid, lbl in TOGETHER_DIRECT_MODELS:
                        orgs.add(lbl.split("—")[-1].strip())
                    console.print(f"[red]No Together models matching org '{org_key}'.[/red]")
                    console.print(f"[dim]Available orgs: {', '.join(sorted(orgs))}[/dim]")
                    return
                models_list, add_after_select = ml, aas
                model_ids = [m[0] for m in models_list]
            elif prov_key == "groq" and config._groq_api_key:
                ml, aas = _get_org_models("groq", org_key)
                if not ml:
                    orgs = set()
                    for mid, lbl in GROQ_DIRECT_MODELS:
                        orgs.add(lbl.split("—")[-1].strip())
                    console.print(f"[red]No Groq models matching org '{org_key}'.[/red]")
                    console.print(f"[dim]Available orgs: {', '.join(sorted(orgs))}[/dim]")
                    return
                models_list, add_after_select = ml, aas
                model_ids = [m[0] for m in models_list]
            else:
                # Try as a model ID with slash, e.g., /model/openai/gpt-4o-mini
                possible_id = '/'.join(sub_parts)
                all_model_ids = [m[0] for m in get_available_models(config)]
                if possible_id in all_model_ids:
                    config.model = possible_id
                    config.save_persisted_config()
                    console.print(f"[green]✓[/green] Model changed to [bold #ff8888]{possible_id}[/bold #ff8888]")
                    console.print("[dim]The new model will be used for your next message.[/dim]")
                    return
                else:
                    console.print(f"[red]Unknown model ID or invalid subcommand: {'/'.join(sub_parts)}[/red]")
                    return
        elif len(sub_parts) >= 2 and sub_parts[0] == 'provider':
            # /model/provider/<name> - legacy route, select from provider
            provider = '/'.join(sub_parts[1:])
            if provider == "openai" and config._openai_api_key:
                models_list = list(OPENAI_DIRECT_MODELS)
                model_ids = [m[0] for m in models_list]
            elif provider == "anthropic" and config._anthropic_api_key:
                models_list = list(ANTHROPIC_DIRECT_MODELS)
                model_ids = [m[0] for m in models_list]
            elif provider == "groq" and config._groq_api_key:
                result = _show_org_selector("groq", "Groq")
                if result is None:
                    return
                models_list, add_after_select = result
                model_ids = [m[0] for m in models_list]
            elif provider == "together" and config._together_api_key:
                result = _show_org_selector("together", "Together AI")
                if result is None:
                    return
                models_list, add_after_select = result
                model_ids = [m[0] for m in models_list]
            elif provider == "openrouter" and (config._openrouter_api_key or config.access_token):
                result = _show_org_selector("openrouter", "OpenRouter")
                if result is None:
                    return
                models_list, add_after_select = result
                model_ids = [m[0] for m in models_list]
            elif provider not in providers:
                console.print(f"[red]Provider '{provider}' not found.[/red]")
                return
            else:
                prov_data = providers[provider]
                mods = prov_data["models"]
                models_list = []
                for m in mods:
                    cost = float(m.get('pricing', {}).get('completion', 0))
                    if cost > 0.000003 and not config.using_own_key:
                        models_list.append((m["id"], f"{m['name']} — {m.get('canonical_slug', m['id'])} [Upgrade to enterprise]"))
                    else:
                        models_list.append((m["id"], f"{m['name']} — {m.get('canonical_slug', m['id'])}"))
                model_ids = [m[0] for m in models_list]
                add_after_select = True
        else:
            # Handle potential multiple slash IDs, e.g., /model/openai/gpt-4o-mini
            possible_id = '/'.join(sub_parts)
            all_model_ids = [m[0] for m in get_available_models(config)]
            if possible_id in all_model_ids:
                config.model = possible_id
                config.save_persisted_config()
                console.print(f"[green]✓[/green] Model changed to [bold #ff8888]{possible_id}[/bold #ff8888]")
                console.print("[dim]The new model will be used for your next message.[/dim]")
                return
            else:
                console.print(f"[red]Unknown model ID or invalid subcommand: {'/'.join(sub_parts)}[/red]")
                return

        # Interactive arrow-key model selector
        from prompt_toolkit import Application
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window

        # Find current model index
        try:
            start_idx = model_ids.index(config.model)
        except ValueError:
            start_idx = 0

        state = {"selected": start_idx, "scroll": 0}
        import shutil
        term_h = shutil.get_terminal_size().lines
        max_visible = max(term_h - 6, 10)

        def get_text():
            active_providers = []
            if config._openai_api_key:
                active_providers.append("OpenAI")
            if config._anthropic_api_key:
                active_providers.append("Anthropic")
            if config._groq_api_key:
                active_providers.append("Groq")
            if config._together_api_key:
                active_providers.append("Together")
            if config._openrouter_api_key or config.access_token:
                active_providers.append("OpenRouter")
            provider_badge = f"  [{', '.join(active_providers)}]" if active_providers else ""

            sel = state["selected"]
            if sel < state["scroll"]:
                state["scroll"] = sel
            elif sel >= state["scroll"] + max_visible:
                state["scroll"] = sel - max_visible + 1

            scroll = state["scroll"]
            visible = models_list[scroll:scroll + max_visible]

            parts = [
                ("bold", "\n  Select model  "),
                ("dim", f"(current: {config.model})"),
                ("#ff8888", provider_badge),
                ("", "\n"),
            ]
            if scroll > 0:
                parts.append(("dim", f"    ▲ {scroll} more above\n"))
            else:
                parts.append(("", "\n"))

            for vi, (mid, label) in enumerate(visible):
                actual_i = scroll + vi
                if actual_i == sel:
                    parts.append(("#ff8888 bold reverse", f"  ❯ {label}  "))
                else:
                    parts.append(("", f"    {label}  "))
                parts.append(("", "\n"))

            remaining = len(models_list) - (scroll + max_visible)
            if remaining > 0:
                parts.append(("dim", f"    ▼ {remaining} more below\n"))
            else:
                parts.append(("", "\n"))
            parts.append(("dim italic", "  ↑ ↓ to move • Enter to confirm • Ctrl-C to cancel\n"))
            return FormattedText(parts)

        kb = KeyBindings()
        result = [None]

        @kb.add("up")
        @kb.add("k")
        def _up(event):
            if state["selected"] > 0:
                state["selected"] -= 1

        @kb.add("down")
        @kb.add("j")
        def _down(event):
            if state["selected"] < len(models_list) - 1:
                state["selected"] += 1

        @kb.add("pageup")
        def _pgup(event):
            state["selected"] = max(0, state["selected"] - max_visible)

        @kb.add("pagedown")
        def _pgdn(event):
            state["selected"] = min(len(models_list) - 1, state["selected"] + max_visible)

        @kb.add("enter")
        def _select(event):
            result[0] = model_ids[state["selected"]]
            event.app.exit()

        @kb.add("c-c")
        @kb.add("escape")
        def _cancel(event):
            event.app.exit()

        control = FormattedTextControl(get_text)
        layout = Layout(HSplit([Window(content=control)]))
        Application(layout=layout, key_bindings=kb, full_screen=False).run()

        if result[0] is None:
            console.print("[dim]Model selection cancelled.[/dim]")
            return

        # Check for upgrade
        selected_id = result[0]
        selected_tuple = models_list[state["selected"]]
        mlabel = selected_tuple[1]
        if "[Upgrade to enterprise]" in mlabel:
            console.print("[red]✗ This model requires an enterprise upgrade. Please select a different model.[/red]")
            return
        config.model = selected_id
        if add_after_select:
            new_tuple = models_list[state["selected"]]
            if new_tuple not in config.available_models:
                config.available_models.append(new_tuple)
                console.print(f"[green]✓[/green] Added {new_tuple[1]} to available models.")

        config.save_persisted_config()
        console.print(f"\n[green]✓[/green] Model changed to [bold #ff8888]{result[0]}[/bold #ff8888]")
        console.print("[dim]The new model will be used for your next message.[/dim]\n")

    def handle_skills(self, user_input):
        parts = user_input.split()
        if len(parts) < 2:
            self.show_skills_help()
            return

        subcmd = parts[1].lower()
        if subcmd == "list":
            self.list_skills()
        elif subcmd == "refresh":
            self.refresh_skills()
        elif subcmd == "view" and len(parts) > 2:

            self.view_skill(parts[2])
        elif subcmd == "create" and len(parts) > 2:
            self.create_skill(parts[2])
        elif subcmd == "search" and len(parts) > 2:
            self.search_skills(" ".join(parts[2:]))
        elif subcmd == "connect" and len(parts) > 2:
            self.connect_project(parts[2])
        elif subcmd == "batch-run" and len(parts) > 2:
            self.batch_run_skills(parts[2:])
        elif subcmd == "install" and len(parts) > 2:
            self.install_skill(parts[2])
        else:
            self.show_skills_help()

    def show_skills_help(self):
        table = Table(title="Skill Management Commands", style="#ff8888")
        table.add_column("Command", style="#ffcccc")
        table.add_column("Description", style="white")
        table.add_row("/skills list", "Show all available skills")
        table.add_row("/skills refresh", "Re-scan skills directory and update registry")
        table.add_row("/skills view <name>", "Show skill details and documentation")
        table.add_row("/skills connect <URL>", "Connect to a Canva project & fetch AI skills")
        table.add_row("/skills search <query>", "Search for skills")
        table.add_row("/skills create <name>", "Create a new skill template")
        table.add_row("/skills install <name>", "Install skill from marketplace")
        table.add_row("/skills batch-run <list>", "Run multiple skills in parallel")
        console.print(table)

    def list_skills(self):
        skills = skill_manager.list_skills()
        if not skills:
            console.print("[yellow]No skills found. Use /skills create or install to add some.[/yellow]")
            return

        table = Table(title="Available Skills", style="#ff8888")
        table.add_column("Name", style="#ffcccc")
        table.add_column("Version", style="white")
        table.add_column("Description", style="dim")
        for s in skills:
            table.add_row(s.get("name", "N/A"), s.get("version", "1.0.0"), s.get("description", ""))
        console.print(table)

    def refresh_skills(self):
        skill_manager.refresh_registry()
        console.print("[green]✔ Skill registry refreshed and updated successfully![/green]")


    def view_skill(self, name):
        skill = skill_manager.get_skill(name)
        if not skill:
            console.print(f"[red]Skill '{name}' not found.[/red]")
            return

        console.print(Panel(f"[bold #ff8888]Skill: {skill.get('name')}[/bold #ff8888]\n"
                            f"Version: {skill.get('version')}\n"
                            f"Description: {skill.get('description')}", border_style="#ff8888"))

        doc_path = Path(skill["path"]) / "skill.md"
        if doc_path.exists():
            with open(doc_path, "r") as f:
                console.print(Markdown(f.read()))

    def create_skill(self, name):
        skill_path = Path(".archcode/skills") / name
        if skill_path.exists():

            console.print(f"[red]Skill '{name}' already exists.[/red]")
            return

        skill_path.mkdir(parents=True)
        # Create 5 boilerplate files
        (skill_path / "handler.py").write_text("async def run(inputs: dict) -> dict:\n    return {'status': 'success', 'message': 'Hello from " + name + "!'}\n")
        (skill_path / "skill.json").write_text(json.dumps({"name": name, "version": "1.0.0", "description": "New skill " + name}, indent=2))
        (skill_path / "schema.json").write_text(json.dumps({"type": "object", "properties": {}}, indent=2))
        (skill_path / "requirements.txt").write_text("")
        (skill_path / "skill.md").write_text(f"# {name} Skill\n\nImplementation of {name}.")

        skill_manager.refresh_registry()
        console.print(f"[green]✔ Skill '{name}' template created successfully![/green]")

    def search_skills(self, query):
        skills = skill_manager.list_skills()
        results = [s for s in skills if query.lower() in s.get("name", "").lower() or query.lower() in s.get("description", "").lower()]

        if not results:
            console.print(f"[yellow]No skills matching '{query}'.[/yellow]")
            return

        table = Table(title=f"Search Results for '{query}'", style="#ff8888")
        table.add_column("Name", style="#ffcccc")
        table.add_column("Description", style="white")
        for s in results:
            table.add_row(s.get("name"), s.get("description"))
        console.print(table)

    def batch_run_skills(self, skill_list):
        # Implementation of batch-run (simplified for now)
        console.print(f"[dim]Triggering batch run for: {skill_list}[/dim]")
        # This would ideally use skill_manager.run_skill in parallel
        console.print("[yellow]Batch run logic is being initialized...[/yellow]")

    def install_skill(self, name):
        console.print(f"[dim]Simulating installation of skill '{name}' from marketplace...[/dim]")
        # Placeholder for marketplace logic
        self.create_skill(name)

    def connect_project(self, url: str):
        """Orchestrates the connection to a Canva project."""
        import asyncio

        try:
            with console.status("[bold #ff8888]🧠 Archimyst is architecting your skill package...[/bold #ff8888]", spinner="dots") as status:
                # Run the async connection logic
                result = asyncio.run(skill_manager.connect_project(url))

            console.print(f"\n[bold green]✔ Connected Successfully![/bold green]")
            console.print(f"[white]Project:[/white] [bold #ff8888]{result['name']}[/bold #ff8888]")
            console.print(f"[white]Location:[/white] [dim]{result['path']}[/dim]")

            files_list = ", ".join([f"[cyan]{f}[/cyan]" for f in result['files']])
            console.print(f"[white]Files Installed:[/white] {files_list}")
            console.print(f"\n[dim]The Council of Agents now has full context of this architecture.[/dim]")

            # Check if the skill requires env var configuration
            try:
                config_info = skill_manager.check_skill_config(result["name"])
                required = config_info.get("required", {})
                missing = config_info.get("missing", [])

                if missing:
                    console.print(f"\n[bold #ff8888]⚙ This skill requires environment variables:[/bold #ff8888]\n")
                    entered_vars = {}
                    skipped = []

                    for var_name in missing:
                        description = required.get(var_name, "Required environment variable")
                        console.print(f"  [bold white]{var_name}[/bold white] — [dim]{description}[/dim]")
                        value = console.input("  [dim]> Enter value (or press Enter to skip):[/dim] ").strip()
                        if value:
                            entered_vars[var_name] = value
                            console.print("  [green]✔ Set[/green]\n")
                        else:
                            skipped.append(var_name)
                            console.print("  [yellow]⚠ Skipped[/yellow]\n")

                    if entered_vars:
                        skill_manager.save_skill_env(result["name"], entered_vars)
                        console.print(f"[green]Environment saved to .archcode/skills/{result['name']}/.env ({len(entered_vars)}/{len(missing)} configured)[/green]")

                    if skipped:
                        console.print(f"[yellow]⚠ Missing: {', '.join(skipped)} — some tools may not work.[/yellow]")
                elif required:
                    console.print(f"\n[green]⚙ Config: All {len(required)} required env vars are already set.[/green]")
            except Exception:
                pass  # Non-fatal — skill works, config check is best-effort

            console.print()

        except Exception as e:
            console.print(f"\n[bold red]✘ Connection Failed:[/bold red] {str(e)}")

    # ------------------------------------------------------------------ #
    #  Background Task Commands
    # ------------------------------------------------------------------ #

    def _handle_task_commands(self, user_input: str, history: list):
        """Route /task subcommands."""
        from background_task_manager import get_task_manager

        raw = user_input.strip()
        # /task (no args) → help
        if raw.lower() == "/task":
            self._task_help()
            return

        rest = raw[len("/task"):].strip()
        parts = rest.split(None, 1)
        subcmd = parts[0].lower() if parts else ""

        if subcmd == "status" and len(parts) > 1:
            self._task_status(parts[1])
        elif subcmd == "logs" and len(parts) > 1:
            self._task_logs(parts[1])
        elif subcmd == "cancel" and len(parts) > 1:
            self._task_cancel(parts[1])
        elif subcmd == "result" and len(parts) > 1:
            self._task_result(parts[1])
        elif subcmd == "rewind" and len(parts) > 1:
            self._task_rewind(parts[1])
        elif subcmd in ("status", "logs", "cancel", "result", "rewind"):
            console.print(f"[#ff8888]Usage: /task {subcmd} <id>[/#ff8888]")
        else:
            # Everything else is treated as a query to submit
            self._task_submit(rest)

    def _task_submit(self, query: str):
        from background_task_manager import get_task_manager
        if not query.strip():
            self._task_help()
            return
        mgr = get_task_manager()
        display_id, task_id = mgr.submit_task(query)
        console.print(f"[bold #ff8888]Task #{display_id} submitted.[/bold #ff8888] [dim]Running in background...[/dim]")

    def _task_list(self):
        from background_task_manager import get_task_manager
        mgr = get_task_manager()
        tasks = mgr.get_all_tasks()
        if not tasks:
            console.print("[dim]No background tasks yet. Use /task <query> to start one.[/dim]")
            return

        table = Table(title="Background Tasks", style="#ff8888")
        table.add_column("#", style="#ffcccc", width=4)
        table.add_column("Status", width=10)
        table.add_column("Query", style="white", max_width=50)
        table.add_column("Duration", style="dim", width=10)
        table.add_column("Files", style="dim", width=6)

        for did, task in tasks:
            status_color = {
                "pending": "dim",
                "running": "bold yellow",
                "completed": "bold green",
                "failed": "bold red",
                "cancelled": "dim red",
            }.get(task.status.value, "white")

            duration = ""
            start = task.started_at or task.created_at
            end = task.completed_at or datetime.now()
            secs = int((end - start).total_seconds())
            if secs < 60:
                duration = f"{secs}s"
            else:
                duration = f"{secs // 60}m{secs % 60}s"

            query_preview = task.query[:47] + "..." if len(task.query) > 50 else task.query
            files_count = str(len(task.changed_files)) if task.changed_files else "-"

            table.add_row(
                str(did),
                f"[{status_color}]{task.status.value}[/{status_color}]",
                query_preview,
                duration,
                files_count,
            )

        console.print(table)

    def _task_status(self, id_str: str):
        from background_task_manager import get_task_manager
        from file_lock_registry import get_file_lock_registry

        task = self._resolve_task(id_str)
        if task is None:
            return

        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", width=15)
        table.add_column()

        table.add_row("Task ID:", f"#{task.display_id} ({task.task_id})")
        table.add_row("Status:", f"[bold]{task.status.value}[/bold]")
        table.add_row("Query:", task.query)
        table.add_row("Created:", task.created_at.strftime("%H:%M:%S"))
        if task.started_at:
            table.add_row("Started:", task.started_at.strftime("%H:%M:%S"))
        if task.completed_at:
            table.add_row("Completed:", task.completed_at.strftime("%H:%M:%S"))

        # Token usage
        if task.token_usage.get("total_tokens", 0) > 0:
            table.add_row("Tokens:", f"{task.token_usage['input_tokens']} in, {task.token_usage['output_tokens']} out")

        # Locked files
        locked = get_file_lock_registry().get_locks_for_task(task.task_id)
        if locked:
            table.add_row("Locked files:", ", ".join(os.path.relpath(p) for p in locked))

        # Changed files
        if task.changed_files:
            table.add_row("Changed files:", ", ".join(task.changed_files))

        # Error
        if task.error_message:
            table.add_row("Error:", f"[red]{task.error_message}[/red]")

        console.print(Panel(table, title=f"[bold #ff8888]Task #{task.display_id}[/bold #ff8888]", border_style="#ff8888"))

    def _task_logs(self, id_str: str):
        task = self._resolve_task(id_str)
        if task is None:
            return
        logs = task.log_buffer.getvalue()
        if not logs.strip():
            console.print(f"[dim]No logs yet for task #{task.display_id}.[/dim]")
        else:
            console.print(Panel(escape(logs), title=f"[bold #ff8888]Logs — Task #{task.display_id}[/bold #ff8888]", border_style="#ff8888"))

    def _task_cancel(self, id_str: str):
        from background_task_manager import get_task_manager
        try:
            display_id = int(id_str)
        except ValueError:
            console.print("[#ff8888]Invalid task ID.[/#ff8888]")
            return
        mgr = get_task_manager()
        ok, msg = mgr.cancel_task(display_id)
        if ok:
            console.print(f"[yellow]{msg}[/yellow]")
        else:
            console.print(f"[red]{msg}[/red]")

    def _task_result(self, id_str: str):
        task = self._resolve_task(id_str)
        if task is None:
            return
        from background_task_manager import TaskStatus
        if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            console.print(f"[yellow]Task #{task.display_id} is still {task.status.value}.[/yellow]")
            return
        if task.final_response:
            console.print(Panel(
                Markdown(task.final_response),
                title=f"[bold #ff8888]Result — Task #{task.display_id}[/bold #ff8888]",
                border_style="#ff8888",
            ))
        else:
            console.print(f"[dim]No response captured for task #{task.display_id}.[/dim]")
        if task.changed_files:
            console.print(f"[bold #ff8888]Changed files:[/bold #ff8888]")
            for f in task.changed_files:
                console.print(f"  [dim]• {f}[/dim]")

    def _task_rewind(self, id_str: str):
        """Interactive rewind scoped to a specific background task's checkpoints."""
        task = self._resolve_task(id_str)
        if task is None:
            return
        if task.history_manager is None:
            console.print(f"[yellow]No history available for task #{task.display_id}.[/yellow]")
            return

        hm = task.history_manager
        history = hm.get_session_history()
        if not history:
            console.print(f"[yellow]No checkpoints found for task #{task.display_id}.[/yellow]")
            return

        entries = list(reversed(history))
        chosen = interactive_rewind_selector(entries, hm)
        if chosen is None:
            return

        console.print(f"\n[bold yellow]Revert task #{task.display_id} to checkpoint [{chosen['id']}]: {chosen['user_msg']}?[/bold yellow]")
        console.print("[dim]Press Y to confirm, any other key to cancel.[/dim]")

        confirm = input().strip().lower()
        if confirm != 'y':
            console.print("[dim]Cancelled.[/dim]")
            return

        success, message = hm.revert_to(chosen['id'])
        if success:
            console.print(f"[green]✔ {message}[/green]")
        else:
            console.print(f"[red]✘ Error: {message}[/red]")

    def _task_help(self):
        table = Table(title="Background Task Commands", style="#ff8888")
        table.add_column("Command", style="#ffcccc")
        table.add_column("Description", style="white")
        table.add_row("/task <query>", "Submit a query to run in the background")
        table.add_row("/tasks", "List all background tasks")
        table.add_row("/task status <id>", "Show detailed status of a task")
        table.add_row("/task logs <id>", "Show task execution logs")
        table.add_row("/task cancel <id>", "Cancel a running task")
        table.add_row("/task result <id>", "Show the final response of a completed task")
        table.add_row("/task rewind <id>", "Rewind file changes made by a task")
        console.print(table)

    def _resolve_task(self, id_str: str):
        """Parse display_id and fetch the task, or print an error."""
        from background_task_manager import get_task_manager
        try:
            display_id = int(id_str)
        except ValueError:
            console.print("[#ff8888]Invalid task ID. Use a number.[/#ff8888]")
            return None
        task = get_task_manager().get_task(display_id)
        if task is None:
            console.print(f"[red]Task #{display_id} not found.[/red]")
        return task

    def handle_login(self):
        """Web-based authentication flow for the CLI."""
        import requests
        import webbrowser
        import time

        backend_url = os.getenv("BACKEND_URL") or "https://archflow-backend.fly.dev"

        console.print("\n[bold #ff8888] ArchCode Authentication [/bold #ff8888]")
        console.print("[dim]Initiating secure browser-based login...[/dim]\n")

        try:
            # 1. Initialize Auth
            resp = requests.post(f"{backend_url}/api/auth/cli/init")
            resp.raise_for_status()
            data = resp.json()

            device_code = data["device_code"]
            auth_url = data["auth_url"]

            console.print(f"1. Open this URL in your browser:\n   [link={auth_url}]{auth_url}[/link]\n")
            console.print(f"2. Confirm the request on the page.")
            console.print(f"3. Return here once finished.\n")

            # Try to open browser automatically
            webbrowser.open(auth_url)

            # 2. Polling
            with console.status("[bold #ff8888]Waiting for approval...[/bold #ff8888]", spinner="dots") as status:
                start_time = time.time()
                timeout = 300 # 5 minutes

                while time.time() - start_time < timeout:
                    try:
                        poll_resp = requests.get(f"{backend_url}/api/auth/cli/poll/{device_code}")
                        poll_data = poll_resp.json()
                    except Exception:
                        time.sleep(3)
                        continue

                    if poll_data["status"] == "success":
                        token = poll_data["access_token"]
                        email = poll_data["user_email"]
                        tier = poll_data["plan"]

                        # Save to config
                        config.access_token = token
                        config.user_email = email
                        config.mode = tier
                        config.synced_env_vars = poll_data.get("env_vars", {})
                        config.save_persisted_config()

                        console.print(f"\n[bold green]✔ Success![/bold green] Logged in as [bold white]{email}[/bold white]")
                        console.print(f"[dim]Plan: {tier.upper()}[/dim]")
                        console.print(f"[dim]Session saved. You'll stay logged in across all terminals.[/dim]")
                        return

                    elif poll_data["status"] == "pending":
                        pass

                    elif poll_data["status"] == "expired":
                        console.print("\n[bold red]✘ Error:[/bold red] Authentication link expired.")
                        return

                    time.sleep(3) # Poll every 3 seconds

                console.print("\n[bold red]✘ Error:[/bold red] Authentication timed out.")

        except Exception as e:
            console.print(f"\n[bold red]✘ Authentication failed:[/bold red] {str(e)}")

    def handle_logout(self):
        """Clears the local session."""
        if not config.access_token:
            console.print("[yellow]You are not logged in.[/yellow]")
            return

        email = config.user_email
        config.access_token = None
        config.user_email = None
        config.mode = "free"

        # >>> ADD THESE <<<
        config.synced_env_vars = {}       # clears keys that came from backend login
        config._openrouter_api_key = None # clears session-stored key (choice "Use my key")
        config.using_own_key = False

        config.save_persisted_config()

        console.print(f"[green]✔ Successfully logged out.[/green] [dim]Account '{email}' session cleared.[/dim]")

    def handle_config(self):
        """Interactive configuration — API keys for coding mode, DB config for data mode."""
        from prompt_toolkit import Application
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window
        
        # Import config here to get current agent_mode
        from config import config

        # Always show API key configuration (pass data_mode flag to include DB options)
        self._handle_coding_config(include_data_config=(config.agent_mode == "data"))

    def _handle_coding_config(self, include_data_config=False):
        """Handle API key configuration. When include_data_config=True, also shows DB options."""
        from prompt_toolkit import Application
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window

        from config import config

        # Each entry: (kind, config_attr, display_name, hint, description)
        # kind = "key" for API keys, "db" for database fields
        ALL_OPTIONS = [
            ("key", "openrouter", "OpenRouter",      "sk-or-",  "Access 200+ models across all providers"),
            ("key", "openai",     "OpenAI",           "sk-",     "Direct access to GPT models"),
            ("key", "anthropic",  "Anthropic",        "sk-ant-", "Direct access to Claude models"),
            ("key", "groq",       "Groq",             "gsk_",    "Ultra-fast inference for open-source models"),
            ("key", "together",   "Together AI",      "",        "Fast inference for open-source models (Llama, Qwen, DeepSeek)"),
        ]

        if include_data_config:
            ALL_OPTIONS.append(("separator", "", "", "", ""))  # visual separator
            ALL_OPTIONS.extend([
                ("db", "database_url", "Database URL",     "postgresql://user:pass@host:port/db", "Full SQLAlchemy connection string"),
                ("db", "db_host",      "PostgreSQL Host",  "localhost",  "PostgreSQL server hostname"),
                ("db", "db_port",      "PostgreSQL Port",  "5432",       "PostgreSQL server port"),
                ("db", "db_name",      "Database Name",    "postgres",   "Database to connect to"),
                ("db", "db_user",      "Database User",    "postgres",   "Username for authentication"),
                ("db", "db_password",  "Database Password","********",   "Password for authentication"),
            ])

        # Filter out separators for selection indexing
        selectable = [(i, opt) for i, opt in enumerate(ALL_OPTIONS) if opt[0] != "separator"]

        def _current_value(kind: str, field: str) -> str:
            if kind == "key":
                if field == "openrouter":    return config._openrouter_api_key or ""
                elif field == "openai":      return config._openai_api_key or ""
                elif field == "groq":        return config._groq_api_key or ""
                elif field == "together":    return config._together_api_key or ""
                else:                        return config._anthropic_api_key or ""
            else:  # db
                if field == "database_url":  return config.database_url or ""
                elif field == "db_host":     return config.db_host or ""
                elif field == "db_port":     return str(config.db_port or "5432")
                elif field == "db_name":     return config.db_name or "postgres"
                elif field == "db_user":     return config.db_user or ""
                elif field == "db_password": return config.db_password or ""
            return ""

        def _status(kind: str, field: str) -> tuple:
            value = _current_value(kind, field)
            if not value:
                return ("ansiyellow", "[NOT SET]")
            if kind == "key":
                masked = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "****"
                return ("ansigreen", f"[SET: {masked}]")
            # DB fields
            if field == "db_password":
                return ("ansigreen", "[SET: ********]")
            if field == "database_url" and "://" in value:
                parts = value.split("://")
                protocol = parts[0]
                rest = parts[1] if len(parts) > 1 else ""
                if "@" in rest:
                    user_pass, host_part = rest.split("@", 1)
                    user = user_pass.split(":", 1)[0] if ":" in user_pass else user_pass
                    masked = f"{protocol}://{user}:****@{host_part}"
                else:
                    masked = f"{protocol}://{rest[:20]}..."
                return ("ansigreen", f"[SET: {masked}]")
            return ("ansigreen", f"[SET: {value[:30]}]")

        state = {"selected": 0}  # index into selectable list
        result_choice = [None]   # will be (kind, field_id)

        def get_text():
            lines = [
                ("bold", "\n  Configuration\n"),
            ]
            if include_data_config:
                lines.append(("dim", "  API keys & database connections for data analysis.\n\n"))
            else:
                lines.append(("dim", "  Configure your API keys to access different model providers.\n\n"))

            sel_idx = 0
            for opt in ALL_OPTIONS:
                kind = opt[0]
                if kind == "separator":
                    lines.append(("dim", "  ─────────────────────────────────────────\n"))
                    lines.append(("bold", "  Database Configuration\n\n"))
                    continue
                _, field_id, name, hint, desc = opt
                status_style, status_text = _status(kind, field_id)
                name_field = f"{name:<22}"
                if sel_idx == state["selected"]:
                    lines.append(("#ff8888 bold reverse", f"  ❯ {name_field}"))
                    lines.append((status_style, f"  {status_text:<45}"))
                    lines.append(("dim italic", f"  {desc}"))
                else:
                    lines.append(("", f"    {name_field}"))
                    lines.append((status_style, f"  {status_text:<45}"))
                    lines.append(("dim", f"  {desc}"))
                lines.append(("", "\n"))
                sel_idx += 1
            lines.append(("", "\n"))
            lines.append(("dim italic", "  ↑ ↓ to navigate · Enter to configure · Esc to close\n"))
            return FormattedText(lines)

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(event):
            if state["selected"] > 0:
                state["selected"] -= 1

        @kb.add("down")
        @kb.add("j")
        def _down(event):
            if state["selected"] < len(selectable) - 1:
                state["selected"] += 1

        @kb.add("enter")
        def _select(event):
            _, opt = selectable[state["selected"]]
            result_choice[0] = (opt[0], opt[1])  # (kind, field_id)
            event.app.exit()

        @kb.add("c-c")
        @kb.add("escape")
        def _cancel(event):
            event.app.exit()

        control = FormattedTextControl(get_text)
        layout = Layout(HSplit([Window(content=control)]))
        Application(layout=layout, key_bindings=kb, full_screen=False).run()

        choice = result_choice[0]
        if not choice:
            console.print("[dim]Configuration unchanged.[/dim]\n")
            return

        kind, selected = choice

        # Find display info
        selected_info = next(o for o in ALL_OPTIONS if o[0] == kind and o[1] == selected)
        _, _, display_name, prefix_hint, _ = selected_info
        current = _current_value(kind, selected)

        # ── Handle API key selection ──
        if kind == "key":
            console.print(f"\n[bold]Configure {display_name} API Key[/bold]")
            if prefix_hint:
                console.print(f"[dim]Expected format: {prefix_hint}...[/dim]")
            if current:
                console.print(f"[dim]Current key: {current[:8]}...{current[-4:]}[/dim]")
                console.print("[dim]Press Enter with no input to clear the key.[/dim]")
            else:
                console.print("[dim]Press Enter with no input to cancel.[/dim]")

            api_key = input("\n  Key > ").strip()

            if not api_key:
                if current:
                    if selected == "openrouter":
                        config._openrouter_api_key = None
                        config.using_own_key = bool(config._openai_api_key or config._anthropic_api_key or config._groq_api_key)
                    elif selected == "openai":
                        config._openai_api_key = None
                    elif selected == "groq":
                        config._groq_api_key = None
                    elif selected == "together":
                        config._together_api_key = None
                    else:
                        config._anthropic_api_key = None
                    config.save_persisted_config()
                    console.print(f"[yellow]✓ {display_name} key cleared.[/yellow]\n")
                else:
                    console.print("[dim]No change made.[/dim]\n")
                return

            if prefix_hint and not api_key.startswith(prefix_hint.rstrip("-")):
                console.print(
                    f"[yellow]Note: {display_name} keys typically start with '{prefix_hint}'[/yellow]"
                )

            if selected == "openrouter":
                config._openrouter_api_key = api_key
                config.using_own_key = True
            elif selected == "openai":
                config._openai_api_key = api_key
            elif selected == "groq":
                config._groq_api_key = api_key
                config.using_own_key = True
            elif selected == "together":
                config._together_api_key = api_key
                config.using_own_key = True
            else:
                config._anthropic_api_key = api_key

            config._agent_mode_changed = True
            config.save_persisted_config()

            console.print(f"\n[bold green]✓[/bold green] {display_name} API key saved.")
            console.print("[dim]Use /model to browse and select a model for this provider.[/dim]\n")

        # ── Handle DB field selection ──
        else:
            console.print(f"\n[bold]Configure {display_name}[/bold]")
            console.print(f"[dim]Example: {prefix_hint}[/dim]")
            if current:
                if selected == "db_password":
                    current_display = "********"
                else:
                    current_display = current[:50] + "..." if len(current) > 50 else current
                console.print(f"[dim]Current: {current_display}[/dim]")
                console.print("[dim]Press Enter with no input to clear/reset the value.[/dim]")
            else:
                console.print("[dim]Press Enter with no input to cancel.[/dim]")

            db_value = input("\n  Value > ").strip()

            if not db_value:
                if current:
                    if selected == "database_url":   config.database_url = ""
                    elif selected == "db_host":      config.db_host = ""
                    elif selected == "db_port":      config.db_port = 5432
                    elif selected == "db_name":      config.db_name = "postgres"
                    elif selected == "db_user":      config.db_user = ""
                    elif selected == "db_password":  config.db_password = ""
                    config.save_persisted_config()
                    console.print(f"[yellow]✓ {display_name} reset to default.[/yellow]\n")
                else:
                    console.print("[dim]No change made.[/dim]\n")
                return

            if selected == "database_url":   config.database_url = db_value
            elif selected == "db_host":      config.db_host = db_value
            elif selected == "db_port":
                try:
                    config.db_port = int(db_value)
                except ValueError:
                    console.print("[red]Invalid port number. Using default 5432.[/red]")
                    config.db_port = 5432
            elif selected == "db_name":      config.db_name = db_value
            elif selected == "db_user":      config.db_user = db_value
            elif selected == "db_password":  config.db_password = db_value

            config.save_persisted_config()

            console.print(f"\n[bold green]✓[/bold green] {display_name} saved.")
            console.print("[dim]Restart your session or reconnect to apply database changes.[/dim]\n")

    def _handle_data_config(self):
        """Handle database configuration for data mode."""
        from config import config
        
        # Database config options for data agent
        DB_OPTIONS = [
            ("database_url", "Database URL", "postgresql://user:pass@host:port/db", "Full SQLAlchemy connection string"),
            ("db_host", "PostgreSQL Host", "localhost", "PostgreSQL server hostname"),
            ("db_port", "PostgreSQL Port", "5432", "PostgreSQL server port"),
            ("db_name", "Database Name", "postgres", "Database to connect to"),
            ("db_user", "Database User", "postgres", "Username for authentication"),
            ("db_password", "Database Password", "********", "Password for authentication"),
        ]

        def _get_db_value(field: str) -> str:
            if field == "database_url":
                return config.database_url or ""
            elif field == "db_host":
                return config.db_host or ""
            elif field == "db_port":
                return str(config.db_port or "5432")
            elif field == "db_name":
                return config.db_name or "postgres"
            elif field == "db_user":
                return config.db_user or ""
            elif field == "db_password":
                return config.db_password or ""
            return ""

        def _db_status(field: str) -> tuple:
            """Return (style, status_text) for a DB config field."""
            value = _get_db_value(field)
            if value:
                if field == "db_password" and value:
                    masked = "********"
                    return ("ansigreen", f"[SET: {masked}]")
                elif field == "database_url":
                    # Show a masked version
                    if "://" in value:
                        parts = value.split("://")
                        protocol = parts[0]
                        rest = parts[1] if len(parts) > 1 else ""
                        if "@" in rest:
                            user_pass, host_part = rest.split("@", 1)
                            if ":" in user_pass:
                                user, _ = user_pass.split(":", 1)
                                masked = f"{protocol}://{user}:****@{host_part}"
                            else:
                                masked = f"{protocol}://{user_pass}@{host_part}"
                        else:
                            masked = f"{protocol}://{rest[:20]}..."
                        return ("ansigreen", f"[SET: {masked}]")
                    return ("ansigreen", f"[SET: {value[:20]}...]")
                return ("ansigreen", f"[SET: {value[:30]}]")
            return ("ansiyellow", "[NOT SET]")

        from prompt_toolkit import Application
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window

        state = {"selected": 0}
        result_field = [None]

        def get_text():
            lines = [
                ("bold", "\n  Data Agent Configuration\n"),
                ("dim", "  Configure database connections for data analysis tools.\n"),
                ("dim", "  Use /mode coding to switch back to API key configuration.\n\n"),
            ]
            for i, (field_id, name, hint, desc) in enumerate(DB_OPTIONS):
                status_style, status_text = _db_status(field_id)
                name_field = f"{name:<22}"
                if i == state["selected"]:
                    lines.append(("#ff8888 bold reverse", f"  ❯ {name_field}"))
                    lines.append((status_style, f"  {status_text:<45}"))
                    lines.append(("dim italic", f"  {desc}"))
                else:
                    lines.append(("", f"    {name_field}"))
                    lines.append((status_style, f"  {status_text:<45}"))
                    lines.append(("dim", f"  {desc}"))
                lines.append(("", "\n"))
            lines.append(("", "\n"))
            lines.append(("dim italic", "  ↑ ↓ to navigate · Enter to configure · Esc to close\n"))
            return FormattedText(lines)

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(event):
            if state["selected"] > 0:
                state["selected"] -= 1

        @kb.add("down")
        @kb.add("j")
        def _down(event):
            if state["selected"] < len(DB_OPTIONS) - 1:
                state["selected"] += 1

        @kb.add("enter")
        def _select(event):
            result_field[0] = DB_OPTIONS[state["selected"]][0]
            event.app.exit()

        @kb.add("c-c")
        @kb.add("escape")
        def _cancel(event):
            event.app.exit()

        control = FormattedTextControl(get_text)
        layout = Layout(HSplit([Window(content=control)]))
        Application(layout=layout, key_bindings=kb, full_screen=False).run()

        selected = result_field[0]
        if not selected:
            console.print("[dim]Configuration unchanged.[/dim]\n")
            return

        # Find display info for selected field
        selected_info = next(o for o in DB_OPTIONS if o[0] == selected)
        _, display_name, hint, _ = selected_info

        console.print(f"\n[bold]Configure {display_name}[/bold]")
        console.print(f"[dim]Example: {hint}[/dim]")
        current = _get_db_value(selected)
        if current:
            if selected == "db_password":
                current_display = "********"
            else:
                current_display = current[:50] + "..." if len(current) > 50 else current
            console.print(f"[dim]Current: {current_display}[/dim]")
            console.print("[dim]Press Enter with no input to clear/reset the value.[/dim]")
        else:
            console.print("[dim]Press Enter with no input to cancel.[/dim]")

        db_value = input("\n  Value > ").strip()

        if not db_value:
            if current:
                # Reset to default or clear
                if selected == "database_url":
                    config.database_url = ""
                elif selected == "db_host":
                    config.db_host = ""
                elif selected == "db_port":
                    config.db_port = 5432
                elif selected == "db_name":
                    config.db_name = "postgres"
                elif selected == "db_user":
                    config.db_user = ""
                elif selected == "db_password":
                    config.db_password = ""
                config.save_persisted_config()
                console.print(f"[yellow]✓ {display_name} reset to default.[/yellow]\n")
            else:
                console.print("[dim]No change made.[/dim]\n")
            return

        # Persist the value
        if selected == "database_url":
            config.database_url = db_value
        elif selected == "db_host":
            config.db_host = db_value
        elif selected == "db_port":
            try:
                config.db_port = int(db_value)
            except ValueError:
                console.print("[red]Invalid port number. Using default 5432.[/red]")
                config.db_port = 5432
        elif selected == "db_name":
            config.db_name = db_value
        elif selected == "db_user":
            config.db_user = db_value
        elif selected == "db_password":
            config.db_password = db_value

        config.save_persisted_config()

        console.print(f"\n[bold green]✓[/bold green] {display_name} saved.")
        console.print("[dim]Restart your session or reconnect to apply database changes.[/dim]\n")

    def handle_mcp(self, user_input: str):
        """Handle /mcp subcommands."""
        parts = user_input.split()
        if len(parts) < 2:
            self.show_mcp_help()
            return

        sub = parts[1].lower()
        if sub == "list":
            self.list_mcp_servers()
        elif sub == "tools" and len(parts) >= 3:
            self.list_mcp_tools(parts[2])
        elif sub == "refresh":
            self.refresh_mcp()
        elif sub == "install" and len(parts) >= 3:
            self.install_mcp_server(parts[2])
        elif sub == "browse":
            self.browse_mcp_registry()
        elif sub == "remove" and len(parts) >= 3:
            self.remove_mcp_server(parts[2])
        elif sub == "help":
            self.show_mcp_help()
        else:
            self.show_mcp_help()

    def show_mcp_help(self):
        help_text = """
[bold #ff8888]MCP COMMANDS[/bold #ff8888]
  /mcp list              List all connected MCP servers and their status
  /mcp tools <server>    List all tools available on a specific server
  /mcp refresh           Reconnect and refresh all MCP servers
  /mcp browse            Show all servers available in the registry
  /mcp install <name>    Install and connect a server from the registry
  /mcp remove <name>     Remove a server from config and disconnect it
  /mcp help              Show this help message

[dim]Config path: ~/.archcode/mcp_servers.json[/dim]
"""
        console.print(Panel(help_text.strip(), title="MCP Help", border_style="#ff8888"))

    def list_mcp_servers(self):
        if not mcp_manager.is_connected():
            console.print("[dim]No MCP servers connected. Check your config at ~/.archcode/mcp_servers.json[/dim]")
            return

        table = Table(title="Connected MCP Servers", border_style="#ff8888")
        table.add_column("Server", style="cyan")
        table.add_column("Tools", justify="right")
        table.add_column("Status", style="green")

        for name, tools in mcp_manager.server_tool_map.items():
            table.add_row(name, str(len(tools)), "connected")

        console.print(table)

    def list_mcp_tools(self, server_name: str):
        tools = mcp_manager.server_tool_map.get(server_name)
        if not tools:
            console.print(f"[red]Error: Server '{server_name}' not found or has no tools.[/red]")
            return

        console.print(f"\n[bold #ff8888]Tools for {server_name}:[/bold #ff8888]")
        for t in tools:
            console.print(f"  • [cyan]{t['name']}[/cyan]: {t.get('description', 'No description')}")
        console.print()

    def install_mcp_server(self, name: str):
        """Interactive install wizard for a registry server."""
        mcp_manager.install_server(name)

    def browse_mcp_registry(self):
        """Show all servers in the registry with installed status."""
        installed = set(mcp_manager.server_tool_map.keys())

        # Also check config for servers that are configured but maybe not connected
        configured = set()
        if mcp_manager.config_path.exists():
            try:
                with open(mcp_manager.config_path, "r") as f:
                    cfg = json.load(f)
                configured = set(cfg.get("mcpServers", {}).keys())
            except Exception:
                pass

        table = Table(title="MCP Server Registry", border_style="#ff8888")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Description")
        table.add_column("Runtime", style="dim")
        table.add_column("Status", justify="center")

        for name, entry in MCP_SERVER_REGISTRY.items():
            if name in installed:
                status = "[green]connected[/green]"
            elif name in configured:
                status = "[yellow]configured[/yellow]"
            else:
                status = "[dim]available[/dim]"
            runtime = "node/npx" if entry.get("requires_node") else "python/uvx"
            table.add_row(name, entry["description"], runtime, status)

        console.print(table)
        console.print("[dim]Install with: /mcp install <name>[/dim]\n")

    def remove_mcp_server(self, name: str):
        """Remove an MCP server from config and disconnect."""
        mcp_manager.remove_server(name)

    def refresh_mcp(self):
        with console.status("[bold #ff8888]●[/bold #ff8888] Refreshing MCP servers...", spinner="dots", spinner_style="#ff8888"):
            try:
                # Cleanup old sessions first, then reconnect
                mcp_manager.cleanup()
                mcp_manager.connect_all_sync()
                if mcp_manager.is_connected():
                    console.print(f"[green]✓[/green] MCP refreshed: {mcp_manager.get_summary()}\n")
                else:
                    console.print("[yellow]! MCP refreshed but no servers connected.[/yellow]\n")
            except Exception as e:
                console.print(f"[red]Error refreshing MCP: {e}[/red]\n")