"""Canonical config facade for financial reports runtime settings."""

from __future__ import annotations

from stock_etl.financial_reports_tool.config import (
    FinancialReportsToolSettings,
    get_financial_reports_settings,
)

__all__ = ["FinancialReportsToolSettings", "get_financial_reports_settings"]
