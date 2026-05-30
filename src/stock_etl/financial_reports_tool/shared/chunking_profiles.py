"""Compatibility shim for canonical financial reports chunking profiles."""

from __future__ import annotations

from .._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from agents.financial_agent.chunking_profiles import *  # noqa: F403
