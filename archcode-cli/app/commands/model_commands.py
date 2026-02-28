"""
Model commands for the ArchCode CLI.
Handles /model, /model/provider, /model/provider/list, and model selection.
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from app.utils.model_store import model_store, DEFAULT_MODELS

console = Console()


def handle_model_command(user_input: str) -> bool:
    """
    Handle /model commands.
    Usage:
        /model              - Show user's current model list
        /model/provider     - Show all providers
        /model/<provider>/list  - Show all models for a provider
        /model/add <id>     - Add a model to user's list
        /model/remove <id>  - Remove a model from user's list
        /model <id>         - Switch to a specific model (existing behavior)
    """
    parts = user_input.strip().split()
    
    # Just /model - show user's current models
    if len(parts) == 1:
        _show_user_models()
        return True
    
    # Handle /model/provider
    if len(parts) == 2 and parts[1].lower() == "provider":
        _show_providers()
        return True
    
    # Handle /model/<provider>/list
    if len(parts) == 2 and parts[1].count("/") == 2 and parts[1].lower().endswith("/list"):
        provider = parts[1].split("/")[1]
        _show_provider_models(provider)
        return True
    
    # Handle /model/add <model_id>
    if len(parts) >= 2 and parts[1].lower() == "add":
        if len(parts) < 3:
            console.print("[red]Usage: /model add <model-id>[/red]")
            return True
        model_id = parts[2]
        _add_user_model(model_id)
        return True
    
    # Handle /model/remove <model_id>
    if len(parts) >= 2 and parts[1].lower() == "remove":
        if len(parts) < 3:
            console.print("[red]Usage: /model remove <model-id>[/red]")
            return True
        model_id = parts[2]
        _remove_user_model(model_id)
        return True
    
    # Default: switch model (existing behavior handled in command_handler)
    return False


def _show_user_models():
    """Display user's current model list with nice formatting."""
    models = model_store.get_user_models_with_info()
    
    if not models:
        console.print("[yellow]No models in your list. Use /model/provider to browse and add models.[/yellow]")
        return
    
    console.print(f"\n[bold #ff8888]Your Models ({len(models)}):[/bold #ff8888]\n")
    
    for i, model in enumerate(models, 1):
        model_id = model['id']
        name = model['name']
        provider = model['provider']
        
        # Format nicely
        console.print(f"  [{i}] [bold]{name}[/bold]")
        console.print(f"      ID: [dim]{model_id}[/dim]")
        console.print(f"      Provider: [cyan]{provider}[/cyan]")
        console.print()
    
    console.print("[dim]Use '/model <id>' to switch models[/dim]")
    console.print("[dim]Use '/model add <id>' or '/model remove <id>' to manage your list[/dim]")
    console.print("[dim]Use '/model/provider' to browse all available models[/dim]\n")


def _show_providers():
    """Display all available providers from OpenRouter data."""
    providers = model_store.get_providers()
    
    if not providers:
        console.print("[yellow]No providers found. Check if OpenRouter JSON file exists.[/yellow]")
        return
    
    console.print(f"\n[bold #ff8888]Available Providers ({len(providers)}):[/bold #ff8888]\n")
    
    # Create a nice table
    table = Table(show_header=False, box=None, padding=(0, 2))
    
    # Display in 3 columns
    for i in range(0, len(providers), 3):
        row = providers[i:i+3]
        formatted = [f"[cyan]•[/cyan] {p}" for p in row]
        while len(formatted) < 3:
            formatted.append("")
        table.add_row(*formatted)
    
    console.print(table)
    console.print("\n[dim]Use '/model/<provider>/list' to see models for a provider[/dim]")
    console.print("[dim]Example: /model/openai/list[/dim]\n")


def _show_provider_models(provider: str):
    """Display all models for a specific provider."""
    models = model_store.get_models_for_provider(provider)
    
    if not models:
        console.print(f"[yellow]No models found for provider: {provider}[/yellow]")
        available = model_store.get_providers()
        if available:
            console.print(f"[dim]Available providers: {', '.join(available[:10])}...[/dim]")
        return
    
    console.print(f"\n[bold #ff8888]{provider} Models ({len(models)}):[/bold #ff8888]\n")
    
    for model in models:
        model_id = model.get('id', 'N/A')
        name = model.get('name', model_id)
        description = model.get('description', 'No description')
        
        # Truncate description
        if len(description) > 100:
            description = description[:97] + "..."
        
        console.print(f"  [bold]{name}[/bold]")
        console.print(f"      ID: [green]{model_id}[/green]")
        if description and description != "No description":
            console.print(f"      [dim]{description}[/dim]")
        console.print()
    
    console.print(f"[dim]Use '/model add <id>' to add a model to your list[/dim]")
    console.print(f"[dim]Example: /model add {models[0].get('id', 'provider/model-name')}[/dim]\n")


def _add_user_model(model_id: str):
    """Add a model to user's list."""
    # Validate model exists in OpenRouter data
    model_info = model_store.get_model_by_id(model_id)
    
    if not model_info:
        # Check if it's a valid format (provider/model-name)
        if "/" not in model_id:
            console.print(f"[red]Invalid model ID format. Expected: provider/model-name[/red]")
            return
    
    added = model_store.add_user_model(model_id)
    
    if added:
        if model_info:
            console.print(f"[green]✓[/green] Added [bold]{model_info.get('name', model_id)}[/bold] to your model list")
        else:
            console.print(f"[green]✓[/green] Added [bold]{model_id}[/bold] to your model list")
        console.print(f"[dim]Use '/model' to see your updated list[/dim]")
    else:
        console.print(f"[yellow]Model '{model_id}' is already in your list[/yellow]")


def _remove_user_model(model_id: str):
    """Remove a model from user's list."""
    removed = model_store.remove_user_model(model_id)
    
    if removed:
        console.print(f"[green]✓[/green] Removed [bold]{model_id}[/bold] from your model list")
    else:
        console.print(f"[yellow]Model '{model_id}' not found in your list[/yellow]")


def get_user_models():
    """Get list of user's model IDs for the interactive selector."""
    return model_store.load_user_models()