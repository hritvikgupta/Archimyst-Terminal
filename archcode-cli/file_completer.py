"""
file_completer.py — Custom prompt_toolkit completer for @file references.

When the user types '@' in the CLI prompt, this completer provides a dropdown
of all files and folders in the current project root, allowing navigation
and selection. The selected path is inserted as @path/to/file in the input.

Key behavior:
- Selecting a FOLDER from dropdown → inserts folder path, re-triggers completion
  to show contents (does NOT submit)
- Selecting a FILE from dropdown → inserts file path, closes menu, user keeps typing
- Enter with no completion active → submits normally

This does NOT touch or interfere with the existing slash-command completer.
"""

import os
from prompt_toolkit.completion import Completer, Completion, CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import has_completions, completion_is_selected
from prompt_toolkit.formatted_text import HTML


# Directories to always skip when scanning
IGNORED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".archcode",
    "venv",
    ".venv",
    ".env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".egg-info",
    ".idea",
    ".vscode",
}

# Max depth to recurse into the project tree
MAX_DEPTH = 5


def _scan_project_files(root: str, max_depth: int = MAX_DEPTH):
    """
    Walk the project root and return a sorted list of relative file/folder paths.
    Folders end with '/'.
    """
    results = []
    root = os.path.abspath(root)

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            depth = 0
        else:
            depth = rel_dir.count(os.sep) + 1

        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in IGNORED_DIRS and not d.startswith(".")
        ]

        if depth >= max_depth:
            dirnames.clear()
            continue

        for d in dirnames:
            rel_path = os.path.relpath(os.path.join(dirpath, d), root)
            results.append(rel_path + "/")

        for f in sorted(filenames):
            if f.startswith("."):
                continue
            rel_path = os.path.relpath(os.path.join(dirpath, f), root)
            results.append(rel_path)

    return results


class SlashCommandCompleter(Completer):
    """
    Custom completer for slash commands with descriptions.
    Shows all commands when '/' is typed.
    Also completes subcommands for /mcp, /model, and /config.
    """
    COMMANDS = {
        "/shortcuts": "Keyboard shortcuts & useful tips",
        "/rewind": "Browse and restore previous checkpoints",
        "/clear": "Clear terminal output for better focus",
        "/reset": "Reset conversation history and context",
        "/login": "Sign in to your Archimyst workspace",
        "/logout": "Clear local authentication data",
        "/status": "View current model, session, and token info",
        "/config": "Configure API keys for model providers",
        "/upgrade": "Get more tokens or upgrade plan",
        "/update": "Install the latest version of ArchCode",
        "/model": "Switch between available AI models",
        "/skills": "Search, list, and manage agent skills",
        "/mcp": "Manage MCP server connections and tools",
        "/tasks": "Monitor background task progress",
        "/task": "Submit a long-running background task",
        "/help": "View detailed usage guide",
        "/revert": "Undo changes to a specific file",
        "exit": "Safely close the terminal session",
        "quit": "Safely close the terminal session",
        "?": "Quick help overview"
    }

    MODEL_SUBCOMMANDS = {
        "providers": "List all available model providers",
        "provider": "Browse models by provider"
    }

    CONFIG_SUBCOMMANDS = {
        "openrouter": "Configure OpenRouter API key",
        "openai": "Configure OpenAI API key", 
        "anthropic": "Configure Anthropic API key",
        "groq": "Configure Groq API key"
    }

    MCP_SUBCOMMANDS = {
        "list":    "List all connected MCP servers",
        "tools":   "List tools for a specific server",
        "refresh": "Reconnect and refresh all MCP servers",
        "browse":  "Show all servers available in the registry",
        "install": "Install a server from the registry",
        "remove":  "Remove a server from config and disconnect",
        "help":    "Show MCP help message",
    }

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor.lstrip()

        # /mcp subcommand completion: "/mcp <partial-sub>"
        if text.startswith("/mcp "):
            after_mcp = text[len("/mcp "):]
            for sub, desc in self.MCP_SUBCOMMANDS.items():
                if sub.startswith(after_mcp):
                    yield Completion(
                        text=sub,
                        start_position=-len(after_mcp),
                        display=sub,
                        display_meta=desc,
                    )
            return

        # /model subcommand completion: "/model <partial-sub>"
        if text.startswith("/model "):
            after_model = text[len("/model "):]
            # Check for provider subcommands like "/model/provider/openai"
            if after_model.startswith("provider/"):
                provider_part = after_model[len("provider/"):]
                # Common providers that users might type
                providers = ["openai", "anthropic", "groq", "openrouter", "google", "mistral", "cohere"]
                for provider in providers:
                    if provider.startswith(provider_part):
                        full_text = f"provider/{provider}"
                        yield Completion(
                            text=full_text,
                            start_position=-len(after_model),
                            display=full_text,
                            display_meta=f"Browse models from {provider} provider"
                        )
            else:
                # Regular model subcommands
                for sub, desc in self.MODEL_SUBCOMMANDS.items():
                    if sub.startswith(after_model):
                        yield Completion(
                            text=sub,
                            start_position=-len(after_model),
                            display=sub,
                            display_meta=desc,
                        )
                # Also allow direct model names (fallback)
                if not any(sub.startswith(after_model) for sub in self.MODEL_SUBCOMMANDS.keys()):
                    # This would be enhanced with actual model names from the current session
                    pass
            return

        # /config subcommand completion: "/config <partial-sub>"
        if text.startswith("/config "):
            after_config = text[len("/config "):]
            for sub, desc in self.CONFIG_SUBCOMMANDS.items():
                if sub.startswith(after_config):
                    yield Completion(
                        text=sub,
                        start_position=-len(after_config),
                        display=sub,
                        display_meta=desc,
                    )
            return

        # Only trigger at the start of the line for top-level commands
        if not text.startswith("/") and text not in ("exit", "quit", "?"):
            if text and any(cmd.startswith(text) for cmd in ("exit", "quit")):
                pass  # Continue
            else:
                return

        for cmd, desc in self.COMMANDS.items():
            if cmd.startswith(text):
                yield Completion(
                    text=cmd,
                    start_position=-len(text),
                    display=cmd,
                    display_meta=desc
                )


class ArchimystCompleter(Completer):
    """
    Unified completer that manages slash commands and @file completions.
    Ensures they don't interfere with each other.
    """
    def __init__(self, slash_completer, at_file_completer):
        self.slash_completer = slash_completer
        self.at_file_completer = at_file_completer

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor
        
        # Priority 1: @file references (anywhere in line)
        at_pos = text.rfind("@")
        if at_pos != -1:
            if at_pos == 0 or text[at_pos - 1].isspace():
                yield from self.at_file_completer.get_completions(document, complete_event)
                # If we are doing file completion, we don't want slash commands showing up
                # unless the @ is preceded by something that doesn't look like a file path
                return
        
        # Priority 2: Slash commands (only at the start of the line)
        if text.lstrip().startswith("/") or text.lstrip() in ("", "e", "ex", "exi", "q", "qu", "qui", "?"):
            yield from self.slash_completer.get_completions(document, complete_event)


class AtFileCompleter(Completer):
    """
    A prompt_toolkit Completer that activates when the user types '@'.
    Scans project root for files/folders and presents them in completion dropdown.
    """

    def __init__(self, project_root: str = None):
        self.project_root = project_root or os.getcwd()
        self._cached_files = None
        self._cache_time = 0

    def _get_files(self):
        import time
        now = time.time()
        if self._cached_files is None or (now - self._cache_time) > 5:
            self._cached_files = _scan_project_files(self.project_root)
            self._cache_time = now
        return self._cached_files

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text_before_cursor = document.text_before_cursor

        # Find the last '@' trigger point
        at_pos = text_before_cursor.rfind("@")
        if at_pos == -1:
            return

        # Double check trigger validity
        if at_pos > 0 and not text_before_cursor[at_pos - 1].isspace():
            return

        # Text after the '@' to match against
        partial = text_before_cursor[at_pos + 1:]
        
        files = self._get_files()
        for filepath in files:
            if partial == "" or filepath.lower().startswith(partial.lower()):
                is_dir = filepath.endswith("/")
                display_meta = "📁 folder" if is_dir else (os.path.splitext(filepath)[1] or "file")

                yield Completion(
                    text=filepath,
                    # Replace everything from the '@' onwards
                    start_position=-len(partial),
                    display=filepath,
                    display_meta=display_meta,
                )


def get_at_file_key_bindings():
    """
    Custom key bindings for @file completion behavior:
    - Enter + folder selected → accept completion, re-trigger menu (don't submit)
    - Enter + file selected → accept completion + space (don't submit)
    - Enter + no completion → submit normally
    """
    kb = KeyBindings()

    @kb.add(Keys.Enter, filter=has_completions & completion_is_selected)
    def _handle_completion_enter(event):
        buf = event.current_buffer
        state = buf.complete_state
        if not state or not state.current_completion:
            return

        # Apply the completion and close the menu
        current_completion = state.current_completion
        buf.apply_completion(current_completion)
        buf.complete_state = None

        # Determine if we should add a space or drill down
        # We check the completion text itself to be sure
        if current_completion.text.endswith("/"):
            # Folder — re-open completion to drill into it
            buf.start_completion()
        else:
            # File — add space, let user keep typing their message
            buf.insert_text(" ")

    @kb.add(Keys.Tab, filter=has_completions)
    def _handle_tab(event):
        event.current_buffer.complete_next()

    @kb.add(Keys.BackTab, filter=has_completions)
    def _handle_shift_tab(event):
        event.current_buffer.complete_previous()

    return kb


def parse_at_file_references(user_input: str, project_root: str = None):
    """
    Scan user input for @path/to/file references, read file contents,
    and return (cleaned_input, file_context_string).
    """
    import re

    root = project_root or os.getcwd()

    pattern = r"@([\w./\-]+)"
    matches = re.findall(pattern, user_input)

    if not matches:
        return user_input, ""

    file_blocks = []
    seen = set()

    for match in matches:
        filepath = os.path.normpath(os.path.join(root, match))

        if not filepath.startswith(os.path.abspath(root)):
            continue

        if filepath in seen:
            continue
        seen.add(filepath)

        if os.path.isdir(filepath):
            continue

        if os.path.isfile(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                rel_path = os.path.relpath(filepath, root)
                file_blocks.append(
                    f"\n--- Referenced File: {rel_path} ---\n"
                    f"```\n{content}\n```"
                )
            except Exception:
                continue

    file_context = "\n".join(file_blocks) if file_blocks else ""
    return user_input, file_context