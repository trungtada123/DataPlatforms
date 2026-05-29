"""Tests cho runtime readiness orchestration."""

from __future__ import annotations

from unittest import TestCase

from orchestration.contracts import ToolName
from orchestration.runtime_readiness import (
    READINESS_NO_DATA,
    READINESS_SERVICE_UNREACHABLE,
    ReadinessCheck,
    ToolRuntimeReadiness,
    dependency_names_for_tools,
    summarize_preflight_blocker,
)


class RuntimeReadinessTests(TestCase):
    """Kiểm tra helper readiness dùng chung cho smoke và orchestration."""

    def test_dependency_names_are_deduped(self) -> None:
        dependencies = dependency_names_for_tools(
            [ToolName.MARKET, ToolName.NEWS, ToolName.MARKET, ToolName.FINANCIAL_REPORTS]
        )

        self.assertEqual(
            dependencies,
            ["postgres", "gemini", "ddgs", "crawl4ai", "groq_or_gemini", "qdrant", "sentence_transformers", "groq"],
        )

    def test_summarize_preflight_blocker_prefers_blocking_failures(self) -> None:
        readiness = ToolRuntimeReadiness(
            tool_name=ToolName.MARKET,
            runtime_ready=False,
            end_to_end_ready=False,
            checks=[
                ReadinessCheck(
                    name="tcp:postgres:5432",
                    category=READINESS_SERVICE_UNREACHABLE,
                    detail="Không kết nối được PostgreSQL dev.",
                    is_blocking=True,
                ),
                ReadinessCheck(
                    name="database:views",
                    category=READINESS_NO_DATA,
                    detail="DB có schema nhưng chưa có dữ liệu.",
                    is_blocking=False,
                ),
            ],
            notes=[],
        )

        self.assertEqual(readiness.primary_failure_category, READINESS_SERVICE_UNREACHABLE)
        self.assertEqual(summarize_preflight_blocker(readiness), "Không kết nối được PostgreSQL dev.")
