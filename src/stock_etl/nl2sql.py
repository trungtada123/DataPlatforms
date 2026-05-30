"""Compatibility shim for market NL2SQL during canonical migration."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "backend" / "src"
if _BACKEND_SRC.exists():
    backend_src = str(_BACKEND_SRC)
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)

_CANONICAL_MODULE = import_module("agents.market_agent.nl2sql")
sys.modules[__name__] = _CANONICAL_MODULE
