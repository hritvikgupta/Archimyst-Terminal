"""
Utility functions for the archcode CLI.
"""
import sys
import os
from pathlib import Path


def get_resource_path(relative_path: str) -> Path:
    """
    Get the absolute path to a resource file.
    
    Works both in development mode and when bundled with PyInstaller.
    PyInstaller stores bundled files in sys._MEIPASS.
    
    Args:
        relative_path: Path relative to the project root (e.g., 'app/utils/file.json')
    
    Returns:
        Path: Absolute path to the resource
    """
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    if hasattr(sys, '_MEIPASS'):
        base_path = Path(sys._MEIPASS)
    else:
        # Development mode: path relative to this file's location
        # app/utils/__init__.py -> go up 3 levels to project root
        base_path = Path(__file__).parent.parent.parent
    
    return base_path / relative_path