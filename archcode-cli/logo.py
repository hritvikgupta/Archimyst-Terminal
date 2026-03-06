import os
from rich.text import Text
from rich.align import Align
from rich.panel import Panel

def _get_theme_color():
    """Get the theme color based on agent mode."""
    return "#22c55e" if os.getenv("AGENT_MODE") == "data" else "#ff8888"  # green for data, pink for coding

def _get_theme_name():
    """Get the theme name based on agent mode."""
    return "DATAMYST" if os.getenv("AGENT_MODE") == "data" else "ARCHIMYST"

def get_logo():
    """
    Returns the logo as a Rich compatible object.
    Design: Custom Block Font for 'ARCHIMYST' or 'DATAMYST'
    Color: Green (#22c55e) for data mode, Pink (#ff8888) for coding mode.
    """
    color = _get_theme_color()
    name = _get_theme_name()
    
    logo_art = rf"""
 [bold {color}] ▄▄▄       ██████╗  ▄█████╗  ██╗  ██╗ ██╗ ███╗   ███╗ ██╗   ██╗ ███████╗ ████████╗[/bold {color}]
 [bold {color}]█████╗    ██╔══██╗██╔════╝  ██║  ██║ ██║ ████╗ ████║ ╚██╗ ██╔╝ ██╔════╝ ╚══██╔══╝[/bold {color}]
 [bold {color}]██╔══██╗  ██████╔╝██║       ███████║ ██║ ██╔████╔██║  ╚████╔╝  ███████╗    ██║   [/bold {color}]
 [bold {color}]███████║  ██╔══██╗██║       ██╔══██║ ██║ ██║╚██╔╝██║   ╚██╔╝   ╚════██║    ██║   [/bold {color}]
 [bold {color}]██╔══██║  ██║  ██║╚██████╗  ██║  ██║ ██║ ██║ ╚═╝ ██║    ██║    ███████║    ██║   [/bold {color}]
 [bold {color}]╚═╝  ╚═╝  ╚═╝  ╚═╝ ╚═════╝  ╚═╝  ╚═╝ ╚═╝ ╚═╝     ╚═╝    ╚═╝    ╚══════╝    ╚═╝   [/bold {color}]
    """
    
    return Align(Text.from_markup(logo_art), align="center")

def get_banner_info(version: str, model_name: str, mode: str, path: str, email: str = None):
    """
    Returns the startup banner info with a professional, structured layout.
    Uses green theme for data mode, pink for coding mode.
    """
    color = _get_theme_color()
    tier_text = mode.upper()
    email_display = f" • {email}" if email else ""

    return f"""
 [bold {color}]{model_name}[/bold {color}] [dim]v{version}[/dim]
 [bold {color}]{tier_text}{email_display}[/bold {color}]
 [dim]cwd: {path}[/dim]
[dim]────────────────────────────────────────────────────────────────────────────────[/dim]
"""
