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
Bạn là biên tập viên phân tích tài chính Việt Nam. Viết câu trả lời CUỐI (plain text) cho USER_QUERY,
chỉ dựa trên MERGED_CONTEXT — đây là kết quả đã merge từ các nhánh tool (market / news / financial_reports).

NGÔN NGỮ:
- Tiếng Việt có dấu UTF-8 chuẩn; không ký tự lỗi (Ã, â€™, khÃ´ng).
- Không lộ thuật ngữ nội bộ: tool_summaries, structured_articles, answer_style, MERGED_CONTEXT.

ĐỌC CONTEXT:
- `tool_summaries[]`: mỗi phần tử là một nhánh đã chạy (`tool_name`, `status`, `summary`, `highlights`, có thể có `structured_articles`).
- `normalized_entities`: tickers, company_names, news_sites.
- `limitations`: hạn chế dữ liệu — phải phản ánh ở ## Lưu ý nếu liên quan.
- `answer_style`: quyết định khung trả lời (xem bên dưới).
- Bỏ qua nhánh `status` khác `success` khi viết nội dung chính; chỉ nhắc ngắn trong ## Lưu ý nếu thiếu dữ liệu quan trọng.

HƯỚNG DẪN THEO CÂU HỎI (ưu tiên cao):
{synthesis_guidance}

KHUNG THEO answer_style = `{answer_style}`:

A) `balanced_investment_view` (câu hỏi có nên mua/đầu tư):
## Tóm tắt — 2–3 câu: đánh giá tham khảo, KHÔNG khuyến nghị mua/bán chắc chắn.
## Điểm ủng hộ — bullet từ dữ kiện market/news/BCTC (nếu có).
## Rủi ro / hạn chế — bullet rủi ro + limitations.
(Không cần section Dữ liệu thị trường / Tin tức riêng trừ khi user cũng hỏi số liệu cụ thể.)

B) `comparison_analysis` (so sánh giá/ngày/mã):
## Tóm tắt — kết luận so sánh.
## Dữ liệu thị trường — bullet từng mốc/ngày/mã; số có dấu chấm ngàn (24.000).
## Lưu ý — nếu thiếu mốc so sánh.

C) `concise_answer` (một nhánh, câu hỏi đơn giản):
## Tóm tắt — 2–4 câu trả lời trực tiếp, đủ ý, không lặp section chi tiết.

D) `integrated_analysis` (mặc định, nhiều nhánh hoặc câu phức hợp):
## Tóm tắt — 2–4 câu TRẢ LỜI TRỰC TIẾP USER_QUERY (giá/KL, tin chính, tác động nếu được hỏi).
  - KHÔNG lặp nguyên văn bullet ở section sau.
  - KHÔNG dùng câu placeholder kiểu "Tóm tắt các tin mới crawl từ nguồn đã chọn".
## Dữ liệu thị trường — CHỈ khi có nhánh market success; 1–2 bullet: mã, giá (đồng), khối lượng (có dấu chấm ngàn), phiên/ngày.
## Tin tức liên quan — CHỈ khi có nhánh news success; tối đa 5 bài:
  - Mỗi bài: **Tiêu đề** — nguồn (ngày nếu có); 1–2 câu ý chính (paraphrase summary, KHÔNG chép menu/web rác);
  - Dòng `Link: https://...` nếu có url trong structured_articles.
## Góc nhìn tổng hợp — BẮT BUỘC nếu có ≥2 nhánh success:
  - Nối tin ↔ giá/số liệu; nếu user hỏi "ảnh hưởng/tác động/đáng chú ý": nêu 2–4 kênh tác động có căn cứ (cung cổ, lãi vay, triển vọng ngành…), dùng "có thể"/"cần theo dõi", không bịa số.
  - Không viết câu chung chung kiểu "nên đọc cùng nhau" mà không nêu ý tin cụ thể.
## Báo cáo tài chính — CHỈ khi có nhánh financial_reports success:
  - Bullet chỉ tiêu/quý/năm từ summary/highlights; không trùng ## Dữ liệu thị trường.
## Lưu ý — bullet limitations (tối đa 3); ghi thiếu tin/market/BCTC nếu có.

TRƯỜNG HỢP CHỈ MỘT NHÁNH:
- Chỉ market → ## Tóm tắt + ## Dữ liệu thị trường (có thể gộp nếu ngắn).
- Chỉ news → ## Tóm tắt + ## Tin tức liên quan.
- Chỉ financial_reports → ## Tóm tắt + ## Báo cáo tài chính.

CẤM:
- Bịa số liệu, link, tiêu đề không có trong context.
- Lặp cùng câu giá/KL ở Tóm tắt và Dữ liệu thị trường.
- Chép snippet crawl (Đăng nhập, menu, "TIN MỚI", English nav).
- Liệt kê "market: ... news: ..." hoặc JSON.

ĐỊNH DẠNG SỐ: giá và khối lượng dùng dấu chấm ngàn (16.925.300 cp, 24.000 đồng) khi có trong dữ liệu.

Chỉ trả plain text; không JSON; không bọc ``` .

USER_QUERY:
{user_query}

MERGED_CONTEXT:
{merged_context_json}
"""

_NEWS_PLACEHOLDER_MARKERS = (
    "cac bai da crawl",
    "cac tin moi crawl",
    "tin moi crawl tu nguon",
    "tom tat cac tin moi crawl",
    "tu nguon da chon",
    "lien quan cau hoi",
    "chua tim thay bai viet",
)


def _fold_vietnamese(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _query_intent_flags(query: str) -> dict[str, bool]:
    folded = _fold_vietnamese(query)

    return {
        "asks_price_volume": any(
            token in folded
            for token in (
                "gia hien tai",
                "gia cp",
                "khoi luong",
                "volume",
                "price",
                "thanh khoan",
                "phien",
            )
        ),
        "asks_news": any(
            token in folded
            for token in ("tin tuc", "tin moi", "bao chi", "headline", "news", "danh chu y")
        ),
        "asks_impact": any(
            token in folded
            for token in (
                "anh huong",
                "tac dong",
                "phan ung",
                "co the anh huong",
                "danh chu y",
                "dong thoi",
            )
        ),
        "asks_comparison": any(
            token in folded for token in ("so sanh", "compare", "va ngay", "giua")
        ),
        "asks_investment": any(
            token in folded
            for token in ("co nen mua", "nen mua", "nen dau tu", "co nen dau tu", "mua khong")
        ),
        "asks_financial_report": any(
            token in folded
            for token in ("bao cao tai chinh", "bctc", "quy ", "financial report", "kqkd")
        ),
    }


def _is_placeholder_news_text(text: str) -> bool:
    folded = _fold_vietnamese(text)
    return any(marker in folded for marker in _NEWS_PLACEHOLDER_MARKERS)


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
            answer_style=merged_context.answer_style,
            synthesis_guidance=self._build_synthesis_guidance(user_query, merged_context),
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
            raw_summary = str(summary_item.get("summary") or "")
            if summary_item.get("tool_name") == "news" and _is_placeholder_news_text(raw_summary):
                raw_summary = ""
            summary_item["summary"] = self._truncate_text(raw_summary, 400)
            highlights = summary_item.get("highlights") or []
            if isinstance(highlights, list):
                deduped_highlights: list[str] = []
                for highlight in highlights[:5]:
                    text = str(highlight).strip()
                    if not text or text in deduped_highlights:
                        continue
                    if summary_item.get("tool_name") == "news" and _is_placeholder_news_text(text):
                        continue
                    deduped_highlights.append(self._truncate_text(text, 180))
                    if len(deduped_highlights) >= 3:
                        break
                summary_item["highlights"] = deduped_highlights
            if summary_item.get("tool_name") == "market" and summary_item["highlights"]:
                summary_item["highlights"] = []
            compact_summaries.append(summary_item)

        payload["tool_summaries"] = compact_summaries
        payload["limitations"] = self._normalize_limitations(payload.get("limitations") or [])[:5]

        evidence = payload.get("key_evidence") or []
        if isinstance(evidence, list):
            payload["key_evidence"] = evidence[:6]

        payload["query_intents"] = _query_intent_flags(merged_context.user_query)
        return payload

    @staticmethod
    def _build_synthesis_guidance(user_query: str, merged_context: MergedContext) -> str:
        """Sinh hướng dẫn ngắn theo câu hỏi và nhánh đã merge thành công."""

        intents = _query_intent_flags(user_query)
        successful_tools = [
            str(item.get("tool_name") or "")
            for item in merged_context.tool_summaries
            if item.get("status") == "success"
        ]
        tools_label = ", ".join(successful_tools) if successful_tools else "không có nhánh success"

        lines = [f"- Nhánh dữ liệu khả dụng: {tools_label}."]

        if intents["asks_price_volume"] and "market" in successful_tools:
            lines.append("- User hỏi giá/khối lượng: nêu rõ mã, giá, KL, ngày phiên trong ## Dữ liệu thị trường.")
        elif intents["asks_price_volume"] and "market" not in successful_tools:
            lines.append("- User hỏi giá/khối lượng nhưng thiếu market: nói ngắn trong ## Lưu ý.")

        if intents["asks_news"] and "news" in successful_tools:
            lines.append("- User hỏi tin: tóm tắt từng bài có Link; không dùng câu placeholder crawl.")
        elif intents["asks_news"] and "news" not in successful_tools:
            lines.append("- User hỏi tin nhưng thiếu news: nói ngắn trong ## Lưu ý.")

        if intents["asks_impact"] and len(successful_tools) >= 2:
            lines.append(
                "- User hỏi tác động/đáng chú ý: ## Góc nhìn tổng hợp phải nêu kênh ảnh hưởng lên mã "
                "(cổ tức/cổ phiếu, chi phí, triển vọng ngành…) bám summary bài tin + giá, không khẳng định chắc chắn."
            )

        if intents["asks_financial_report"] and "financial_reports" in successful_tools:
            lines.append("- User hỏi BCTC: dùng section ## Báo cáo tài chính.")

        if intents["asks_comparison"]:
            lines.append("- User so sánh: làm rõ từng mốc thời gian/mã, tránh gộp chung một số.")

        if merged_context.answer_style == "balanced_investment_view" or intents["asks_investment"]:
            lines.append("- Phong cách đầu tư: không khuyến nghị mua/bán tuyệt đối; tách ủng hộ vs rủi ro.")

        tickers = merged_context.normalized_entities.get("tickers") if merged_context.normalized_entities else []
        if isinstance(tickers, list) and tickers:
            lines.append(f"- Mã liên quan ưu tiên: {', '.join(str(t) for t in tickers[:5])}.")

        return "\n".join(lines)

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
        user_query = merged_context.user_query

        summary_lines = self._build_summary_section(successful_tools, user_query)
        if summary_lines:
            sections.append("## Tóm tắt\n" + "\n".join(summary_lines))

        market_section = self._build_market_section(successful_tools)
        if market_section:
            sections.append(market_section)

        news_section = self._build_news_section(successful_tools)
        if news_section:
            sections.append(news_section)

        reports_section = self._build_reports_section(successful_tools)
        if reports_section:
            sections.append(reports_section)

        synthesis_line = self._build_synthesis_line(successful_tools, user_query)
        if synthesis_line:
            sections.append("## Góc nhìn tổng hợp\n" + synthesis_line)

        limitations = self._normalize_limitations(merged_context.limitations)
        if limitations:
            sections.append("## Lưu ý\n" + "\n".join(f"- {item}" for item in limitations[:3]))

        if not sections:
            return "Hiện chưa có đủ dữ liệu đáng tin cậy để đưa ra câu trả lời hợp nhất cho truy vấn này."
        return "\n\n".join(sections)

    def _build_summary_section(self, successful_tools: list[dict[str, Any]], user_query: str) -> list[str]:
        lines: list[str] = []
        market = self._find_tool_summary(successful_tools, "market")
        news = self._find_tool_summary(successful_tools, "news")
        reports = self._find_tool_summary(successful_tools, "financial_reports")
        intents = _query_intent_flags(user_query)

        if market and news and intents["asks_impact"]:
            impact_line = self._build_impact_summary_line(user_query, market, news)
            if impact_line:
                return [impact_line]

        if news:
            overview = self._news_overview_from_articles(news) or self._extract_news_branch_overview(
                str(news.get("summary") or "")
            )
            if overview:
                lines.append(overview)

        if market and intents["asks_price_volume"]:
            if news:
                short_market = self._short_market_reference(market)
                if short_market and short_market not in lines:
                    lines.insert(0, short_market)
            else:
                lines.insert(0, self._humanize_tool_summary("market", str(market.get("summary") or "")))

        if reports and intents["asks_financial_report"] and not lines:
            lines.append(self._humanize_tool_summary("financial_reports", str(reports.get("summary") or "")))

        if not lines and successful_tools:
            first = successful_tools[0]
            lines.append(self._humanize_tool_summary(str(first.get("tool_name") or ""), str(first.get("summary") or "")))

        return [line for line in lines if line]

    def _build_market_section(self, successful_tools: list[dict[str, Any]]) -> str:
        market = self._find_tool_summary(successful_tools, "market")
        if not market:
            return ""

        summary = self._format_market_bullet(self._humanize_tool_summary("market", str(market.get("summary") or "")))
        if not summary:
            return ""
        return "## Dữ liệu thị trường\n" + f"- {summary}"

    def _build_reports_section(self, successful_tools: list[dict[str, Any]]) -> str:
        reports = self._find_tool_summary(successful_tools, "financial_reports")
        if not reports:
            return ""

        bullets: list[str] = []
        summary = self._humanize_tool_summary("financial_reports", str(reports.get("summary") or ""))
        if summary:
            bullets.append(f"- {summary}")

        for highlight in reports.get("highlights") or []:
            text = self._truncate_text(str(highlight), 200)
            if text and text not in bullets:
                bullets.append(f"- {text.lstrip('- ')}")
            if len(bullets) >= 3:
                break

        if not bullets:
            return ""
        return "## Báo cáo tài chính\n" + "\n".join(bullets[:3])

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

    def _build_synthesis_line(self, successful_tools: list[dict[str, Any]], user_query: str) -> str:
        tool_names = {str(item.get("tool_name") or "") for item in successful_tools}
        intents = _query_intent_flags(user_query)

        if "market" in tool_names and "news" in tool_names:
            market = self._find_tool_summary(successful_tools, "market")
            news = self._find_tool_summary(successful_tools, "news")
            if market and news:
                if intents["asks_impact"]:
                    impact = self._build_impact_synthesis_paragraph(market, news)
                    if impact:
                        return impact
                themes = self._collect_news_themes(news, limit=3)
                if themes:
                    joined = "; ".join(themes)
                    return (
                        f"Các tin về {joined} có thể tác động tâm lý và kỳ vọng ngắn hạn, "
                        "cần đối chiếu thêm với giá/KL và báo cáo chính thức."
                    )
            return (
                "Nên đọc giá/KL cùng tin tức: số liệu thị trường phản ánh trạng thái hiện tại, "
                "tin giúp giải thích biến động gần đây."
            )

        if "financial_reports" in tool_names and "market" in tool_names:
            return (
                "Số liệu BCTC và giá thị trường cần được đọc cùng nhau để tránh suy luận một chiều từ một phiên giao dịch."
            )

        if len(tool_names) == 1:
            return ""
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
        if _is_placeholder_news_text(text) or "### " in text:
            return ""

        return FinalSynthesizer._truncate_text(text, 280)

    @staticmethod
    def _news_overview_from_articles(news_summary: dict[str, Any]) -> str:
        articles = news_summary.get("structured_articles")
        if not isinstance(articles, list) or not articles:
            return ""

        themes = FinalSynthesizer._collect_news_themes(news_summary, limit=3)
        if not themes:
            return ""
        return (
            f"Tin nổi bật gần đây gồm: {', '.join(themes)}. "
            "Chi tiết từng bài và link ở mục Tin tức liên quan."
        )

    @staticmethod
    def _collect_news_themes(news_summary: dict[str, Any], *, limit: int = 3) -> list[str]:
        articles = news_summary.get("structured_articles")
        if not isinstance(articles, list):
            return []

        themes: list[str] = []
        for item in articles:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title or title in themes:
                continue
            themes.append(FinalSynthesizer._truncate_text(title, 80))
            if len(themes) >= limit:
                break
        return themes

    def _build_impact_summary_line(
        self,
        user_query: str,
        market: dict[str, Any],
        news: dict[str, Any],
    ) -> str:
        market_part = self._short_market_reference(market) or self._humanize_tool_summary(
            "market",
            str(market.get("summary") or ""),
        )
        themes = self._collect_news_themes(news, limit=2)
        news_part = f"tin về {', '.join(themes)}" if themes else "các tin mới đã thu thập"
        return (
            f"{market_part} Về mặt tin, {news_part} là điểm đáng theo dõi; "
            "tác động lên cổ phiếu cần xem thêm ở mục Góc nhìn tổng hợp."
        ).strip()

    def _build_impact_synthesis_paragraph(self, market: dict[str, Any], news: dict[str, Any]) -> str:
        themes = self._collect_news_themes(news, limit=4)
        if not themes:
            return ""

        theme_text = "; ".join(themes)
        market_hint = self._short_market_reference(market)
        lead = f"{market_hint} " if market_hint else ""
        return (
            f"{lead}Theo các tin đã có, các chủ đề như {theme_text} có thể ảnh hưởng tâm lý nhà đầu tư "
            "và kỳ vọng lợi nhuận/cổ tức ngắn hạn. Đây là nhận định tham khảo từ tin tức công khai, "
            "không thay thế phân tích định giá hay khuyến nghị giao dịch."
        ).strip()

    @staticmethod
    def _short_market_reference(market: dict[str, Any]) -> str:
        text = FinalSynthesizer._humanize_tool_summary("market", str(market.get("summary") or ""))
        if not text:
            return ""
        return FinalSynthesizer._truncate_text(text, 160)

    @staticmethod
    def _format_market_bullet(text: str) -> str:
        if not text:
            return ""

        def _fmt_number(match: re.Match[str]) -> str:
            raw = match.group(0)
            if "." in raw and len(raw.split(".")[-1]) == 3:
                return raw
            try:
                value = int(raw)
            except ValueError:
                return raw
            if value >= 1000:
                return f"{value:,}".replace(",", ".")
            return raw

        formatted = re.sub(r"\b\d{5,}\b", _fmt_number, text)
        formatted = re.sub(r"\b(\d{1,3}(?:\.\d{3})+)(?!\d)", lambda m: m.group(1), formatted)
        return formatted

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
