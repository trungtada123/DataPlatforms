"""Final synthesis node and canonical synthesis logic."""

from __future__ import annotations

"""Tổng hợp câu trả lời cuối từ merged context của nhiều tool."""


import json
import re
import unicodedata
from typing import Any

from pydantic import BaseModel

from src.config import Settings, get_settings
from src.core.llm_pool import GeminiKeyPool
from src.schemas.orchestration import MergedContext
from src.schemas.orchestration import TraceCollector

SYNTHESIS_PROMPT_TEMPLATE = """
Bạn là biên tập viên phân tích tài chính Việt Nam. Viết câu trả lời CUỐI cho người dùng.

NGÔN NGỮ & MÃ HÓA:
- Chỉ dùng tiếng Việt có dấu UTF-8 chuẩn.
- Không xuất hiện ký tự lỗi kiểu "Ã", "â€™", "khÃ´ng".

ĐỊNH DẠNG BẮT BUỘC (plain text, có tiêu đề section):

## Tóm tắt
2–4 câu ngắn, trả lời trực tiếp USER_QUERY.

## Dữ liệu thị trường
(Bỏ hẳn section này nếu không có dữ liệu market)
- Bullet ngắn: mã, giá, khối lượng, ngày giao dịch — viết tự nhiên, KHÔNG dùng key=value.

## Tin tức liên quan
(Bỏ hẳn section này nếu không có tin)
- Mỗi bài: **Tiêu đề** — nguồn; 1-2 câu tóm tắt; dòng `Link: https://...` (bắt buộc nếu có trong context).
- Tối đa 5 bài; không chép crawl dài; không lặp URL/tiêu đề.

## Góc nhìn tổng hợp
1–3 câu nối market và news (nếu có cả hai).

## Lưu ý
- Bullet ngắn các hạn chế (nếu có); tối đa 3 dòng.

QUY TẮC NỘI DUNG:
- Chỉ dùng dữ kiện trong MERGED_CONTEXT; không bịa.
- Không liệt kê máy móc "market: ... news: ...".
- Không lặp cùng một ý hoặc cùng một URL/tiêu đề.
- Nếu answer_style là `balanced_investment_view`: tách rõ điểm ủng hộ và rủi ro, không khẳng định chắc chắn mua/bán.
- Giá tiền format có dấu phẩy ngàn (ví dụ 24.000 đồng) khi phù hợp.

Chỉ trả plain text, không JSON, không markdown link dài dòng.

USER_QUERY:
{user_query}

MERGED_CONTEXT:
{merged_context_json}
"""


class FinalSynthesisResult(BaseModel):
    """Kết quả tổng hợp cuối cùng cho câu trả lời orchestration."""

    answer: str
    model_name: str
    used_fallback: bool = False


class FinalSynthesizer:
    """Tổng hợp câu trả lời cuối từ merged context."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._pool = GeminiKeyPool(
            self.settings,
            generation_config={"temperature": 0.15},
        )

    def synthesize(
        self,
        user_query: str,
        merged_context: MergedContext,
        *,
        trace_collector: TraceCollector | None = None,
    ) -> FinalSynthesisResult:
        """Sinh câu trả lời cuối từ merged context."""

        compact_context = self._compact_merged_context_for_prompt(merged_context)
        prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            user_query=user_query,
            merged_context_json=json.dumps(compact_context, ensure_ascii=False, indent=2),
        )

        if not self._pool.has_keys():
            answer = self._fallback_answer(merged_context)
            self._record_trace(
                trace_collector,
                model_name="deterministic-fallback",
                used_fallback=True,
                merged_context=merged_context,
            )
            return FinalSynthesisResult(
                answer=answer,
                model_name="deterministic-fallback",
                used_fallback=True,
            )

        try:
            output = self._pool.generate_text(prompt)
            cleaned = self._clean_model_text(output)
            if cleaned:
                self._record_trace(
                    trace_collector,
                    model_name=self.settings.gemini_model,
                    used_fallback=False,
                    merged_context=merged_context,
                )
                return FinalSynthesisResult(
                    answer=cleaned,
                    model_name=self.settings.gemini_model,
                    used_fallback=False,
                )
        except Exception as exc:  # noqa: BLE001
            if trace_collector:
                trace_collector.set_fallback_reason(
                    trace_collector.snapshot().fallback_reason or f"final_synthesizer_failed:{exc}"
                )

        answer = self._fallback_answer(merged_context)
        self._record_trace(
            trace_collector,
            model_name="deterministic-fallback",
            used_fallback=True,
            merged_context=merged_context,
        )
        return FinalSynthesisResult(
            answer=answer,
            model_name="deterministic-fallback",
            used_fallback=True,
        )

    def _compact_merged_context_for_prompt(self, merged_context: MergedContext) -> dict[str, Any]:
        """Rút gọn context trước khi đưa vào prompt để giảm nhiễu và trùng lặp."""

        payload = merged_context.model_dump(mode="json")
        compact_summaries: list[dict[str, Any]] = []

        for item in payload.get("tool_summaries", []):
            if not isinstance(item, dict):
                continue
            summary_item = dict(item)
            summary_item["summary"] = self._truncate_text(str(summary_item.get("summary") or ""), 400)
            highlights = summary_item.get("highlights") or []
            if isinstance(highlights, list):
                summary_item["highlights"] = [
                    self._truncate_text(str(highlight), 180)
                    for highlight in highlights[:3]
                    if str(highlight).strip()
                ]
            compact_summaries.append(summary_item)

        payload["tool_summaries"] = compact_summaries
        payload["limitations"] = self._normalize_limitations(payload.get("limitations") or [])[:5]

        evidence = payload.get("key_evidence") or []
        if isinstance(evidence, list):
            payload["key_evidence"] = evidence[:6]

        return payload

    def _record_trace(
        self,
        trace_collector: TraceCollector | None,
        *,
        model_name: str,
        used_fallback: bool,
        merged_context: MergedContext,
    ) -> None:
        if trace_collector is None:
            return

        trace_collector.set_metadata("synthesizer_model", model_name)
        trace_collector.set_metadata("synthesizer_used_fallback", used_fallback)
        trace_collector.add_event(
            "final_synthesizer.complete",
            detail="Đã tổng hợp câu trả lời cuối.",
            metadata={
                "model_name": model_name,
                "used_fallback": used_fallback,
                "answer_style": merged_context.answer_style,
            },
        )

    def _fallback_answer(self, merged_context: MergedContext) -> str:
        """Fallback có cấu trúc, dễ đọc khi LLM không khả dụng."""

        successful_tools = [
            item
            for item in merged_context.tool_summaries
            if item.get("status") == "success"
        ]

        if merged_context.answer_style == "balanced_investment_view":
            return self._build_balanced_investment_answer(successful_tools, merged_context.limitations)

        sections: list[str] = []

        summary_lines = self._build_summary_section(successful_tools)
        if summary_lines:
            sections.append("## Tóm tắt\n" + "\n".join(summary_lines))

        market_section = self._build_market_section(successful_tools)
        if market_section:
            sections.append(market_section)

        news_section = self._build_news_section(successful_tools)
        if news_section:
            sections.append(news_section)

        synthesis_line = self._build_synthesis_line(successful_tools)
        if synthesis_line:
            sections.append("## Góc nhìn tổng hợp\n" + synthesis_line)

        limitations = self._normalize_limitations(merged_context.limitations)
        if limitations:
            sections.append("## Lưu ý\n" + "\n".join(f"- {item}" for item in limitations[:3]))

        if not sections:
            return "Hiện chưa có đủ dữ liệu đáng tin cậy để đưa ra câu trả lời hợp nhất cho truy vấn này."
        return "\n\n".join(sections)

    def _build_summary_section(self, successful_tools: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        market = self._find_tool_summary(successful_tools, "market")
        news = self._find_tool_summary(successful_tools, "news")

        if market:
            lines.append(self._humanize_tool_summary("market", str(market.get("summary") or "")))
        if news:
            overview = self._extract_news_branch_overview(str(news.get("summary") or ""))
            if overview:
                lines.append(overview)

        if not lines and successful_tools:
            first = successful_tools[0]
            lines.append(self._humanize_tool_summary(str(first.get("tool_name") or ""), str(first.get("summary") or "")))

        return [line for line in lines if line]

    def _build_market_section(self, successful_tools: list[dict[str, Any]]) -> str:
        market = self._find_tool_summary(successful_tools, "market")
        if not market:
            return ""

        bullets: list[str] = []
        summary = self._humanize_tool_summary("market", str(market.get("summary") or ""))
        if summary:
            bullets.append(f"- {summary}")

        for highlight in market.get("highlights") or []:
            text = self._truncate_text(str(highlight), 160)
            if text and text not in bullets:
                bullets.append(f"- {text.lstrip('- ')}")
            if len(bullets) >= 3:
                break

        if not bullets:
            return ""
        return "## Dữ liệu thị trường\n" + "\n".join(bullets[:3])

    def _build_news_section(self, successful_tools: list[dict[str, Any]]) -> str:
        news = self._find_tool_summary(successful_tools, "news")
        if not news:
            return ""

        articles = news.get("structured_articles") if isinstance(news.get("structured_articles"), list) else []
        bullets: list[str] = []
        seen: set[str] = set()

        if articles:
            for index, item in enumerate(articles[:5], start=1):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "Bài viết").strip()
                site = str(item.get("site") or "").strip()
                summary = self._truncate_text(
                    self._clean_article_summary_for_display(
                        str(item.get("summary") or ""),
                        title=title,
                        site=site,
                    ),
                    320,
                )
                url = str(item.get("url") or "").strip()
                key = url or title.lower()
                if key in seen:
                    continue
                seen.add(key)
                line = f"**{title}**"
                if site:
                    line += f" — {site}"
                line += f"\n  {summary}"
                if url:
                    line += f"\n  Link: {url}"
                bullets.append(f"- {line}")
        else:
            for highlight in news.get("highlights") or []:
                bullet = self._format_news_bullet(str(highlight))
                if not bullet:
                    continue
                key = bullet.lower()
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(f"- {bullet}")
                if len(bullets) >= 5:
                    break

        if not bullets:
            branch_summary = self._truncate_text(str(news.get("summary") or ""), 1200)
            if branch_summary:
                bullets.append(branch_summary)

        if not bullets:
            return ""
        return "## Tin tức liên quan\n" + "\n".join(bullets)

    def _build_synthesis_line(self, successful_tools: list[dict[str, Any]]) -> str:
        tool_names = {str(item.get("tool_name") or "") for item in successful_tools}
        if "market" in tool_names and "news" in tool_names:
            return (
                "Kết hợp giá/khối lượng gần nhất với tin vừa crawl, nên đọc cùng nhau: "
                "giá phản ánh thị trường, tin giải thích bối cảnh ngắn hạn."
            )
        if len(tool_names) == 1:
            return "Câu trả lời dựa trên một nguồn dữ liệu; nên bổ sung thêm tool khác nếu cần góc nhìn đầy đủ hơn."
        return ""

    def _build_balanced_investment_answer(
        self,
        successful_tools: list[dict[str, Any]],
        limitations: list[str],
    ) -> str:
        support_points: list[str] = []
        risk_points: list[str] = []

        for item in successful_tools:
            tool_name = str(item.get("tool_name") or "")
            summary = self._humanize_tool_summary(tool_name, str(item.get("summary") or ""))
            if not summary:
                continue

            if tool_name == "market":
                support_points.append(f"Thị trường: {summary}")
            elif tool_name == "news":
                support_points.append(f"Tin tức: {summary}")
            elif tool_name == "financial_reports":
                support_points.append(f"Báo cáo: {summary}")

            for limitation in item.get("limitations") or []:
                limitation_text = self._normalize_limitation_text(str(limitation))
                if limitation_text and limitation_text not in risk_points:
                    risk_points.append(limitation_text)

        for limitation in self._normalize_limitations(limitations):
            if limitation not in risk_points:
                risk_points.append(limitation)

        if not risk_points:
            risk_points.append(
                "Chưa đủ dữ liệu về khẩu vị rủi ro, định giá mục tiêu và thời điểm vào lệnh."
            )

        sections = ["## Tóm tắt\nĐánh giá tham khảo từ dữ liệu hiện có, chưa phải khuyến nghị mua/bán chắc chắn."]
        if support_points:
            sections.append("## Điểm ủng hộ\n" + "\n".join(f"- {point}" for point in support_points[:3]))
        if risk_points:
            sections.append("## Rủi ro / hạn chế\n" + "\n".join(f"- {point}" for point in risk_points[:3]))
        return "\n\n".join(sections)

    @staticmethod
    def _find_tool_summary(
        successful_tools: list[dict[str, Any]],
        tool_name: str,
    ) -> dict[str, Any] | None:
        for item in successful_tools:
            if item.get("tool_name") == tool_name:
                return item
        return None

    @staticmethod
    def _extract_news_branch_overview(summary: str) -> str:
        """Chỉ lấy 1–2 câu tóm tắt nhánh news, không nhét markdown bài vào ## Tóm tắt cuối."""

        text = summary.strip()
        if not text:
            return ""

        match = re.search(r"##\s*Tóm tắt\s*\n+(.*?)(?=\n##\s+|\Z)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1).strip()

        text = re.sub(r"^#+\s*", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        lowered = text.lower()
        if "cac bai da crawl" in lowered or "### " in text:
            return ""

        return FinalSynthesizer._truncate_text(text, 280)

    @staticmethod
    def _clean_article_summary_for_display(summary: str, *, title: str, site: str) -> str:
        try:
            from src.agents.news_agent.summarizer import NewsSummarizer

            return NewsSummarizer.polish_article_summary(summary, title=title, site=site)
        except Exception:
            cleaned = re.sub(r"^\[[^\]]+\]\s*", "", summary.strip())
            return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _humanize_tool_summary(tool_name: str, summary: str) -> str:
        cleaned = re.sub(r"\s+", " ", summary).strip()
        if not cleaned:
            return ""

        cleaned = re.sub(
            r"Kết quả phù hợp nhất là:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b(ticker|current_price|volume|trading_date)\s*=", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;")

        if tool_name == "market" and cleaned and not cleaned[0].isupper():
            cleaned = cleaned[0].upper() + cleaned[1:]

        return FinalSynthesizer._truncate_text(cleaned, 320)

    @staticmethod
    def _format_news_bullet(raw: str) -> str:
        text = re.sub(r"\s+", " ", raw).strip()
        if not text:
            return ""

        match = re.match(r"\[([^\]]+)\]\s*([^:]+):\s*(.+)$", text)
        if match:
            site, title, _body = match.groups()
            title = FinalSynthesizer._truncate_text(title.strip(), 90)
            return f"**{title}** — {site.strip()}"

        if len(text) > 140:
            return FinalSynthesizer._truncate_text(text, 140)
        return text

    @staticmethod
    def _truncate_text(value: str, max_len: int) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if len(cleaned) <= max_len:
            return cleaned
        return cleaned[: max_len - 1].rstrip() + "…"

    @staticmethod
    def _normalize_limitation_text(value: str) -> str:
        text = FinalSynthesizer._fix_text_encoding(value.strip())
        text = re.sub(r"\s+", " ", text)
        return text

    def _normalize_limitations(self, limitations: list[Any]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for item in limitations:
            text = self._normalize_limitation_text(str(item))
            if not text:
                continue
            key = unicodedata.normalize("NFC", text.casefold())
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return normalized

    @staticmethod
    def _fix_text_encoding(value: str) -> str:
        if not value or "Ã" not in value and "â" not in value:
            return value
        try:
            repaired = value.encode("latin1").decode("utf-8")
            if repaired and "Ã" not in repaired:
                return repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return value

    @staticmethod
    def _clean_model_text(value: str) -> str:
        value = FinalSynthesizer._fix_text_encoding(value)
        lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
        cleaned = "\n".join(line for line in lines if line).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned


from src.orchestration.state import OrchestrationState


def synthesize(state: OrchestrationState) -> dict[str, Any]:
    trace = list(state.get("trace", []))
    errors = list(state.get("errors", []))
    metadata = dict(state.get("metadata", {}))
    query = str(state.get("query", "") or "").strip()
    merged_payload = metadata.get("merged_context")
    if not isinstance(merged_payload, dict):
        trace.append(
            {
                "step": "synthesizer",
                "status": "warning",
                "detail": "Merged context is missing. Returning insufficient-data answer.",
            }
        )
        return {
            "final_answer": "Hiện chưa đủ context hợp lệ để tổng hợp câu trả lời. Vui lòng thử lại sau khi dữ liệu được bổ sung.",
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }
    try:
        merged_context = MergedContext.model_validate(merged_payload)
    except Exception as exc:
        errors.append(f"synthesizer_merged_context_invalid:{exc}")
        trace.append(
            {
                "step": "synthesizer",
                "status": "error",
                "detail": f"Invalid merged context payload: {exc}",
            }
        )
        return {
            "final_answer": "Không thể tổng hợp câu trả lời vì dữ liệu context không hợp lệ.",
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }
    if not query:
        errors.append("synthesizer_missing_query")
        trace.append({"step": "synthesizer", "status": "error", "detail": "Missing user query in state."})
        return {
            "final_answer": "Không thể tổng hợp câu trả lời vì thiếu câu hỏi đầu vào.",
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }
    try:
        result = FinalSynthesizer().synthesize(query, merged_context)
    except Exception as exc:
        errors.append(f"synthesizer_error:{exc}")
        trace.append({"step": "synthesizer", "status": "error", "detail": str(exc)})
        return {
            "final_answer": "Không thể tổng hợp câu trả lời ở thời điểm hiện tại.",
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }
    trace.append(
        {
            "step": "synthesizer",
            "status": "ok",
            "detail": "Final answer synthesized successfully.",
            "metadata": {"model_name": result.model_name, "used_fallback": result.used_fallback},
        }
    )
    return {"final_answer": result.answer, "trace": trace, "errors": errors, "metadata": metadata}
