"""Adapter mỏng để gọi news tool từ orchestration."""

from __future__ import annotations

from ..news_tool.service import NewsToolService
from .contracts import ToolExecutionRequest, ToolExecutionResult, ToolExecutionStatus, ToolName
from .trace import TraceCollector


class NewsToolAdapter:
    """Bọc news tool thành contract execution thống nhất."""

    def run(
        self,
        request: ToolExecutionRequest,
        *,
        trace_collector: TraceCollector | None = None,
    ) -> ToolExecutionResult:
        """Thực thi news tool và chuẩn hoá output.

        Args:
            request: Tool execution request do router tạo ra.
            trace_collector: Trace collector của orchestration nếu có.

        Returns:
            ToolExecutionResult theo contract orchestration.
        """

        try:
            payload = NewsToolService().ask(
                request.query,
                trace_id=request.trace_id,
                debug=request.debug,
            )
            if trace_collector:
                trace_collector.add_event(
                    "news_adapter.execute",
                    detail="News adapter gọi news tool thành công.",
                    metadata={"tool": ToolName.NEWS.value, "status": payload.status},
                )

            status = {
                "success": ToolExecutionStatus.SUCCESS,
                "no_data": ToolExecutionStatus.NO_DATA,
                "error": ToolExecutionStatus.ERROR,
            }.get(payload.status, ToolExecutionStatus.ERROR)

            return ToolExecutionResult(
                tool_name=ToolName.NEWS,
                status=status,
                query_used=request.query,
                summary=payload.summary,
                structured_data={
                    "query_id": payload.query_id,
                    "run_id": payload.run_id,
                    "article_count": len(payload.articles),
                    "article_summaries": payload.article_summaries,
                    "stats": payload.stats,
                },
                evidence=self._build_evidence(payload),
                raw_response=payload.model_dump(exclude_none=True),
                limitations=list(payload.limitations),
            )
        except Exception as exc:  # noqa: BLE001
            if trace_collector:
                trace_collector.add_event(
                    "news_adapter.execute",
                    status="error",
                    detail=str(exc),
                    metadata={"tool": ToolName.NEWS.value},
                )
            return ToolExecutionResult(
                tool_name=ToolName.NEWS,
                status=ToolExecutionStatus.ERROR,
                query_used=request.query,
                summary="News tool không xử lý được query hiện tại.",
                structured_data={},
                evidence=[],
                raw_response={"error": str(exc)},
                error_message=str(exc),
                limitations=["News pipeline gặp lỗi ở bước search/crawl/summarize."],
            )

    @staticmethod
    def _build_evidence(payload) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
        evidence: list[dict[str, object]] = []
        for article in payload.articles[:5]:
            evidence.append(
                {
                    "kind": "article",
                    "value": {
                        "article_id": article.article_id,
                        "title": article.title,
                        "site": article.site,
                        "url": article.url,
                        "summary": article.article_summary,
                    },
                }
            )
        return evidence
