"""LLM rewrite và synthesis cho financial reports runtime."""

from __future__ import annotations

import json
import re
from typing import Any

from src.core.llm_pool import GroqKeyPool
from src.config.financial import FinancialReportsToolSettings
from .retrieval import (
    context_block,
    detect_focus,
    detect_metric_targets,
    fold_text,
    has_explicit_focus_evidence,
    payload_text,
    question_has_opinion_signal,
)


REWRITE_PROMPT_TEMPLATE = """
Bạn là bộ tiền xử lý truy vấn cho hệ thống RAG báo cáo tài chính tiếng Việt.
Nhiệm vụ: chuẩn hóa câu hỏi người dùng để truy vấn vector DB chính xác hơn.

Trả về JSON hợp lệ với schema:
{
  "normalized_question": "...",
  "focus": "amount|unit|method|policy|numbered_section|generic",
  "retrieval_queries": ["...", "...", "..."]
}

Quy tắc:
- Giữ nguyên tiếng Việt.
- Nếu câu hỏi hỏi số liệu, hãy tạo 2-3 câu truy vấn ngắn hơn, sát row/bảng hơn.
- Nếu câu hỏi hỏi phương pháp, đơn vị tính hoặc kỳ báo cáo, hãy tạo truy vấn bám đúng cụm từ đó.
- Không thêm thông tin ngoài câu hỏi.
- Chỉ trả JSON.

Câu hỏi gốc: {question}
""".strip()


class FinancialReportsSynthesizer:
    """Hỗ trợ rewrite query và synthesis grounded answer."""

    def __init__(self, settings: FinancialReportsToolSettings) -> None:
        self.settings = settings
        self._pool = GroqKeyPool(settings) if settings.groq_api_keys or settings.groq_api_key else None

    def rewrite_query(self, question: str) -> dict[str, Any]:
        """Tùy chọn dùng Groq để rewrite retrieval query."""

        if self._pool is None or not self.settings.enable_llm_rewrite:
            return {
                "normalized_question": question,
                "focus": detect_focus(question),
                "retrieval_queries": [question],
            }
        prompt = REWRITE_PROMPT_TEMPLATE.format(question=question)
        output = self._pool.generate_text(prompt)
        parsed = self._safe_json_extract(output)
        if parsed is None:
            raise ValueError("Could not parse financial reports rewrite JSON.")
        return parsed

    def synthesize(
        self,
        *,
        user_query: str,
        normalized_question: str,
        context_items: list[dict[str, Any]],
    ) -> str:
        """Tổng hợp câu trả lời grounded từ context đã chọn."""

        focus = detect_focus(normalized_question)
        if focus in {"unit", "method", "policy"} and not has_explicit_focus_evidence(focus, context_items):
            source_refs = ", ".join(
                f"page={item.get('page')} retrieval_id={item.get('retrieval_id')}"
                for item in context_items[:2]
                if item.get("retrieval_id")
            )
            suffix = f" Nguồn đã kiểm tra: {source_refs}." if source_refs else ""
            return f"Không đủ dữ liệu trong context để kết luận cho câu hỏi này.{suffix}"

        explicit_amount_answer = self._extract_explicit_amount_answer(normalized_question, context_items)
        if explicit_amount_answer is not None:
            return explicit_amount_answer

        explicit_opinion_answer = self._extract_explicit_opinion_answer(normalized_question, context_items)
        if explicit_opinion_answer is not None:
            return explicit_opinion_answer

        if self._pool is None:
            return self._fallback_synthesis(context_items)

        context_text = "\n\n".join(
            f"[Context {idx}]\n{context_block(payload)}" for idx, payload in enumerate(context_items, start=1)
        )
        prompt = (
            "Bạn là trợ lý phân tích báo cáo tài chính. "
            "Bạn PHẢI trả lời bằng tiếng Việt. "
            "Bạn chỉ được dựa vào context được cung cấp. "
            "Nếu context đã có đáp án trực tiếp thì câu đầu tiên phải trả lời thẳng vào đáp án. "
            "Nếu thiếu dữ liệu thật sự, phải trả lời đúng câu: 'Không đủ dữ liệu trong context để kết luận cho câu hỏi này.' "
            "Cuối câu trả lời, nêu ngắn gọn page/retrieval_id đã dùng.\n\n"
            f"Câu hỏi gốc: {user_query}\n"
            f"Câu hỏi chuẩn hóa: {normalized_question}\n\n"
            f"Context:\n{context_text}\n"
        )
        try:
            return self._clean_text(self._pool.generate_text(prompt))
        except Exception:
            return self._fallback_synthesis(context_items)

    def model_name(self) -> str:
        """Trả về model synthesis hiện tại để trace/debug."""

        return self.settings.groq_model if self._pool is not None else "fallback"

    @staticmethod
    def _safe_json_extract(text: str) -> dict[str, Any] | None:
        text = text.strip()
        if not text:
            return None
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_explicit_opinion_answer(
        normalized_question: str,
        context_items: list[dict[str, Any]],
    ) -> str | None:
        """Trả lời trực tiếp nếu context đã chứa kết luận soát xét/kiểm toán rõ ràng."""

        if not question_has_opinion_signal(normalized_question):
            return None

        for item in context_items:
            content = re.sub(r"\s+", " ", payload_text(item)).strip()
            content_fold = fold_text(content)
            if "khong thay co van de gi" in content_fold:
                page = item.get("page")
                retrieval_id = item.get("retrieval_id")
                page_ref = f"page={page}" if page is not None else "page=?"
                retrieval_ref = f"retrieval_id={retrieval_id}" if retrieval_id else "retrieval_id=?"
                return (
                    "Kết luận soát xét cho thấy kiểm toán viên không thấy có vấn đề gì khiến báo cáo tài chính giữa niên độ "
                    "đính kèm không phản ánh trung thực và hợp lý trên các khía cạnh trọng yếu. "
                    f"Page/retrieval_id đã dùng: {page_ref} {retrieval_ref}."
                )
        return None

    @staticmethod
    def _extract_explicit_amount_answer(
        normalized_question: str,
        context_items: list[dict[str, Any]],
    ) -> str | None:
        """Trả lời trực tiếp từ row_values khi context đã có đúng row số liệu."""

        metric_targets = detect_metric_targets(normalized_question)
        if not metric_targets:
            return None

        requested_dates = FinancialReportsSynthesizer._extract_requested_dates(normalized_question)
        question_fold = fold_text(normalized_question)

        for metric_name in metric_targets:
            for item in context_items:
                metadata = item.get("metadata") or {}
                row_label = fold_text(str(metadata.get("row_label") or ""))
                row_values = metadata.get("row_values") or {}
                if not isinstance(row_values, dict):
                    continue
                if metric_name != row_label and metric_name not in row_label:
                    continue

                selected_pairs = FinancialReportsSynthesizer._select_requested_row_values(
                    row_values=row_values,
                    requested_dates=requested_dates,
                    question_fold=question_fold,
                )
                if not selected_pairs:
                    continue

                label_text = {
                    "tong tai san": "Tổng tài sản",
                    "cho vay khach hang": "Cho vay khách hàng",
                    "tien gui cua khach hang": "Tiền gửi của khách hàng",
                    "loi nhuan sau thue": "Lợi nhuận sau thuế",
                }.get(metric_name, str(metadata.get("row_label") or metric_name))
                scope = str(item.get("scope") or "")
                scope_text = {
                    "Congtyme": "riêng",
                    "Hopnhat": "hợp nhất",
                }.get(scope, "")
                prefix = "Theo báo cáo tài chính"
                if scope_text:
                    prefix += f" {scope_text}"
                page = item.get("page")
                retrieval_id = item.get("retrieval_id")
                if len(selected_pairs) >= 2:
                    value_text = " và ".join(
                        f"tại {date_label} là {value}" for date_label, _key, value in selected_pairs
                    )
                    return (
                        f"{prefix}, {label_text} {value_text}. "
                        f"Page/retrieval_id: page={page}, retrieval_id={retrieval_id}."
                    )

                selected_date_label, selected_key, selected_value = selected_pairs[0]
                key_text = f" ({selected_key})" if selected_key else ""
                date_text = f" tại {selected_date_label}" if selected_date_label else ""
                return (
                    f"{prefix}, {label_text}{date_text}{key_text} là {selected_value}. "
                    f"Page/retrieval_id: page={page}, retrieval_id={retrieval_id}."
                )
        return None

    @staticmethod
    def _looks_like_numeric_value(value: str) -> bool:
        """Chỉ nhận các ô thật sự là số liệu để tránh nhặt nhầm label dòng."""

        compact = value.strip()
        return re.search(r"\d", compact) is not None

    @staticmethod
    def _extract_requested_dates(question: str) -> list[str]:
        """Rút các mốc ngày explicit từ câu hỏi để trả đủ nhiều cột khi cần."""

        dates = []
        for match in re.findall(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{4}\b", question):
            if match not in dates:
                dates.append(match)
        return dates

    @staticmethod
    def _select_requested_row_values(
        *,
        row_values: dict[str, Any],
        requested_dates: list[str],
        question_fold: str,
    ) -> list[tuple[str, str, str]]:
        """Chọn một hoặc nhiều cột số liệu từ row_values tương ứng với câu hỏi."""

        selected: list[tuple[str, str, str]] = []
        used_keys: set[str] = set()

        for requested_date in requested_dates:
            matched = FinancialReportsSynthesizer._match_row_value_for_date(row_values, requested_date)
            if matched is None:
                continue
            date_label, key, value = matched
            if key in used_keys:
                continue
            selected.append((date_label, key, value))
            used_keys.add(key)

        if selected:
            return selected

        preferred_date_markers = ["30.6.2025", "30/06/2025"] if "2025" in question_fold else []
        for key, value in row_values.items():
            key_fold = fold_text(str(key))
            if (
                any(marker in key_fold for marker in preferred_date_markers)
                and FinancialReportsSynthesizer._looks_like_numeric_value(str(value))
            ):
                return [("", str(key), str(value).strip())]
        for key, value in row_values.items():
            key_fold = fold_text(str(key))
            if "2025" in key_fold and FinancialReportsSynthesizer._looks_like_numeric_value(str(value)):
                return [("", str(key), str(value).strip())]
        for key, value in row_values.items():
            if str(key).strip() and FinancialReportsSynthesizer._looks_like_numeric_value(str(value)):
                return [("", str(key), str(value).strip())]
        return []

    @staticmethod
    def _match_row_value_for_date(
        row_values: dict[str, Any],
        requested_date: str,
    ) -> tuple[str, str, str] | None:
        """Tìm đúng cột row_values khớp với mốc ngày được hỏi."""

        candidates = FinancialReportsSynthesizer._date_marker_candidates(requested_date)
        for key, value in row_values.items():
            key_fold = fold_text(str(key))
            if any(candidate in key_fold for candidate in candidates) and FinancialReportsSynthesizer._looks_like_numeric_value(
                str(value)
            ):
                return (requested_date, str(key), str(value).strip())
        return None

    @staticmethod
    def _date_marker_candidates(date_text: str) -> list[str]:
        """Sinh các biến thể ngày để match với key như 30.6.2025 / 30/06/2025."""

        match = re.match(r"^\s*(\d{1,2})[/.](\d{1,2})[/.](\d{4})\s*$", date_text)
        if not match:
            return [fold_text(date_text)]
        day = int(match.group(1))
        month = int(match.group(2))
        year = match.group(3)
        variants = [
            f"{day}.{month}.{year}",
            f"{day:02d}.{month:02d}.{year}",
            f"{day}/{month}/{year}",
            f"{day:02d}/{month:02d}/{year}",
        ]
        return [fold_text(item) for item in variants]

    @staticmethod
    def _fallback_synthesis(context_items: list[dict[str, Any]]) -> str:
        if not context_items:
            return "Không đủ dữ liệu trong context để kết luận cho câu hỏi này."
        first = context_items[0]
        preview = re.sub(r"\s+", " ", context_block(first)).strip()
        return (
            "Dựa trên ngữ cảnh truy xuất được, thông tin phù hợp nhất là: "
            f"{preview[:420]}"
            + ("..." if len(preview) > 420 else "")
        )
