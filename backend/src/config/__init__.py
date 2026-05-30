"""Canonical backend config package.

Facade exports:
- get_settings
- require_ssi_settings
- Settings
"""

from .settings import Settings, get_settings, require_ssi_settings

__all__ = ["Settings", "get_settings", "require_ssi_settings"]
