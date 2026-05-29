"""Compatibility shim for canonical backend settings."""

from __future__ import annotations

import sys
from pathlib import Path


_BACKEND_SRC = Path(__file__).resolve().parents[2] / "backend" / "src"
if _BACKEND_SRC.exists():
    backend_src = str(_BACKEND_SRC)
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)

from config.base import ENV_FILE_ENV_VAR, PROJECT_ROOT
from config.base import resolve_env_file as _resolve_env_file
from config.settings import Settings, get_settings, require_ssi_settings
from config.market import DEFAULT_SYMBOLS
from config.llm import split_secret_csv as _split_secret_csv
from config.market import split_symbol_csv as _split_csv


ENV_FILE = PROJECT_ROOT / ".env"

__all__ = [
    "DEFAULT_SYMBOLS",
    "ENV_FILE",
    "ENV_FILE_ENV_VAR",
    "PROJECT_ROOT",
    "Settings",
    "_resolve_env_file",
    "_split_csv",
    "_split_secret_csv",
    "get_settings",
    "require_ssi_settings",
]
