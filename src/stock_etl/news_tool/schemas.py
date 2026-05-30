"""Compatibility shim for canonical news schemas implementation."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path


def _ensure_backend_src_on_path() -> None:
    project_root = Path(__file__).resolve().parents[3]
    backend_src = project_root / "backend" / "src"
    backend_path = str(backend_src)
    if backend_src.exists() and backend_path not in sys.path:
        sys.path.insert(0, backend_path)


_ensure_backend_src_on_path()
_CANONICAL_MODULE = import_module("agents.news_agent.schemas")
sys.modules[__name__] = _CANONICAL_MODULE
