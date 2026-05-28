"""News storage runtime wrapper for canonical backend layout."""

from __future__ import annotations

from agents._legacy import ensure_legacy_src_on_path


ensure_legacy_src_on_path()

from stock_etl.news_tool.storage import *  # noqa: F403

