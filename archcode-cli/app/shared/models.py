"""Shared datamodels for ArchCode CLI app package."""

from dataclasses import dataclass


@dataclass
class AppContext:
    """Lightweight context container for runtime composition."""

    session_id: str = "N/A"


__all__ = ["AppContext"]
