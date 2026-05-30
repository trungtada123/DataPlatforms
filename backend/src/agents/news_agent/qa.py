"""Unified news-agent QA facade."""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from typing import Any

from schemas.orchestration import AgentResult, IntentPlan, ToolExecutionResult, ToolExecutionStatus, ToolName

from .service import NewsToolService


def normalize_news_tool_query(value: Any, original_query: str | None = None) -> str:
    """Normalize structured news tool query payload to plain text."""

    fallback = str(original_query or "").strip()
    parsed = _coerce_news_query_payload(value)
    if isinstance(parsed, Mapping):
        text = _build_query_from_mapping(parsed)
    else:
        text = str(parsed or "").strip()

    if not text:
        return fallback
    return " ".join(text.split())


def _coerce_news_query_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ""
        if raw.startswith("{") and raw.endswith("}"):
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, Mapping):
                    return loaded
            except Exception:
                pass
            try:
                loaded = ast.literal_eval(raw)
                if isinstance(loaded, Mapping):
                    return loaded
            except Exception:
                pass
        return raw
    return str(value or "").strip()


def _build_query_from_mapping(payload: Mapping[str, Any]) -> str:
    def _read_first(*keys: str) -> str:
        for key in keys:
            if key not in payload:
                continue
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    base_query = _read_first("query", "question", "text", "keyword", "keywords")
    ticker = _read_first("ticker", "symbol")
    time_period = _read_first("time_period", "timeframe", "time_window")
    tone = _read_first("sentiment", "tone")
    topic = _read_first("topic", "focus")

    parts: list[str] = []
    if base_query:
        parts.append(base_query)
    if ticker and ticker.lower() not in base_query.lower():
        parts.append(ticker)
    for token in (time_period, tone, topic):
        if token:
            parts.append(token)
    return " ".join(parts).strip()


def answer(query: str) -> AgentResult:
    """Answer one news query and wrap into canonical AgentResult."""

    normalized_query = normalize_news_tool_query(query, original_query=query)
    try:
        payload = NewsToolService().ask(normalized_query)
        status_value = str(payload.status)
        if status_value == "success":
            tool_status = ToolExecutionStatus.SUCCESS
        elif status_value == "no_data":
            tool_status = ToolExecutionStatus.NO_DATA
        else:
            tool_status = ToolExecutionStatus.ERROR

        tool_result = ToolExecutionResult(
            tool_name=ToolName.NEWS,
            status=tool_status,
            query_used=normalized_query,
            summary=payload.summary,
            structured_data={
                "query_id": payload.query_id,
                "run_id": payload.run_id,
                "stats": payload.stats,
                "article_summaries": payload.article_summaries,
            },
            evidence=[
                {
                    "kind": "news_articles_preview",
                    "value": [article.model_dump() for article in payload.articles[:3]],
                }
            ],
            raw_response=payload.model_dump(),
            limitations=list(payload.limitations),
        )
        return AgentResult(
            trace_id=payload.query_id,
            status=status_value,
            original_query=query,
            normalized_query=payload.normalized_question,
            answer=payload.summary,
            intent_plan=IntentPlan(
                original_query=query,
                normalized_query=payload.normalized_question,
                tools_to_use=[ToolName.NEWS],
                tool_queries={ToolName.NEWS.value: payload.normalized_question},
                entities={},
                time_constraints={},
                analysis_requirements={},
                reasoning_brief="news_agent_qa",
                primary_intent="news",
                classifier_mode="agent_facade",
                confidence=1.0 if status_value == "success" else 0.6,
            ),
            tools_used=[ToolName.NEWS],
            results=[tool_result],
            limitations=list(payload.limitations),
            debug_trace=None,
        )
    except Exception as exc:  # noqa: BLE001
        tool_result = ToolExecutionResult(
            tool_name=ToolName.NEWS,
            status=ToolExecutionStatus.ERROR,
            query_used=normalized_query,
            summary="News tool khong xu ly duoc query hien tai.",
            structured_data={},
            evidence=[],
            raw_response={"error": str(exc)},
            error_message=str(exc),
        )
        return AgentResult(
            trace_id="news-agent",
            status="error",
            original_query=query,
            normalized_query=normalized_query,
            answer="News tool khong xu ly duoc query hien tai.",
            intent_plan=IntentPlan(
                original_query=query,
                normalized_query=normalized_query,
                tools_to_use=[ToolName.NEWS],
                tool_queries={ToolName.NEWS.value: normalized_query},
                entities={},
                time_constraints={},
                analysis_requirements={},
                reasoning_brief="news_agent_qa_error",
                primary_intent="news",
                classifier_mode="agent_facade",
                confidence=0.0,
            ),
            tools_used=[ToolName.NEWS],
            results=[tool_result],
            limitations=[str(exc)],
            debug_trace=None,
        )
