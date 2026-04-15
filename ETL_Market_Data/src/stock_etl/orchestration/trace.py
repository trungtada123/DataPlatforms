"""Tiện ích trace và debug cho orchestration flow."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from .contracts import DebugTrace, ToolName, TraceEvent


class TraceCollector:
    """Thu thập trace runtime cho một request orchestration.

    Args:
        trace_id: Trace id có sẵn từ caller nếu muốn tái sử dụng.
    """

    def __init__(self, trace_id: str | None = None) -> None:
        self._started_at = perf_counter()
        self._trace = DebugTrace(trace_id=trace_id or uuid4().hex)

    @property
    def trace_id(self) -> str:
        """Lấy trace id hiện tại."""

        return self._trace.trace_id

    def add_event(
        self,
        step: str,
        *,
        status: str = "ok",
        detail: str | None = None,
        duration_ms: float | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Thêm một event vào trace.

        Args:
            step: Tên bước đang được ghi nhận.
            status: Trạng thái ngắn của bước.
            detail: Mô tả ngắn gọn cho event.
            duration_ms: Thời gian của bước nếu có.
            metadata: Metadata mở rộng đi kèm event.
        """

        self._trace.events.append(
            TraceEvent(
                step=step,
                status=status,
                detail=detail,
                duration_ms=duration_ms,
                metadata=metadata or {},
            )
        )

    def add_tool(self, tool_name: ToolName) -> None:
        """Ghi nhận tool đã được chọn."""

        if tool_name not in self._trace.chosen_tools:
            self._trace.chosen_tools.append(tool_name)

    def set_fallback_reason(self, reason: str) -> None:
        """Ghi nhận lý do fallback."""

        self._trace.fallback_reason = reason

    def set_generated_sql(self, sql: str | None) -> None:
        """Ghi lại SQL được sinh ra nếu có."""

        self._trace.generated_sql = sql

    def set_metadata(self, key: str, value: object) -> None:
        """Đính thêm metadata tổng hợp vào trace."""

        self._trace.metadata[key] = value

    def snapshot(self) -> DebugTrace:
        """Trả về trace hiện tại để caller inspect mà không đóng trace."""

        return self._trace

    def finalize(self) -> DebugTrace:
        """Đóng trace và trả về payload cuối cùng."""

        self._trace.latency_ms = round((perf_counter() - self._started_at) * 1000, 3)
        return self._trace
