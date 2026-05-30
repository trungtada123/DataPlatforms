"""Helpers for loading legacy ``src/stock_etl`` modules during migration."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_legacy_src_on_path() -> None:
    """Ensure legacy source root is importable when running from backend/src."""

    project_root = Path(__file__).resolve().parents[3]
    src_dir = project_root / "src"
    src_path = str(src_dir)
    if src_dir.exists() and src_path not in sys.path:
        sys.path.insert(0, src_path)

