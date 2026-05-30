"""Canonical orchestration schemas and contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ToolName(str, Enum):
    MARKET = "market"
    NEWS = "news"
    FINANCIAL_REPORTS = "financial_reports"


class ToolExecutionStatus(str, Enum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    ERROR = "error"
    SKIPPED = "skipped"
    NOT_SUPPORTED_YET = "not_supported_yet"


class TraceEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    step: str
    status: str = "ok"
    detail: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedQueryRequest(BaseModel):
    question: str = Field(min_length=3, description="Natural-language user question.")
    debug: bool = Field(default=False, description="Enable detailed trace output.")
    trace_id: str | None = Field(default=None, description="Caller-provided trace id.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Caller metadata.")


class IntentPlan(BaseModel):
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
    tool_name: ToolName
    query: str
    intent_plan: IntentPlan
    trace_id: str | None = None
    debug: bool = False


class ToolExecutionResult(BaseModel):
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
    trace_id: str
    status: str
    original_query: str
    normalized_query: str
    answer: str
    intent_plan: IntentPlan
    tools_used: list[ToolName] = Field(default_factory=list)
    results: list[ToolExecutionResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    merged_context: MergedContext | None = None
    debug_trace: DebugTrace | None = None


class MergedContext(BaseModel):
    user_query: str
    normalized_query: str
    intent_plan: dict[str, Any]
    normalized_entities: dict[str, Any]
    tool_summaries: list[dict[str, Any]] = Field(default_factory=list)
    key_evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    answer_style: str = "integrated_analysis"


class TraceCollector:
    def __init__(self, trace_id: str | None = None) -> None:
        self._started_at = perf_counter()
        self._trace = DebugTrace(trace_id=trace_id or uuid4().hex)
    @property
    def trace_id(self) -> str:
        return self._trace.trace_id
    def add_event(self, step: str, *, status: str = "ok", detail: str | None = None, duration_ms: float | None = None, metadata: dict | None = None) -> None:
        self._trace.events.append(TraceEvent(step=step, status=status, detail=detail, duration_ms=duration_ms, metadata=metadata or {}))
    def add_tool(self, tool_name: ToolName) -> None:
        if tool_name not in self._trace.chosen_tools:
            self._trace.chosen_tools.append(tool_name)
    def add_requested_tool(self, tool_name: ToolName) -> None:
        if tool_name not in self._trace.requested_tools:
            self._trace.requested_tools.append(tool_name)
    def add_unsupported_tool(self, tool_name: ToolName) -> None:
        if tool_name not in self._trace.unsupported_tools:
            self._trace.unsupported_tools.append(tool_name)
    def set_fallback_reason(self, reason: str) -> None:
        self._trace.fallback_reason = reason
    def set_generated_sql(self, sql: str | None) -> None:
        self._trace.generated_sql = sql
    def set_metadata(self, key: str, value: object) -> None:
        self._trace.metadata[key] = value
    def snapshot(self) -> DebugTrace:
        return self._trace
    def finalize(self) -> DebugTrace:
        self._trace.latency_ms = round((perf_counter() - self._started_at) * 1000, 3)
        return self._trace


AgentResult = NormalizedQueryResponse
IntentResult = IntentPlan
ToolResult = ToolExecutionResult
