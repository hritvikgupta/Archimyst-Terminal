import os
import json
import asyncio
import threading
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from rich.console import Console

# Try to import MCP and LangChain, handle missing dependencies gracefully
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    ClientSession = None
    stdio_client = None

# pydantic is still used for schema introspection of MCP tool params
try:
    from pydantic import create_model, Field
except ImportError:
    create_model = None

console = Console()

# ---------------------------------------------------------------------------
# Curated registry of popular MCP servers
# ---------------------------------------------------------------------------
MCP_SERVER_REGISTRY = {
    "filesystem": {
        "description": "Read/write any local files and directories",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{path}"],
        "setup_args": [{"name": "path", "prompt": "Which directory to expose?", "default": str(Path.home())}],
        "requires_node": True,
    },
    "github": {
        "description": "GitHub issues, PRs, repos, branches",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_required": {"GITHUB_TOKEN": "GitHub personal access token (repo scope)"},
        "requires_node": True,
    },
    "postgres": {
        "description": "Query any PostgreSQL database",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "{connection_string}"],
        "setup_args": [{"name": "connection_string", "prompt": "Postgres connection string?", "default": "postgresql://localhost/mydb"}],
        "requires_node": True,
    },
    "sqlite": {
        "description": "Query SQLite database files",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "{db_path}"],
        "setup_args": [{"name": "db_path", "prompt": "Path to .db file?", "default": "./db.sqlite"}],
        "requires_node": True,
    },
    "brave-search": {
        "description": "Web search via Brave Search API",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env_required": {"BRAVE_API_KEY": "Brave Search API key (free tier available)"},
        "requires_node": True,
    },
    "puppeteer": {
        "description": "Browser automation and web scraping",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "requires_node": True,
    },
    "slack": {
        "description": "Read/send Slack messages and channels",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env_required": {
            "SLACK_BOT_TOKEN": "Slack Bot Token",
            "SLACK_TEAM_ID": "Slack Team ID",
        },
        "requires_node": True,
    },
    "memory": {
        "description": "Persistent memory/knowledge graph across sessions",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "requires_node": True,
    },
    "time": {
        "description": "Get current time and convert between timezones",
        "command": "uvx",
        "args": ["mcp-server-time"],
        "requires_node": False,
    },
    "fetch": {
        "description": "Fetch web pages and convert to markdown",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "requires_node": False,
    },
    "git": {
        "description": "Git operations on local repos",
        "command": "uvx",
        "args": ["mcp-server-git", "--repository", "{repo_path}"],
        "setup_args": [{"name": "repo_path", "prompt": "Path to git repo?", "default": "."}],
        "requires_node": False,
    },
}


class MCPManager:
    def __init__(self):
        self.config_path = Path.home() / ".archcode" / "mcp_servers.json"
        self.sessions: Dict[str, Any] = {}
        self.tools: List[Any] = []
        self.server_tool_map: Dict[str, List[Dict[str, Any]]] = {}

        # Background thread + event loop for persistent sessions
        self._bg_loop: Optional[asyncio.AbstractEventLoop] = None
        self._bg_thread: Optional[threading.Thread] = None
        self._stop_events: Dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # Background thread management
    # ------------------------------------------------------------------

    def _start_bg_thread(self):
        """Start a daemon thread that runs an event loop forever."""
        if self._bg_thread is not None and self._bg_thread.is_alive():
            return

        self._bg_loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self._bg_loop)
            self._bg_loop.run_forever()

        self._bg_thread = threading.Thread(target=_run, daemon=True, name="mcp-bg-loop")
        self._bg_thread.start()

    # ------------------------------------------------------------------
    # Public connect entry-point (synchronous, called from cli.py)
    # ------------------------------------------------------------------

    def connect_all_sync(self, timeout: float = 15.0):
        """Start the bg thread and connect to all configured MCP servers.

        Blocks until all servers have connected (or timeout elapses).
        Safe to call from the main thread even when no async loop is running.
        """
        if not self.config_path.exists():
            return

        if ClientSession is None:
            if not self._ensure_mcp_sdk():
                return

        self._start_bg_thread()

        future = asyncio.run_coroutine_threadsafe(self.connect_all(), self._bg_loop)
        try:
            future.result(timeout=timeout)
        except TimeoutError:
            console.print("[dim yellow]MCP: some servers took too long to connect[/dim yellow]")
        except Exception as e:
            console.print(f"[dim red]MCP connect error: {e}[/dim red]")

    # ------------------------------------------------------------------
    # Async connect helpers (run inside bg loop)
    # ------------------------------------------------------------------

    async def connect_all(self):
        """Connect to all configured MCP servers (runs in bg loop)."""
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)
        except Exception as e:
            console.print(f"[dim red]Error reading MCP config: {e}[/dim red]")
            return

        servers = config.get("mcpServers", {})
        if not servers:
            return

        # Launch all server coroutines as background tasks (they stay open)
        tasks = []
        for name, cfg in servers.items():
            stop_event = asyncio.Event()
            self._stop_events[name] = stop_event
            task = asyncio.ensure_future(self._run_server(name, cfg, stop_event))
            tasks.append((name, task))

        # Wait until each session is initialised (or fails)
        deadline = asyncio.get_event_loop().time() + 12.0
        for name, _ in tasks:
            while name not in self.sessions:
                if asyncio.get_event_loop().time() > deadline:
                    break
                await asyncio.sleep(0.2)

    async def _run_server(self, name: str, cfg: Dict[str, Any], stop_event: asyncio.Event):
        """Long-running coroutine: opens an MCP stdio session and keeps it alive."""
        command = cfg.get("command")
        args = cfg.get("args", [])
        env = os.environ.copy()
        if "env" in cfg:
            env.update(cfg["env"])

        params = StdioServerParameters(command=command, args=args, env=env)

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.sessions[name] = session

                    # Enumerate tools
                    result = await session.list_tools()
                    wrapped_tools = []
                    tool_info_list = []
                    for tool in result.tools:
                        wrapped = self._wrap_tool(name, tool)
                        if wrapped:
                            wrapped_tools.append(wrapped)
                            tool_info_list.append({
                                "name": tool.name,
                                "description": tool.description,
                            })

                    self.tools.extend(wrapped_tools)
                    self.server_tool_map[name] = tool_info_list

                    # Stay open until stop_event is set
                    await stop_event.wait()

        except Exception as e:
            console.print(f"[dim red]MCP server '{name}' error: {e}[/dim red]")
        finally:
            self.sessions.pop(name, None)

    # ------------------------------------------------------------------
    # Synchronous tool call (main thread → bg loop via threadsafe bridge)
    # ------------------------------------------------------------------

    def _call_tool_sync(self, server_name: str, tool_name: str, kwargs: dict) -> str:
        """Call an MCP tool synchronously from any thread."""
        session = self.sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' not connected."

        if self._bg_loop is None or not self._bg_loop.is_running():
            return f"Error: MCP background loop not running."

        async def _call():
            result = await session.call_tool(tool_name, kwargs)
            if hasattr(result, "content"):
                return "\n".join(
                    c.text for c in result.content if hasattr(c, "text")
                )
            return str(result)

        future = asyncio.run_coroutine_threadsafe(_call(), self._bg_loop)
        try:
            return future.result(timeout=60)
        except TimeoutError:
            return f"Error: Tool '{tool_name}' timed out after 60 seconds."
        except Exception as e:
            return f"Error calling tool '{tool_name}': {e}"

    # ------------------------------------------------------------------
    # LangChain tool wrapping
    # ------------------------------------------------------------------

    def _wrap_tool(self, server_name: str, tool: Any) -> Optional[Any]:
        """Wrap an MCP tool as a plain callable function for Agno.

        Creates a function with proper __name__, __doc__, and type hints
        so Agno can register it as a tool automatically.
        """
        import inspect

        # Capture by value for closure correctness
        _server = server_name
        _tool_name = tool.name

        # Build parameter info from JSON schema
        properties = {}
        if hasattr(tool, 'inputSchema') and tool.inputSchema:
            properties = tool.inputSchema.get("properties", {})

        def call_tool_sync(**kwargs) -> str:
            return self._call_tool_sync(_server, _tool_name, kwargs)

        # Set proper metadata for Agno's tool introspection
        call_tool_sync.__name__ = f"mcp__{server_name}__{tool.name}"
        call_tool_sync.__doc__ = (
            f"[MCP:{server_name}] {tool.description or tool.name}"
        )

        # Build __annotations__ from schema for Agno parameter detection
        annotations = {"return": str}
        for prop_name, prop_info in properties.items():
            prop_type = prop_info.get("type", "string")
            if prop_type == "integer":
                annotations[prop_name] = int
            elif prop_type == "boolean":
                annotations[prop_name] = bool
            else:
                annotations[prop_name] = str
        call_tool_sync.__annotations__ = annotations

        return call_tool_sync

    # ------------------------------------------------------------------
    # Dependency helpers
    # ------------------------------------------------------------------

    def _ensure_mcp_sdk(self) -> bool:
        """Auto-install the MCP Python SDK if not present. Returns True if available."""
        global ClientSession, stdio_client
        try:
            from mcp import ClientSession as _CS, StdioServerParameters as _SP
            from mcp.client.stdio import stdio_client as _SC
            ClientSession = _CS
            stdio_client = _SC
            return True
        except ImportError:
            pass

        console.print("[dim]Installing MCP SDK...[/dim]")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "mcp", "pydantic>=2.7", "--quiet"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Failed to install MCP SDK: {result.stderr.strip()}[/red]")
            return False

        # Force a fresh import after upgrade
        for mod in list(sys.modules.keys()):
            if mod.startswith("mcp") or mod.startswith("pydantic"):
                sys.modules.pop(mod, None)

        try:
            from mcp import ClientSession as _CS
            from mcp.client.stdio import stdio_client as _SC
            ClientSession = _CS
            stdio_client = _SC
            console.print("[green]✓[/green] MCP SDK installed.")
            return True
        except ImportError as e:
            console.print(f"[red]MCP SDK installed but failed to import: {e}[/red]")
            return False

    def _ensure_uvx(self) -> bool:
        """Auto-install uv (provides uvx) if not present. Returns True if available."""
        if subprocess.run(["which", "uvx"], capture_output=True).returncode == 0:
            return True

        console.print("[dim]Installing uv (provides uvx)...[/dim]")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "uv", "--quiet"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Failed to install uv: {result.stderr.strip()}[/red]")
            return False

        if subprocess.run(["uvx", "--version"], capture_output=True).returncode == 0:
            console.print("[green]✓[/green] uv installed.")
            return True

        console.print("[green]✓[/green] uv installed (use 'python -m uvx' if uvx not on PATH).")
        return True

    def _ensure_node(self) -> bool:
        """Check that node/npx are available. Returns True if present."""
        if subprocess.run(["which", "npx"], capture_output=True).returncode == 0:
            return True

        console.print(
            "[yellow]Node.js / npx is required for this server but was not found.[/yellow]\n"
            "[dim]Install it from https://nodejs.org (LTS) or via your package manager:[/dim]\n"
            "[dim]  brew install node   # macOS[/dim]\n"
            "[dim]  apt install nodejs  # Debian/Ubuntu[/dim]\n"
        )
        return False

    # ------------------------------------------------------------------
    # Registry / install
    # ------------------------------------------------------------------

    def install_server(self, name: str) -> bool:
        """Interactive wizard: prompt for args/env, write config, connect."""
        entry = MCP_SERVER_REGISTRY.get(name)
        if not entry:
            console.print(f"[red]Unknown server '{name}'. Run /mcp browse to see available servers.[/red]")
            return False

        console.print(f"\n[bold #ff8888]Installing MCP server: {name}[/bold #ff8888]")
        console.print(f"[dim]{entry['description']}[/dim]\n")

        # --- Auto-install dependencies ---
        if not self._ensure_mcp_sdk():
            return False

        if entry.get("requires_node"):
            if not self._ensure_node():
                return False
        else:
            if not self._ensure_uvx():
                return False

        # Collect setup_args (path substitutions in command args)
        collected: Dict[str, str] = {}
        for arg_def in entry.get("setup_args", []):
            arg_name = arg_def["name"]
            prompt_text = arg_def["prompt"]
            default = arg_def.get("default", "")
            user_val = input(f"  {prompt_text} [{default}]: ").strip()
            collected[arg_name] = user_val if user_val else default

        # Collect required env vars
        env_vals: Dict[str, str] = {}
        for env_key, env_desc in entry.get("env_required", {}).items():
            existing = os.environ.get(env_key, "")
            if existing:
                console.print(f"  [dim]{env_key} already set in environment — using it.[/dim]")
                env_vals[env_key] = existing
            else:
                val = input(f"  {env_desc}\n  {env_key}: ").strip()
                if not val:
                    console.print(f"[yellow]Warning: {env_key} left empty.[/yellow]")
                env_vals[env_key] = val

        # Build the final args list with substitutions
        final_args = []
        for arg in entry["args"]:
            for k, v in collected.items():
                arg = arg.replace(f"{{{k}}}", v)
            final_args.append(arg)

        # Write to config
        config: Dict[str, Any] = {"mcpServers": {}}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    config = json.load(f)
            except Exception:
                pass

        server_cfg: Dict[str, Any] = {
            "command": entry["command"],
            "args": final_args,
        }
        if env_vals:
            server_cfg["env"] = env_vals

        config.setdefault("mcpServers", {})[name] = server_cfg
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        console.print(f"[green]✓[/green] Config written to {self.config_path}")

        # Connect immediately
        console.print(f"[dim]Connecting to {name}...[/dim]")
        self.connect_all_sync(timeout=15.0)
        if name in self.sessions:
            console.print(f"[green]✓[/green] {name} connected with {len(self.server_tool_map.get(name, []))} tools.")
            return True
        else:
            console.print(f"[yellow]! {name} config saved but failed to connect right now. Try /mcp refresh.[/yellow]")
            return False

    def remove_server(self, name: str) -> bool:
        """Remove a server from config and disconnect it."""
        if name in self._stop_events:
            if self._bg_loop and self._bg_loop.is_running():
                self._bg_loop.call_soon_threadsafe(self._stop_events[name].set)
            del self._stop_events[name]

        self.tools = [t for t in self.tools if not t.name.startswith(f"mcp__{name}__")]
        self.server_tool_map.pop(name, None)

        if not self.config_path.exists():
            console.print(f"[yellow]Server '{name}' not found in config.[/yellow]")
            return False

        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)
        except Exception as e:
            console.print(f"[red]Error reading config: {e}[/red]")
            return False

        servers = config.get("mcpServers", {})
        if name not in servers:
            console.print(f"[yellow]Server '{name}' not found in config.[/yellow]")
            return False

        del servers[name]
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        console.print(f"[green]✓[/green] Server '{name}' removed.")
        return True

    # ------------------------------------------------------------------
    # Utility / info
    # ------------------------------------------------------------------

    def get_tools(self) -> List[Any]:
        return self.tools

    def get_summary(self) -> str:
        if not self.server_tool_map:
            return "No servers connected"
        return " | ".join(
            f"{name} ({len(tools)} tools)" for name, tools in self.server_tool_map.items()
        )

    def is_connected(self) -> bool:
        return len(self.sessions) > 0

    def cleanup(self):
        """Signal all bg server tasks to stop and wait for the thread."""
        if self._bg_loop and self._bg_loop.is_running():
            for event in self._stop_events.values():
                self._bg_loop.call_soon_threadsafe(event.set)

        self.sessions.clear()
        self.tools.clear()
        self.server_tool_map.clear()
        self._stop_events.clear()

        if self._bg_loop:
            self._bg_loop.call_soon_threadsafe(self._bg_loop.stop)
        if self._bg_thread and self._bg_thread.is_alive():
            self._bg_thread.join(timeout=5)

        self._bg_loop = None
        self._bg_thread = None


# Singleton instance
mcp_manager = MCPManager()
