"""Compatibility helpers for importing the canonical backend financial agent."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_backend_src_on_path() -> None:
    """Ensure ``backend/src`` is importable for legacy compatibility shims."""

    project_root = Path(__file__).resolve().parents[3]
    backend_src = project_root / "backend" / "src"
    backend_src_path = str(backend_src)
    if backend_src.exists() and backend_src_path not in sys.path:
        sys.path.insert(0, backend_src_path)


__all__ = ["ensure_backend_src_on_path"]
