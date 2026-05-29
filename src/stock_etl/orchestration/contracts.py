"""Contracts chuẩn hóa cho orchestration phase A."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ToolName(str, Enum):
    """Danh sách tool đã biết trong contract orchestration."""

    MARKET = "market"
    NEWS = "news"
    FINANCIAL_REPORTS = "financial_reports"


class ToolExecutionStatus(str, Enum):
    """Trạng thái chuẩn hóa khi một tool hoàn tất xử lý."""

    SUCCESS = "success"
    NO_DATA = "no_data"
    ERROR = "error"
    SKIPPED = "skipped"
    NOT_SUPPORTED_YET = "not_supported_yet"


class TraceEvent(BaseModel):
    """Một event debug nhỏ trong suốt flow orchestration."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    step: str
    status: str = "ok"
    detail: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedQueryRequest(BaseModel):
    """Request chuẩn hóa đầu vào cho orchestration API."""

    question: str = Field(min_length=3, description="Câu hỏi tự nhiên của người dùng.")
    debug: bool = Field(default=False, description="Bật trace chi tiết cho request.")
    trace_id: str | None = Field(default=None, description="Trace id do caller truyền vào nếu có.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata mở rộng cho caller.")


class IntentPlan(BaseModel):
    """Kế hoạch intent chuẩn hóa trước khi router chọn tool."""

    original_query: str
    normalized_query: str
    tools_to_use: list[ToolName] = Field(default_factory=list)
    tool_queries: dict[str, str] = Field(default_factory=dict)
    entities: dict[str, Any] = Field(default_factory=dict)
    time_constraints: dict[str, Any] = Field(default_factory=dict)
    analysis_requirements: dict[str, Any] = Field(default_factory=dict)
    reasoning_brief: str
    primary_intent: str = "unknown"
    classifier_mode: str = "rule_based"
    confidence: float = 0.0


class ToolExecutionRequest(BaseModel):
    """Request đã được router gán cho một tool cụ thể."""

    tool_name: ToolName
    query: str
    intent_plan: IntentPlan
    trace_id: str | None = None
    debug: bool = False


class ToolExecutionResult(BaseModel):
    """Kết quả chuẩn hóa của một tool sau khi thực thi."""

    tool_name: ToolName
    status: ToolExecutionStatus
    query_used: str
    summary: str
    structured_data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    limitations: list[str] = Field(default_factory=list)


class DebugTrace(BaseModel):
    """Trace phục vụ debug cho toàn bộ flow orchestration."""

    trace_id: str
    requested_tools: list[ToolName] = Field(default_factory=list)
    chosen_tools: list[ToolName] = Field(default_factory=list)
    unsupported_tools: list[ToolName] = Field(default_factory=list)
    fallback_reason: str | None = None
    generated_sql: str | None = None
    latency_ms: float | None = None
    events: list[TraceEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedQueryResponse(BaseModel):
    """Response chuẩn hóa của orchestration API."""

    trace_id: str
    status: str
    original_query: str
    normalized_query: str
    answer: str
    intent_plan: IntentPlan
    tools_used: list[ToolName] = Field(default_factory=list)
    results: list[ToolExecutionResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    debug_trace: DebugTrace | None = None
