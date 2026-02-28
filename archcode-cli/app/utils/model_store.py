"""
Model store utility for managing user-selected models and provider data.
Loads models from OpenRouter JSON and persists user selections.
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from rich.console import Console
from app.utils import get_resource_path

console = Console()

DEFAULT_MODELS = [
    "moonshotai/kimi-k2.5",
    "z-ai/glm-4.7",
    "openai/gpt-oss-120b",
    "qwen/qwen3-coder-next",
    "x-ai/grok-code-fast-1",
]

# Direct OpenAI models (used when OPENAI_API_KEY is configured)
OPENAI_DIRECT_MODELS = [
    ("gpt-oss-120b",           "GPT-OSS 120B        — OpenAI open-source"),
    ("gpt-5-2025-08-07",       "GPT-5               — OpenAI"),
    ("gpt-4.1-2025-04-14",     "GPT-4.1             — OpenAI"),
    ("gpt-5-nano-2025-08-07",  "GPT-5 Nano          — OpenAI"),
    ("gpt-5.2-pro-2025-12-11", "GPT-5.2 Pro         — OpenAI"),
    ("gpt-5.2-2025-12-11",     "GPT-5.2             — OpenAI"),
]

# Direct Anthropic models (used when ANTHROPIC_API_KEY is configured)
ANTHROPIC_DIRECT_MODELS = [
    ("claude-opus-4-6",                          "Claude Opus 4.6              — Anthropic"),
    ("claude-sonnet-4-6",                        "Claude Sonnet 4.6            — Anthropic"),
    ("claude-haiku-4-5",                         "Claude Haiku 4.5             — Anthropic"),
    ("claude-haiku-4-5-20251001",                "Claude Haiku 4.5 (2025-10)   — Anthropic"),
    ("anthropic.claude-opus-4-6-v1",             "Claude Opus 4.6 v1           — Bedrock"),
    ("anthropic.claude-sonnet-4-6",              "Claude Sonnet 4.6            — Bedrock"),
    ("anthropic.claude-haiku-4-5-20251001-v1:0", "Claude Haiku 4.5 v1          — Bedrock"),
    ("claude-haiku-4-5@20251001",                "Claude Haiku 4.5 (Vertex)    — Vertex AI"),
]

# Direct Groq models (used when GROQ_API_KEY is configured)
GROQ_DIRECT_MODELS = [
    ("meta-llama/llama-prompt-guard-2-86m",          "Llama Prompt Guard 2 86M       — Meta"),
    ("qwen/qwen3-32b",                               "Qwen3 32B                      — Qwen"),
    ("meta-llama/llama-guard-4-12b",                  "Llama Guard 4 12B              — Meta"),
    ("openai/gpt-oss-20b",                            "GPT-OSS 20B                    — OpenAI"),
    ("groq/compound-mini",                            "Compound Mini                  — Groq"),
    ("whisper-large-v3",                              "Whisper Large V3               — OpenAI"),
    ("openai/gpt-oss-120b",                           "GPT-OSS 120B                   — OpenAI"),
    ("meta-llama/llama-4-scout-17b-16e-instruct",     "Llama 4 Scout 17B              — Meta"),
    ("llama-3.3-70b-versatile",                       "Llama 3.3 70B Versatile        — Meta"),
    ("moonshotai/kimi-k2-instruct",                   "Kimi K2 Instruct               — Moonshot"),
    ("canopylabs/orpheus-v1-english",                 "Orpheus V1 English             — Canopy"),
    ("allam-2-7b",                                    "Allam 2 7B                     — STC"),
    ("whisper-large-v3-turbo",                        "Whisper Large V3 Turbo         — OpenAI"),
    ("openai/gpt-oss-safeguard-20b",                  "GPT-OSS Safeguard 20B          — OpenAI"),
    ("meta-llama/llama-prompt-guard-2-22m",           "Llama Prompt Guard 2 22M       — Meta"),
    ("llama-3.1-8b-instant",                          "Llama 3.1 8B Instant           — Meta"),
    ("moonshotai/kimi-k2-instruct-0905",              "Kimi K2 Instruct 0905          — Moonshot"),
    ("canopylabs/orpheus-arabic-saudi",               "Orpheus Arabic Saudi           — Canopy"),
    ("groq/compound",                                 "Compound                       — Groq"),
    ("meta-llama/llama-4-maverick-17b-128e-instruct", "Llama 4 Maverick 17B           — Meta"),
]


def get_available_models(cfg) -> list:
    """Return the combined model list based on configured API keys.

    Each entry is a (model_id, display_label) tuple, ready for the
    interactive selector in change_model().
    """
    models = []
    seen = set()

    def _add(model_id: str, label: str):
        if model_id not in seen:
            seen.add(model_id)
            models.append((model_id, label))

    # OpenAI direct models
    if cfg._openai_api_key:
        for model_id, label in OPENAI_DIRECT_MODELS:
            _add(model_id, label)

    # Anthropic direct models
    if cfg._anthropic_api_key:
        for model_id, label in ANTHROPIC_DIRECT_MODELS:
            _add(model_id, label)

    # Groq direct models
    if cfg._groq_api_key:
        for model_id, label in GROQ_DIRECT_MODELS:
            _add(model_id, label)

    # OpenRouter models (when logged in or OpenRouter key is set)
    if cfg._openrouter_api_key or cfg.access_token:
        for item in cfg.available_models:
            # available_models can be list of tuples or (id, label)
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                _add(item[0], item[1])
            elif isinstance(item, str):
                _add(item, item.split("/")[-1] if "/" in item else item)

    # Fallback: show defaults so the selector is never empty
    if not models:
        for item in cfg.available_models:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                _add(item[0], item[1])
            elif isinstance(item, str):
                _add(item, item.split("/")[-1] if "/" in item else item)

    return models

class ModelStore:
    def __init__(self):
        self.config_dir = Path.home() / ".archcode"
        self.user_models_file = self.config_dir / "user_models.json"
        self.openrouter_json_path = get_resource_path("app/utils/openrouter_chat_models_by_provider.json")
        self._providers_data: Optional[Dict[str, Any]] = None
        self._user_models: Optional[List[str]] = None

    def _load_openrouter_data(self) -> Dict[str, Any]:
        """Load provider and model data from OpenRouter JSON."""
        if self._providers_data is None:
            try:
                if self.openrouter_json_path.exists():
                    with open(self.openrouter_json_path, 'r', encoding='utf-8') as f:
                        self._providers_data = json.load(f)
                else:
                    console.print(f"[yellow]Warning: OpenRouter JSON not found at {self.openrouter_json_path}[/yellow]")
                    self._providers_data = {}
            except Exception as e:
                console.print(f"[red]Error loading OpenRouter data: {e}[/red]")
                self._providers_data = {}
        return self._providers_data

    def get_providers(self) -> List[str]:
        """Get list of all provider names."""
        data = self._load_openrouter_data()
        return sorted(data.keys()) if data else []

    def get_models_for_provider(self, provider: str) -> List[Dict[str, Any]]:
        """Get all models for a specific provider."""
        data = self._load_openrouter_data()
        provider_data = data.get(provider, {})
        # Return list of model info dicts
        models = []
        for model_name, model_info in provider_data.items():
            if isinstance(model_info, dict):
                model_info['name'] = model_name
                models.append(model_info)
        return models

    def get_model_by_id(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Find a model by its ID across all providers."""
        data = self._load_openrouter_data()
        for provider, models in data.items():
            for model_name, model_info in models.items():
                if isinstance(model_info, dict) and model_info.get('id') == model_id:
                    model_info['name'] = model_name
                    model_info['provider'] = provider
                    return model_info
        return None

    def load_user_models(self) -> List[str]:
        """Load user's selected models from config."""
        if self._user_models is None:
            try:
                if self.user_models_file.exists():
                    with open(self.user_models_file, 'r') as f:
                        data = json.load(f)
                        self._user_models = data.get('models', [])
                else:
                    self._user_models = []
            except Exception as e:
                console.print(f"[dim]Warning: Could not load user models: {e}[/dim]")
                self._user_models = []
        
        # If no user models, return defaults
        if not self._user_models:
            return DEFAULT_MODELS.copy()
        return self._user_models.copy()

    def save_user_models(self, models: List[str]):
        """Save user's selected models to config."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.user_models_file, 'w') as f:
                json.dump({'models': models}, f, indent=2)
            self._user_models = models.copy()
        except Exception as e:
            console.print(f"[red]Error saving user models: {e}[/red]")

    def add_user_model(self, model_id: str) -> bool:
        """Add a model to user's list. Returns True if added, False if already exists."""
        models = self.load_user_models()
        if model_id not in models:
            models.append(model_id)
            self.save_user_models(models)
            return True
        return False

    def remove_user_model(self, model_id: str) -> bool:
        """Remove a model from user's list. Returns True if removed."""
        models = self.load_user_models()
        if model_id in models:
            models.remove(model_id)
            self.save_user_models(models)
            return True
        return False

    def get_user_models_with_info(self) -> List[Dict[str, Any]]:
        """Get user's models with full info from OpenRouter data."""
        user_models = self.load_user_models()
        result = []
        for model_id in user_models:
            model_info = self.get_model_by_id(model_id)
            if model_info:
                result.append({
                    'id': model_id,
                    'name': model_info.get('name', model_id),
                    'provider': model_info.get('provider', 'Unknown')
                })
            else:
                result.append({
                    'id': model_id,
                    'name': model_id.split('/')[-1] if '/' in model_id else model_id,
                    'provider': model_id.split('/')[0] if '/' in model_id else 'Unknown'
                })
        return result


# Global instance
model_store = ModelStore()