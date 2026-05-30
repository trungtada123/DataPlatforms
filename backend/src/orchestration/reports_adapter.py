"""Adapter orchestration cho financial reports tool."""

from __future__ import annotations

from agents.financial_agent.service import FinancialReportsQueryService
from .contracts import ToolExecutionRequest, ToolExecutionResult, ToolExecutionStatus, ToolName
from .trace import TraceCollector


class FinancialReportsToolAdapter:
    """Bọc financial reports runtime thành contract execution thống nhất."""

    def run(
        self,
        request: ToolExecutionRequest,
        *,
        trace_collector: TraceCollector | None = None,
    ) -> ToolExecutionResult:
        """Thực thi tool financial reports và chuẩn hóa output."""

        try:
            payload = FinancialReportsQueryService().ask(
                request.query,
                trace_id=request.trace_id,
                debug=request.debug,
                trace_collector=trace_collector,
            )
            if trace_collector:
                trace_collector.add_event(
                    "financial_reports_adapter.execute",
                    detail="Financial reports adapter gọi query service thành công.",
                    metadata={"tool": ToolName.FINANCIAL_REPORTS.value, "status": payload.status},
                )

            status = {
                "success": ToolExecutionStatus.SUCCESS,
                "no_data": ToolExecutionStatus.NO_DATA,
                "error": ToolExecutionStatus.ERROR,
            }.get(payload.status, ToolExecutionStatus.ERROR)

            return ToolExecutionResult(
                tool_name=ToolName.FINANCIAL_REPORTS,
                status=status,
                query_used=request.query,
                summary=payload.summary,
                structured_data={
                    "filters": payload.filters,
                    "retrieval_queries": payload.retrieval_queries,
                    "top_hits": [item.model_dump() for item in payload.hits],
                    "selected_contexts": [item.model_dump() for item in payload.contexts],
                    "synthesis_model": payload.raw_response.get("synthesis_model"),
                },
                evidence=self._build_evidence(payload),
                raw_response=payload.model_dump(exclude_none=True),
                limitations=list(payload.limitations),
            )
        except Exception as exc:  # noqa: BLE001
            if trace_collector:
                trace_collector.add_event(
                    "financial_reports_adapter.execute",
                    status="error",
                    detail=str(exc),
                    metadata={"tool": ToolName.FINANCIAL_REPORTS.value},
                )
            return ToolExecutionResult(
                tool_name=ToolName.FINANCIAL_REPORTS,
                status=ToolExecutionStatus.ERROR,
                query_used=request.query,
                summary="Financial reports tool không xử lý được query hiện tại.",
                structured_data={},
                evidence=[],
                raw_response={"error": str(exc)},
                error_message=str(exc),
                limitations=["Financial reports runtime gặp lỗi ở bước retrieval/rerank/synthesis."],
            )

    @staticmethod
    def _build_evidence(payload) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
        evidence: list[dict[str, object]] = []
        for context in payload.contexts[:5]:
            evidence.append(
                {
                    "kind": "report_context",
                    "value": {
                        "retrieval_id": context.retrieval_id,
                        "chunk_type": context.chunk_type,
                        "page": context.page,
                        "section_title": context.section_title,
                        "source_ids": context.source_ids,
                        "preview": context.preview,
                    },
                }
            )
        return evidence
