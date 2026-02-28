from rich.text import Text
from rich.align import Align
from rich.panel import Panel

def get_logo():
    """
    Returns the Archimyst logo as a Rich compatible object.
    Design: Custom Block Font for 'ARCHIMYST' matching the landing page aesthetic.
    Color: Reddish/Pink/Salmon theme (approx #ff8888 or similiar ANSI).
    """
    
    # Custom block font construction for "ARCHIMYST"
    # Fixed typo: Ensure 'C' is distinct from 'O' or 'D'
    
    logo_art = r"""
 [bold #ff8888] ▄▄▄       ██████╗  ▄█████╗  ██╗  ██╗ ██╗ ███╗   ███╗ ██╗   ██╗ ███████╗ ████████╗[/bold #ff8888]
 [bold #ff8888]█████╗    ██╔══██╗██╔════╝  ██║  ██║ ██║ ████╗ ████║ ╚██╗ ██╔╝ ██╔════╝ ╚══██╔══╝[/bold #ff8888]
 [bold #ff8888]██╔══██╗  ██████╔╝██║       ███████║ ██║ ██╔████╔██║  ╚████╔╝  ███████╗    ██║   [/bold #ff8888]
 [bold #ff8888]███████║  ██╔══██╗██║       ██╔══██║ ██║ ██║╚██╔╝██║   ╚██╔╝   ╚════██║    ██║   [/bold #ff8888]
 [bold #ff8888]██╔══██║  ██║  ██║╚██████╗  ██║  ██║ ██║ ██║ ╚═╝ ██║    ██║    ███████║    ██║   [/bold #ff8888]
 [bold #ff8888]╚═╝  ╚═╝  ╚═╝  ╚═╝ ╚═════╝  ╚═╝  ╚═╝ ╚═╝ ╚═╝     ╚═╝    ╚═╝    ╚══════╝    ╚═╝   [/bold #ff8888]
    """
    
    return Align(Text.from_markup(logo_art), align="center")

def get_banner_info(version: str, model_name: str, mode: str, path: str, email: str = None):
    """
    Returns the startup banner info with a professional, structured layout.
    """
    tier_text = mode.upper()
    email_display = f" • {email}" if email else ""

    return f"""
 [bold #ff8888]{model_name}[/bold #ff8888] [dim]v{version}[/dim]
 [bold #ff8888]{tier_text}{email_display}[/bold #ff8888]
 [dim]cwd: {path}[/dim]
[dim]────────────────────────────────────────────────────────────────────────────────[/dim]
"""
