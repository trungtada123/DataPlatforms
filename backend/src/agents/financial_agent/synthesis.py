"""Financial synthesis runtime wrapper for canonical backend layout."""

from __future__ import annotations

from agents._legacy import ensure_legacy_src_on_path


ensure_legacy_src_on_path()

from stock_etl.financial_reports_tool.runtime.synthesis import *  # noqa: F403

