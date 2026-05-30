"""Tổng hợp câu trả lời cuối từ merged context của nhiều tool."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from config import Settings, get_settings
from core.llm_pool import GeminiKeyPool
from .context_merger import MergedContext
from .trace import TraceCollector

SYNTHESIS_PROMPT_TEMPLATE = """
Bạn là lớp final orchestrator cho hệ thống phân tích chứng khoán Việt Nam.

Nhiệm vụ:
- Trả lời bằng tiếng Việt tự nhiên, mạch lạc, thống nhất.
- Chỉ dùng dữ kiện trong MERGED_CONTEXT dưới đây.
- Không liệt kê máy móc theo kiểu "market: ... news: ...".
- Nếu có đủ evidence từ nhiều tool, hãy hợp nhất chúng thành một phân tích chung.
- Nếu evidence yếu hoặc còn thiếu, phải nói rõ limitation.
- Nếu answer_style là `balanced_investment_view`, hãy:
  - nêu các điểm ủng hộ
  - nêu các rủi ro/caveat
  - tránh kết luận chắc chắn quá mức
- Nếu có tin tức/báo cáo, ưu tiên gắn dữ kiện với nguồn hoặc section khi có thể.

Trả về plain text duy nhất, không dùng JSON.

USER_QUERY:
{user_query}

MERGED_CONTEXT:
{merged_context_json}
"""


class FinalSynthesisResult(BaseModel):
    """Kết quả tổng hợp cuối cùng cho câu trả lời orchestration.

    Attributes:
        answer: Câu trả lời cuối đã được tổng hợp.
        model_name: Tên model hoặc chiến lược được dùng.
        used_fallback: Có phải fallback không dùng LLM hay không.
    """

    answer: str
    model_name: str
    used_fallback: bool = False


class FinalSynthesizer:
    """Tổng hợp câu trả lời cuối từ merged context."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._pool = GeminiKeyPool(
            self.settings,
            generation_config={"temperature": 0.1},
        )

    def synthesize(
        self,
        user_query: str,
        merged_context: MergedContext,
        *,
        trace_collector: TraceCollector | None = None,
    ) -> FinalSynthesisResult:
        """Sinh câu trả lời cuối từ merged context.

        Args:
            user_query: Câu hỏi gốc của người dùng.
            merged_context: Context đã được merger chuẩn hóa.
            trace_collector: Trace collector nếu caller muốn ghi debug.

        Returns:
            FinalSynthesisResult chứa answer cuối và metadata nhẹ.
        """

        prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            user_query=user_query,
            merged_context_json=json.dumps(merged_context.model_dump(mode="json"), ensure_ascii=False, indent=2),
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

    def _record_trace(
        self,
        trace_collector: TraceCollector | None,
        *,
        model_name: str,
        used_fallback: bool,
        merged_context: MergedContext,
    ) -> None:
        """Ghi trace cho bước final synthesis."""

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
        """Tạo câu trả lời fallback có cấu trúc khi LLM không sẵn sàng."""

        successful_tools = [
            item
            for item in merged_context.tool_summaries
            if item.get("status") == "success"
        ]
        answer_style = merged_context.answer_style

        if answer_style == "balanced_investment_view":
            return self._build_balanced_investment_answer(successful_tools, merged_context.limitations)

        paragraphs: list[str] = []
        if successful_tools:
            opening = self._compose_opening(successful_tools)
            if opening:
                paragraphs.append(opening)

            evidence_paragraph = self._compose_evidence_paragraph(successful_tools)
            if evidence_paragraph:
                paragraphs.append(evidence_paragraph)

        if merged_context.limitations:
            paragraphs.append("Điểm còn hạn chế: " + "; ".join(merged_context.limitations[:3]))

        if not paragraphs:
            return "Hiện chưa có đủ dữ liệu đáng tin cậy để đưa ra câu trả lời hợp nhất cho truy vấn này."
        return "\n\n".join(paragraphs)

    def _compose_opening(self, successful_tools: list[dict[str, Any]]) -> str:
        """Tạo đoạn mở đầu nêu bức tranh chung từ các tool."""

        market_summary = self._find_tool_summary(successful_tools, "market")
        news_summary = self._find_tool_summary(successful_tools, "news")
        reports_summary = self._find_tool_summary(successful_tools, "financial_reports")

        clauses: list[str] = []
        if market_summary:
            clauses.append(self._flatten_sentence(str(market_summary.get("summary") or "")))
        if news_summary:
            clauses.append("Ở phía tin tức, " + self._flatten_sentence(str(news_summary.get("summary") or "")))
        if reports_summary:
            clauses.append("Ở phía báo cáo tài chính, " + self._flatten_sentence(str(reports_summary.get("summary") or "")))

        if not clauses:
            return ""
        return " ".join(clause for clause in clauses if clause).strip()

    def _compose_evidence_paragraph(self, successful_tools: list[dict[str, Any]]) -> str:
        """Tạo đoạn evidence ngắn dựa trên highlights đã được merger chuẩn hóa."""

        highlight_lines: list[str] = []
        for item in successful_tools:
            highlights = item.get("highlights") or []
            if not isinstance(highlights, list):
                continue
            for highlight in highlights[:2]:
                text = str(highlight).strip()
                if text:
                    highlight_lines.append(text)

        deduped_lines: list[str] = []
        for line in highlight_lines:
            if line not in deduped_lines:
                deduped_lines.append(line)

        if not deduped_lines:
            return ""
        return "Các điểm nổi bật hỗ trợ cho kết luận này gồm: " + " ".join(deduped_lines[:4])

    def _build_balanced_investment_answer(
        self,
        successful_tools: list[dict[str, Any]],
        limitations: list[str],
    ) -> str:
        """Tạo câu trả lời cân bằng cho câu hỏi kiểu có nên mua không."""

        support_points: list[str] = []
        risk_points: list[str] = []

        for item in successful_tools:
            tool_name = str(item.get("tool_name") or "")
            summary = self._flatten_sentence(str(item.get("summary") or ""))
            if not summary:
                continue

            if tool_name == "market":
                support_points.append(f"Tín hiệu giá hiện tại cho thấy: {summary}")
            elif tool_name == "news":
                support_points.append(f"Dòng tin gần đây cho thấy: {summary}")
            elif tool_name == "financial_reports":
                support_points.append(f"Ở góc độ kết quả kinh doanh: {summary}")

            for limitation in item.get("limitations") or []:
                limitation_text = str(limitation).strip()
                if limitation_text and limitation_text not in risk_points:
                    risk_points.append(limitation_text)

        if limitations:
            for limitation in limitations:
                text = limitation.strip()
                if text and text not in risk_points:
                    risk_points.append(text)

        if not risk_points:
            risk_points.append(
                "Evidence hiện có chưa phản ánh đầy đủ khẩu vị rủi ro, định giá mục tiêu và thời điểm giải ngân."
            )

        sections: list[str] = []
        if support_points:
            sections.append("Các điểm ủng hộ hiện có: " + " ".join(support_points[:3]))
        if risk_points:
            sections.append("Rủi ro và điểm cần thận trọng: " + "; ".join(risk_points[:3]))
        sections.append(
            "Vì vậy, đây mới là đánh giá tham khảo từ dữ liệu hiện có, chưa đủ để khẳng định chắc chắn nên mua hay không nếu thiếu thêm khẩu vị rủi ro và điểm vào lệnh cụ thể."
        )
        return "\n\n".join(sections)

    @staticmethod
    def _find_tool_summary(
        successful_tools: list[dict[str, Any]],
        tool_name: str,
    ) -> dict[str, Any] | None:
        """Tìm summary payload của một tool cụ thể."""

        for item in successful_tools:
            if item.get("tool_name") == tool_name:
                return item
        return None

    @staticmethod
    def _clean_model_text(value: str) -> str:
        """Làm sạch text trả về từ model mà vẫn giữ xuống dòng hợp lý."""

        lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
        cleaned = "\n".join(line for line in lines if line).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    @staticmethod
    def _flatten_sentence(value: str) -> str:
        """Rút gọn một summary về một câu liền mạch."""

        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned.rstrip(".") + "." if cleaned else ""
