"""Intent classifier cho orchestration market-first."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..config import Settings, get_settings
from ..gemini_pool import GeminiKeyPool
from .contracts import IntentPlan, NormalizedQueryRequest, ToolName
from .fallback_rules import build_rule_based_intent_plan


CLASSIFIER_PROMPT_TEMPLATE = """
You are an intent classifier for a stock-market orchestration service.

Current date: {today}

Supported tools:
- market
- news
- financial_reports

For this phase, prefer `market` whenever the user asks about price, ticker, technical indicators,
historical comparison, intraday status, or market-data analysis.

Return valid JSON only with this shape:
{{
  "primary_intent": "market|news|financial_reports|unknown",
  "normalized_query": "...",
  "tools_to_use": ["market"],
  "tool_queries": {{"market": "...", "news": "...", "financial_reports": "..."}},
  "entities": {{
    "tickers": ["ACB"],
    "company_names": ["Asia Commercial Bank"],
    "intraday": true,
    "historical": false,
    "technical_analysis": false,
    "comparison": false
  }},
  "time_constraints": {{
    "explicit_dates": [],
    "date_range": [],
    "relative_periods": []
  }},
  "analysis_requirements": {{
    "intraday": true,
    "historical": false,
    "technical_analysis": false,
    "comparison": false,
    "health_debug": false
  }},
  "reasoning_brief": "short explanation",
  "confidence": 0.0
}}

User query:
{question}
"""


class IntentClassifier:
    """Phân loại intent và tạo IntentPlan cho router.

    Args:
        settings: Settings override nếu caller muốn tái sử dụng config hiện có.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def classify(self, request: NormalizedQueryRequest | str) -> IntentPlan:
        """Classify một query thành IntentPlan.

        Args:
            request: Request chuẩn hóa hoặc raw string.

        Returns:
            IntentPlan dùng cho router.
        """

        normalized_request = request if isinstance(request, NormalizedQueryRequest) else NormalizedQueryRequest(question=request)
        fallback_plan = build_rule_based_intent_plan(normalized_request.question)

        if not self.settings.google_api_keys:
            return fallback_plan

        try:
            plan = self._classify_with_gemini(normalized_request.question, fallback_plan)
            return self._preserve_multi_tool_guard(plan, fallback_plan)
        except Exception:
            fallback_plan.classifier_mode = "fallback_rule_based"
            return fallback_plan

    def _classify_with_gemini(self, question: str, fallback_plan: IntentPlan) -> IntentPlan:
        """Dùng Gemini để enrich thêm plan khi có model khả dụng."""

        now_tz = getattr(self.settings, "tzinfo", timezone.utc)
        prompt = CLASSIFIER_PROMPT_TEMPLATE.format(
            today=datetime.now(now_tz).date().isoformat(),
            question=question,
        )
        response_text = GeminiKeyPool(
            self.settings,
            generation_config={"temperature": 0.0},
        ).generate_text(prompt)
        payload = self._extract_json_payload(response_text or "")
        return self._plan_from_payload(question, payload, fallback_plan)

    @staticmethod
    def _extract_json_payload(text: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Classifier model did not return JSON.")
        return json.loads(match.group(0))

    @staticmethod
    def _normalize_tools(raw_tools: list[Any], fallback_plan: IntentPlan) -> list[ToolName]:
        tools: list[ToolName] = []
        for raw_tool in raw_tools:
            try:
                tool = ToolName(str(raw_tool))
            except ValueError:
                continue
            if tool not in tools:
                tools.append(tool)

        if tools:
            return tools
        if fallback_plan.tools_to_use:
            return fallback_plan.tools_to_use
        primary_intent = fallback_plan.primary_intent
        try:
            return [ToolName(primary_intent)]
        except ValueError:
            return []

    def _plan_from_payload(
        self,
        question: str,
        payload: dict[str, Any],
        fallback_plan: IntentPlan,
    ) -> IntentPlan:
        tools_to_use = self._normalize_tools(payload.get("tools_to_use") or [], fallback_plan)
        normalized_query = str(payload.get("normalized_query") or fallback_plan.normalized_query)

        tool_queries = dict(fallback_plan.tool_queries)
        raw_tool_queries = payload.get("tool_queries") or {}
        for key, value in raw_tool_queries.items():
            if value:
                tool_queries[str(key)] = str(value)
        fallback_reports_query = fallback_plan.tool_queries.get(ToolName.FINANCIAL_REPORTS.value)
        current_reports_query = tool_queries.get(ToolName.FINANCIAL_REPORTS.value)
        if self._is_metric_report_question(question) and ToolName.FINANCIAL_REPORTS in tools_to_use:
            tool_queries[ToolName.FINANCIAL_REPORTS.value] = question
        elif (
            fallback_reports_query
            and current_reports_query
            and self._should_prefer_fallback_reports_query(fallback_reports_query, current_reports_query)
        ):
            tool_queries[ToolName.FINANCIAL_REPORTS.value] = fallback_reports_query
        for tool in tools_to_use:
            tool_queries.setdefault(tool.value, normalized_query)

        entities = dict(fallback_plan.entities)
        entities.update(payload.get("entities") or {})

        analysis_requirements = dict(fallback_plan.analysis_requirements)
        analysis_requirements.update(payload.get("analysis_requirements") or {})

        time_constraints = dict(fallback_plan.time_constraints)
        time_constraints.update(payload.get("time_constraints") or {})

        primary_intent = str(payload.get("primary_intent") or fallback_plan.primary_intent)
        valid_primary_intents = {tool.value for tool in ToolName} | {"unknown"}
        if primary_intent not in valid_primary_intents:
            primary_intent = fallback_plan.primary_intent
        if primary_intent == "unknown" and tools_to_use:
            primary_intent = tools_to_use[0].value
        if not tools_to_use and primary_intent in {tool.value for tool in ToolName}:
            tools_to_use = [ToolName(primary_intent)]
            tool_queries.setdefault(primary_intent, normalized_query)

        confidence = payload.get("confidence", fallback_plan.confidence)
        try:
            normalized_confidence = float(confidence)
        except (TypeError, ValueError):
            normalized_confidence = fallback_plan.confidence

        return IntentPlan(
            original_query=question,
            normalized_query=normalized_query,
            tools_to_use=tools_to_use,
            tool_queries=tool_queries,
            entities=entities,
            time_constraints=time_constraints,
            analysis_requirements=analysis_requirements,
            reasoning_brief=str(payload.get("reasoning_brief") or fallback_plan.reasoning_brief),
            primary_intent=primary_intent,
            classifier_mode="gemini",
            confidence=normalized_confidence,
        )

    @staticmethod
    def _should_prefer_fallback_reports_query(fallback_query: str, current_query: str) -> bool:
        """Giữ query reports cụ thể hơn nếu model làm rơi mốc thời gian/ý định kiểm toán."""

        fallback_normalized = fallback_query.casefold()
        current_normalized = current_query.casefold()
        fallback_has_year = re.search(r"\b20\d{2}\b", fallback_normalized) is not None
        fallback_has_quarter = re.search(r"\bq[1-4]\b", fallback_normalized) is not None
        fallback_has_opinion = any(token in fallback_normalized for token in ["opinion", "review", "audit"])
        current_has_year = re.search(r"\b20\d{2}\b", current_normalized) is not None
        current_has_quarter = re.search(r"\bq[1-4]\b", current_normalized) is not None
        current_has_opinion = any(token in current_normalized for token in ["opinion", "review", "audit"])

        return (
            (fallback_has_year and not current_has_year)
            or (fallback_has_quarter and not current_has_quarter)
            or (fallback_has_opinion and not current_has_opinion)
        )

    @staticmethod
    def _is_metric_report_question(question: str) -> bool:
        """Giữ nguyên câu hỏi reports dạng lấy chỉ tiêu/số liệu trong bảng."""

        normalized = question.casefold()
        metric_keywords = (
            "tổng tài sản",
            "cho vay khách hàng",
            "tiền gửi của khách hàng",
            "lợi nhuận sau thuế",
            "total assets",
            "customer loans",
            "customer deposits",
            "profit after tax",
        )
        report_keywords = (
            "báo cáo tài chính",
            "bao cao tai chinh",
            "financial report",
            "financial statements",
        )
        return any(metric in normalized for metric in metric_keywords) and any(
            keyword in normalized for keyword in report_keywords
        )

    @staticmethod
    def _preserve_multi_tool_guard(plan: IntentPlan, fallback_plan: IntentPlan) -> IntentPlan:
        """Giữ lại tín hiệu multi-tool từ fallback để tránh route sai sang single-tool.

        Args:
            plan: Intent plan do Gemini trả về.
            fallback_plan: Intent plan rule-based đã phát hiện multi-signal nếu có.

        Returns:
            Intent plan đã được bảo toàn multi-tool signal khi cần.
        """

        if len(fallback_plan.tools_to_use) <= 1:
            return plan

        merged_tools = list(fallback_plan.tools_to_use)
        for tool in plan.tools_to_use:
            if tool not in merged_tools:
                merged_tools.append(tool)

        merged_tool_queries = dict(fallback_plan.tool_queries)
        merged_tool_queries.update(plan.tool_queries)
        for tool in merged_tools:
            merged_tool_queries.setdefault(tool.value, plan.normalized_query)

        return plan.model_copy(
            update={
                "tools_to_use": merged_tools,
                "tool_queries": merged_tool_queries,
                "reasoning_brief": f"{plan.reasoning_brief}; giữ multi-tool signal từ fallback để tránh misroute",
            }
        )
