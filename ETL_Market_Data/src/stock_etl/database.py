"""Compatibility shim for database helpers during backend layout migration.

This module intentionally re-exports:
- shared database/bootstrap/upsert logic from ``core.database``
- NL2SQL read-only executor from ``agents.market_agent.sql_executor``
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "backend" / "src"
if _BACKEND_SRC.exists():
    backend_src = str(_BACKEND_SRC)
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)

from agents.market_agent.sql_executor import execute_readonly_sql
from core.database import *  # noqa: F403

# NOTE: explicit re-export keeps old callers stable while canonical modules move
# to backend/src/core and backend/src/agents.
