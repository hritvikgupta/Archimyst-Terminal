import os
import json
from pathlib import Path
from rich.console import Console

# Global rich console for consistent output
console = Console()

class Config:
    def __init__(self):
        self.config_dir = Path.home() / ".archcode"
        self.config_file = self.config_dir / "config.json"
        
        # Versioning
        self.version = "1.2.1"
        self.new_version_available = None # Stores version dict if update available
        
        # Defaults (internal storage)
        self._openrouter_api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("VITE_OPENROUTER_API_KEY")
        self._voyage_api_key = os.getenv("VOYAGE_API_KEY") or os.getenv("VITE_VOYAGE_API_KEY")
        self._tavily_api_key = os.getenv("TAVILY_API_KEY") or os.getenv("VITE_TAVILY_API_KEY")
        self._openai_api_key = os.getenv("OPENAI_API_KEY")
        self._anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        self._groq_api_key = os.getenv("GROQ_API_KEY")
        
        # Secrets synced from backend (in-memory only)
        self.synced_env_vars = {}
        
        self.model = "moonshotai/kimi-k2.5"
        self.mode = "free" 
        self.access_token = None
        self.user_email = None
        
        # Token Usage Stats
        self.token_usage = 0
        self.token_limit = 50000
        self.is_blocked = False
        
        # Using own API key mode - no token limits, no usage reporting
        self.using_own_key = False

        self.model_map = {
            "supervisor": "moonshotai/kimi-k2.5",
            "coder": "moonshotai/kimi-k2.5",
            "reviewer": "x-ai/grok-4.1-fast",
            "executor": "x-ai/grok-4.1-fast"
        }

        # Available models list (persistent)
        self.available_models = [
            ("moonshotai/kimi-k2.5",       "Kimi K2.5       — default fast coder"),
            ("z-ai/glm-4.7",               "GLM-4.7         — Z.ai"),
            ("openai/gpt-oss-120b",         "GPT-OSS 120B    — OpenAI open-source"),
            ("qwen/qwen3-coder-next",       "Qwen3-Coder-Next — Alibaba"),
            ("x-ai/grok-code-fast-1",        "Grok-Code-Fast-1    — X-AI"),
        ]

        # Load persisted config if exists
        self.load_persisted_config()

    def load_persisted_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.user_email = data.get("user_email")
                    # if data.get("model"): self.model = data.get("model")
                    if data.get("mode"): self.mode = data.get("mode")
                    if data.get("env_vars"): self.synced_env_vars = data.get("env_vars")
                    if data.get("available_models"): self.available_models = data.get("available_models")
                    # Load API keys (env vars take priority; file fills in when env var absent)
                    if not self._openrouter_api_key:
                        self._openrouter_api_key = data.get("openrouter_api_key")
                    if not self._openai_api_key:
                        self._openai_api_key = data.get("openai_api_key")
                    if not self._anthropic_api_key:
                        self._anthropic_api_key = data.get("anthropic_api_key")
                    if not self._groq_api_key:
                        self._groq_api_key = data.get("groq_api_key")
            except Exception as e:
                console.print(f"[dim]Warning: Could not load config file: {e}[/dim]")

    def save_persisted_config(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "access_token": self.access_token,
            "user_email": self.user_email,
            "model": self.model,
            "mode": self.mode,
            "env_vars": self.synced_env_vars,
            "available_models": self.available_models,
            "openrouter_api_key": self._openrouter_api_key,
            "openai_api_key": self._openai_api_key,
            "anthropic_api_key": self._anthropic_api_key,
            "groq_api_key": self._groq_api_key,
        }
        try:
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=4)
            os.chmod(self.config_file, 0o600)
        except Exception as e:
            console.print(f"[bold red]Error saving config: {e}[/bold red]")

    @property
    def openrouter_api_key(self):
        return self.synced_env_vars.get("OPENROUTER_API_KEY") or self._openrouter_api_key

    @property
    def voyage_api_key(self):
        return self.synced_env_vars.get("VOYAGE_API_KEY") or self._voyage_api_key

    @property
    def tavily_api_key(self):
        return self.synced_env_vars.get("TAVILY_API_KEY") or self._tavily_api_key

    @property
    def openai_api_key(self):
        return self._openai_api_key

    @property
    def anthropic_api_key(self):
        return self._anthropic_api_key

    @property
    def groq_api_key(self):
        return self._groq_api_key

    # Groq model IDs that should route through the Groq API
    GROQ_MODEL_IDS = {
        "meta-llama/llama-prompt-guard-2-86m",
        "qwen/qwen3-32b",
        "meta-llama/llama-guard-4-12b",
        "openai/gpt-oss-20b",
        "groq/compound-mini",
        "whisper-large-v3",
        "openai/gpt-oss-120b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama-3.3-70b-versatile",
        "moonshotai/kimi-k2-instruct",
        "canopylabs/orpheus-v1-english",
        "allam-2-7b",
        "whisper-large-v3-turbo",
        "openai/gpt-oss-safeguard-20b",
        "meta-llama/llama-prompt-guard-2-22m",
        "llama-3.1-8b-instant",
        "moonshotai/kimi-k2-instruct-0905",
        "canopylabs/orpheus-arabic-saudi",
        "groq/compound",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
    }

    @property
    def active_provider(self) -> str:
        """Determine which backend to use for the current model.

        Returns 'anthropic', 'openai', 'groq', or 'openrouter'.
        """
        m = self.model or ""
        if self._anthropic_api_key and (
            m.startswith("claude-") or m.startswith("anthropic.")
        ):
            return "anthropic"
        if self._openai_api_key and m.startswith("gpt-"):
            return "openai"
        if self._groq_api_key and m in self.GROQ_MODEL_IDS:
            return "groq"
        return "openrouter"

    def validate(self):
        # Check if user has their own API key from environment
        if self._openrouter_api_key:
            self.using_own_key = True
            # Show which env var is being used
            env_source = "OPENROUTER_API_KEY" if os.getenv("OPENROUTER_API_KEY") else \
                        "VITE_OPENROUTER_API_KEY" if os.getenv("VITE_OPENROUTER_API_KEY") else "environment"
            console.print(f"[bold green]✓[/bold green] Using your own OpenRouter API key from [cyan]{env_source}[/cyan].")
            console.print("[dim]No token limits. No usage data stored. Private mode active.[/dim]\n")
            return True

        # Check for Groq API key
        if self._groq_api_key:
            self.using_own_key = True
            console.print(f"[bold green]✓[/bold green] Using your own Groq API key.")
            console.print("[dim]No token limits. No usage data stored. Private mode active.[/dim]\n")
            return True

        # Check for OpenAI / Anthropic direct keys — no OpenRouter needed
        if self._openai_api_key or self._anthropic_api_key:
            self.using_own_key = True
            active = []
            if self._openai_api_key:
                active.append("OpenAI")
            if self._anthropic_api_key:
                active.append("Anthropic")
            console.print(
                f"[bold green]✓[/bold green] Direct API keys configured: "
                f"[cyan]{', '.join(active)}[/cyan]."
            )
            console.print("[dim]Use /model to select a model · /config to manage keys.[/dim]\n")
            return True

        # Check if logged in via backend
        if self.access_token:
            self.using_own_key = False
            return True
        
        # Neither API key nor access token - show interactive prompt
        console.print("[bold yellow]Welcome to ArchCode![/bold yellow]\n")
        console.print("[dim]Choose how you want to use ArchCode:[/dim]\n")
        console.print("  [1] [bold #ff8888]/login[/bold #ff8888]     — Login with your Archimyst account (managed usage)")
        console.print("  [2] [bold #ff8888]Use my key[/bold #ff8888] — Use your own OpenRouter API key (unlimited, private)")
        console.print("  [3] [bold #ff8888]Skip[/bold #ff8888]       — Continue without authentication (limited features)\n")
        
        choice = input("Enter choice [1/2/3]: ").strip()
        
        if choice == "1":
            console.print("\n[dim]Type /login when ready to authenticate.[/dim]\n")
            return True
        
        elif choice == "2":
            console.print("\n[dim]Enter your OpenRouter API key (sk-or-...):[/dim]")
            api_key = input("> ").strip()
            
            if not api_key:
                console.print("[yellow]No key provided. Continuing in limited mode.[/yellow]\n")
                return True
            
            if not api_key.startswith("sk-or-"):
                console.print("[yellow]Warning: OpenRouter keys typically start with 'sk-or-'[/yellow]")
                confirm = input("Continue anyway? [y/N]: ").strip().lower()
                if confirm != 'y':
                    console.print("[dim]Cancelled. Type /login to authenticate.[/dim]\n")
                    return True
            
            # Store the API key for this session only (not persisted)
            self._openrouter_api_key = api_key
            self.using_own_key = True
            console.print("[bold green]✓[/bold green] API key accepted!")
            console.print("[dim]Supported providers: OpenRouter (with 200+ models)[/dim]")
            console.print("[dim]No token limits. No usage data stored. Private mode activated.[/dim]\n")
            return True
        
        elif choice == "3":
            console.print("\n[dim]Continuing in limited mode. Type /login anytime to authenticate.[/dim]\n")
            return True
        
        else:
            console.print("\n[dim]Invalid choice. Type /login to authenticate when ready.[/dim]\n")
            return True

config = Config()
