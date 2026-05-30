"""Context merger node and canonical merge logic."""

from __future__ import annotations

"""Gộp context đa tool thành payload thống nhất cho bước final synthesis."""


import json
import re
from typing import Any

from pydantic import BaseModel, Field

from src.schemas.orchestration import IntentPlan, ToolExecutionResult, ToolExecutionStatus, ToolName


class MergedContext(BaseModel):
    """Context hợp nhất dùng cho bước tổng hợp câu trả lời cuối.

    Attributes:
        user_query: Câu hỏi gốc của người dùng.
        normalized_query: Câu hỏi đã được normalize từ intent plan.
        intent_plan: Intent plan ở dạng JSON-friendly.
        normalized_entities: Thực thể đã chuẩn hóa cho toàn bộ request.
        tool_summaries: Danh sách tóm tắt theo từng tool đã chạy.
        key_evidence: Evidence đã được chuẩn hóa và dedupe.
        limitations: Hạn chế tổng hợp từ từng tool và orchestration.
        answer_style: Gợi ý phong cách trả lời cho final synthesizer.
    """

    user_query: str
    normalized_query: str
    intent_plan: dict[str, Any]
    normalized_entities: dict[str, Any]
    tool_summaries: list[dict[str, Any]] = Field(default_factory=list)
    key_evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    answer_style: str = "integrated_analysis"


class ContextMerger:
    """Gộp kết quả từ nhiều tool thành context có cấu trúc rõ ràng."""

    def merge(
        self,
        original_query: str,
        results: list[ToolExecutionResult],
        intent_plan: IntentPlan,
    ) -> MergedContext:
        """Gộp kết quả execution thành merged context.

        Args:
            original_query: Câu hỏi gốc của người dùng.
            results: Danh sách kết quả từ các tool đã chạy.
            intent_plan: Intent plan đã được classifier tạo ra.

        Returns:
            MergedContext sẵn sàng cho bước final synthesis.
        """

        tool_summaries = [self._build_tool_summary(result) for result in results]
        key_evidence = self._collect_key_evidence(results)
        limitations = self._collect_limitations(results)

        return MergedContext(
            user_query=original_query,
            normalized_query=intent_plan.normalized_query,
            intent_plan=intent_plan.model_dump(mode="json"),
            normalized_entities=self._build_normalized_entities(intent_plan, results),
            tool_summaries=tool_summaries,
            key_evidence=key_evidence,
            limitations=limitations,
            answer_style=self._infer_answer_style(original_query, intent_plan, results),
        )

    def _build_tool_summary(self, result: ToolExecutionResult) -> dict[str, Any]:
        """Chuẩn hóa phần summary của từng tool để dễ synthesize hơn."""

        summary_payload = {
            "tool_name": result.tool_name.value,
            "status": result.status.value,
            "query_used": result.query_used,
            "summary": result.summary,
            "highlights": [],
        }
        if result.tool_name == ToolName.NEWS:
            articles = result.structured_data.get("article_summaries")
            if isinstance(articles, list):
                summary_payload["structured_articles"] = articles[:5]

        if result.tool_name == ToolName.MARKET:
            summary_payload["highlights"] = self._market_highlights(result)
        elif result.tool_name == ToolName.NEWS:
            summary_payload["highlights"] = self._news_highlights(result)
        elif result.tool_name == ToolName.FINANCIAL_REPORTS:
            summary_payload["highlights"] = self._reports_highlights(result)

        if result.limitations:
            summary_payload["limitations"] = list(result.limitations)
        if result.error_message:
            summary_payload["error_message"] = result.error_message
        return summary_payload

    def _collect_key_evidence(self, results: list[ToolExecutionResult]) -> list[dict[str, Any]]:
        """Chuẩn hóa và dedupe evidence từ các tool."""

        seen_keys: set[str] = set()
        merged_evidence: list[dict[str, Any]] = []

        for result in results:
            for evidence_item in result.evidence:
                normalized_item = self._normalize_evidence(result.tool_name, evidence_item)
                if normalized_item is None:
                    continue
                dedupe_key = normalized_item.pop("_dedupe_key", "")
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                merged_evidence.append(normalized_item)

        return merged_evidence[:10]

    def _collect_limitations(self, results: list[ToolExecutionResult]) -> list[str]:
        """Tổng hợp limitation từ tool results thành danh sách gọn."""

        limitations: list[str] = []
        for result in results:
            for limitation in result.limitations:
                normalized = limitation.strip()
                if normalized and normalized not in limitations:
                    limitations.append(normalized)

            if result.status == ToolExecutionStatus.NO_DATA:
                message = f"Tool `{result.tool_name.value}` chưa tìm thấy dữ liệu phù hợp cho query này."
                if message not in limitations:
                    limitations.append(message)
            if result.status == ToolExecutionStatus.ERROR:
                message = f"Tool `{result.tool_name.value}` gặp lỗi trong lúc xử lý."
                if message not in limitations:
                    limitations.append(message)
        return limitations

    def _build_normalized_entities(
        self,
        intent_plan: IntentPlan,
        results: list[ToolExecutionResult],
    ) -> dict[str, Any]:
        """Gộp thực thể từ intent plan với tín hiệu nhẹ từ tool results."""

        entities = dict(intent_plan.entities)
        entities.setdefault("tools_detected", [result.tool_name.value for result in results])

        companies = [str(item) for item in entities.get("company_names", []) if str(item).strip()]
        tickers = [str(item) for item in entities.get("tickers", []) if str(item).strip()]

        for result in results:
            if result.tool_name == ToolName.MARKET:
                rows = result.structured_data.get("rows")
                if isinstance(rows, list) and rows:
                    ticker = str((rows[0] or {}).get("ticker") or "").strip()
                    if ticker and ticker not in tickers:
                        tickers.append(ticker)
            if result.tool_name == ToolName.NEWS:
                article_summaries = result.structured_data.get("article_summaries")
                if isinstance(article_summaries, list):
                    sites = sorted(
                        {
                            str(item.get("site") or "").strip()
                            for item in article_summaries
                            if isinstance(item, dict) and str(item.get("site") or "").strip()
                        }
                    )
                    if sites:
                        entities["news_sites"] = sites

        entities["tickers"] = tickers
        entities["company_names"] = companies
        return entities

    def _infer_answer_style(
        self,
        original_query: str,
        intent_plan: IntentPlan,
        results: list[ToolExecutionResult],
    ) -> str:
        """Suy ra kiểu trả lời phù hợp cho final synthesizer."""

        lowered_query = original_query.lower()
        if any(
            marker in lowered_query
            for marker in ("có nên mua", "nen mua", "nên mua", "co nen mua", "có nên đầu tư", "co nen dau tu", "nên đầu tư", "nen dau tu")
        ):
            return "balanced_investment_view"

        success_count = sum(1 for result in results if result.status == ToolExecutionStatus.SUCCESS)
        if success_count >= 2:
            return "integrated_analysis"
        if intent_plan.analysis_requirements.get("comparison"):
            return "comparison_analysis"
        return "concise_answer"

    def _market_highlights(self, result: ToolExecutionResult) -> list[str]:
        """Rút ra highlight ngắn từ dữ liệu market."""

        highlights: list[str] = []
        rows = result.structured_data.get("rows")
        if not isinstance(rows, list) or not rows:
            return [result.summary]

        first_row = rows[0] if isinstance(rows[0], dict) else {}
        ticker = str(first_row.get("ticker") or "").strip()
        if "current_price" in first_row:
            price = self._format_scalar(first_row.get("current_price"))
            if ticker and price:
                highlights.append(f"Giá hiện tại của {ticker} là {price}.")
        if "timestamp" in first_row:
            highlights.append(f"Timestamp dữ liệu market: {first_row.get('timestamp')}.")
        if not highlights:
            highlights.append(result.summary)
        return highlights

    def _news_highlights(self, result: ToolExecutionResult) -> list[str]:
        """Rút highlight từ article_summaries (ưu tiên link + tóm tắt từng bài)."""

        article_summaries = result.structured_data.get("article_summaries")
        if not isinstance(article_summaries, list) or not article_summaries:
            summary_text = str(result.summary or "").strip()
            return [summary_text] if summary_text else []

        highlights: list[str] = []
        for index, item in enumerate(article_summaries[:5], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "Bài viết").strip()
            site = str(item.get("site") or "").strip()
            summary = str(item.get("summary") or "").strip()
            try:
                from src.agents.news_agent.summarizer import NewsSummarizer

                summary = NewsSummarizer.polish_article_summary(summary, title=title, site=site)
            except Exception:
                summary = re.sub(r"^\[[^\]]+\]\s*", "", summary)
            if len(summary) > 280:
                summary = summary[:279].rstrip() + "…"
            url = str(item.get("url") or "").strip()
            published_at = str(item.get("published_at") or "").strip()
            date_part = f", {published_at}" if published_at else ""
            line = f"Bài {index}: {title} ({site}{date_part}) — {summary}"
            if url:
                line += f" | {url}"
            highlights.append(line)
        return highlights

    def _reports_highlights(self, result: ToolExecutionResult) -> list[str]:
        """Rút ra highlight ngắn từ dữ liệu financial reports."""

        highlights: list[str] = []
        filters = result.structured_data.get("filters")
        if isinstance(filters, dict):
            ticker = str(filters.get("ticker") or "").strip()
            year = filters.get("year")
            quarter = filters.get("quarter")
            if ticker and (year or quarter):
                highlights.append(
                    f"Context báo cáo tập trung vào {ticker}"
                    f"{f' quý {quarter}' if quarter else ''}"
                    f"{f' năm {year}' if year else ''}."
                )

        selected_contexts = result.structured_data.get("selected_contexts")
        if isinstance(selected_contexts, list):
            for item in selected_contexts[:2]:
                if not isinstance(item, dict):
                    continue
                section_title = str(item.get("section_title") or "").strip()
                page = item.get("page")
                if section_title:
                    highlights.append(
                        f"Trích dẫn từ phần '{section_title}'"
                        f"{f' trang {page}' if page is not None else ''}."
                    )
        return highlights or [result.summary]

    def _normalize_evidence(
        self,
        tool_name: ToolName,
        evidence_item: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Chuẩn hóa evidence của từng tool về cùng một shape."""

        kind = str(evidence_item.get("kind") or "").strip()
        value = evidence_item.get("value")
        if not kind:
            return None

        normalized = {
            "tool_name": tool_name.value,
            "kind": kind,
            "label": self._build_evidence_label(tool_name, kind, value),
            "value": value,
        }

        if tool_name == ToolName.NEWS and isinstance(value, dict):
            source_ref = str(value.get("url") or value.get("article_id") or value.get("title") or "").strip()
        elif tool_name == ToolName.FINANCIAL_REPORTS and isinstance(value, dict):
            source_ref = (
                f"{value.get('retrieval_id') or ''}:{value.get('page') or ''}".strip(":")
                or str(value.get("preview") or "").strip()
            )
        else:
            source_ref = self._compact_value(value)

        normalized["source_ref"] = source_ref
        normalized["_dedupe_key"] = f"{tool_name.value}:{kind}:{source_ref}"
        return normalized

    def _build_evidence_label(self, tool_name: ToolName, kind: str, value: Any) -> str:
        """Tạo label dễ đọc cho evidence."""

        if tool_name == ToolName.NEWS and isinstance(value, dict):
            site = str(value.get("site") or "").strip()
            title = str(value.get("title") or "").strip()
            return f"Tin báo {site}: {title}".strip(": ")
        if tool_name == ToolName.FINANCIAL_REPORTS and isinstance(value, dict):
            section = str(value.get("section_title") or "").strip()
            retrieval_id = str(value.get("retrieval_id") or "").strip()
            return f"Đoạn báo cáo {retrieval_id}: {section}".strip(": ")
        if tool_name == ToolName.MARKET and kind == "rows_preview":
            return "Dòng dữ liệu market gần nhất"
        if tool_name == ToolName.MARKET and kind == "sql":
            return "SQL đã dùng để truy vấn market"
        return f"{tool_name.value}:{kind}"

    @staticmethod
    def _compact_value(value: Any) -> str:
        """Rút gọn value về chuỗi ổn định để dedupe evidence."""

        if isinstance(value, str):
            return value.strip()
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)

    @staticmethod
    def _format_scalar(value: Any) -> str:
        """Format số liệu gọn cho highlight."""

        if value is None:
            return ""
        if isinstance(value, int):
            return f"{value:,}"
        if isinstance(value, float):
            if value.is_integer():
                return f"{int(value):,}"
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return str(value)

from src.orchestration.state import OrchestrationState
def merge(state: OrchestrationState) -> dict[str, Any]:
    trace=list(state.get("trace", [])); errors=list(state.get("errors", [])); metadata=dict(state.get("metadata", {})); query=str(state.get("query", "") or "").strip(); plan_payload=metadata.get("intent_plan")
    if not query or not isinstance(plan_payload, dict):
        errors.append("merge_missing_inputs"); trace.append({"step":"merger","status":"error","detail":"Missing query or intent_plan for merge step."}); return {"merged_context":None,"trace":trace,"errors":errors,"metadata":metadata}
    try: plan=IntentPlan.model_validate(plan_payload)
    except Exception as exc: errors.append(f"merge_intent_plan_invalid:{exc}"); trace.append({"step":"merger","status":"error","detail":f"Invalid intent_plan payload: {exc}"}); return {"merged_context":None,"trace":trace,"errors":errors,"metadata":metadata}
    tool_results=_collect_tool_results(state)
    if not tool_results:
        errors.append("merge_no_tool_results"); trace.append({"step":"merger","status":"warning","detail":"No tool results available to merge."}); return {"merged_context":None,"trace":trace,"errors":errors,"metadata":metadata}
    try: merged=ContextMerger().merge(query, tool_results, plan)
    except Exception as exc: errors.append(f"merge_error:{exc}"); trace.append({"step":"merger","status":"error","detail":str(exc)}); return {"merged_context":None,"trace":trace,"errors":errors,"metadata":metadata}
    merged_payload=merged.model_dump(mode="json"); metadata["merged_context"]=merged_payload
    trace.append({"step":"merger","status":"ok","detail":"Merged context built successfully.","metadata":{"tool_count":len(tool_results),"evidence_count":len(merged.key_evidence),"limitations_count":len(merged.limitations),"answer_style":merged.answer_style}})
    return {"merged_context":json.dumps(merged_payload, ensure_ascii=False),"trace":trace,"errors":errors,"metadata":metadata}
def _collect_tool_results(state: OrchestrationState) -> list[ToolExecutionResult]:
    out=[]
    for key in ("market_result","news_result","financial_result"):
        agent_result=state.get(key); results=getattr(agent_result,"results",None) if agent_result is not None else None
        if isinstance(results, list): out.extend(result for result in results if isinstance(result, ToolExecutionResult))
    return out
