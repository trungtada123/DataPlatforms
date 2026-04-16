"""Summarizer cho news tool với provider có thể thay thế."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from ..gemini_pool import GeminiKeyPool
from ..groq_pool import GroqKeyPool
from .config import NewsToolSettings, get_news_tool_settings
from .schemas import NewsCrawledArticle


ARTICLE_PROMPT_TEMPLATE = """
Bạn là trợ lý tổng hợp tin tức chứng khoán Việt Nam.

Hãy tóm tắt bài viết sau trong 3-4 câu tiếng Việt ngắn gọn, chỉ dựa trên nội dung cung cấp.
- Nêu điểm chính liên quan đến doanh nghiệp/cổ phiếu.
- Không suy diễn ngoài dữ liệu.
- Nếu nội dung quá ngắn, hãy nói rõ ràng bài viết chỉ cung cấp tín hiệu hạn chế.

Tiêu đề: {title}
Nguồn: {site}
URL: {url}
Nội dung:
{content}
"""


FINAL_PROMPT_TEMPLATE = """
Bạn là trợ lý tổng hợp tin tức chứng khoán Việt Nam.

Hãy tổng hợp câu trả lời cho câu hỏi sau chỉ dựa trên các bài báo được cung cấp.
- Trả lời bằng tiếng Việt.
- Nêu 2-4 ý chính đáng chú ý nhất.
- Có nhắc nguồn theo dạng [Nguồn].
- Nếu các bài viết không đủ chắc chắn, hãy nói rõ hạn chế.
- Mỗi ý phải nằm trên một dòng riêng.
- Dùng đúng format:
  Tóm tắt:
  1. ...
  2. ...
  3. ...
  Hạn chế:
  - ...
- Không gộp tất cả ý vào một đoạn văn dài duy nhất.

Câu hỏi: {question}

Các bài viết:
{article_summaries}
"""

QUERY_COMPANY_PATTERN = re.compile(r"(?:của|cua|về|ve)\s+([^?.,]+)", flags=re.IGNORECASE)
QUERY_TICKER_PATTERN = re.compile(r"\b([A-Z]{3,5})\b")
QUERY_STOPWORDS = {
    "tin",
    "news",
    "gia",
    "gia ca",
    "co",
    "co phieu",
    "phieu",
    "gan",
    "day",
    "moi",
    "nhat",
    "hom",
    "nay",
    "la",
    "gi",
    "dang",
    "chu",
    "y",
    "noteworthy",
    "recent",
    "latest",
    "current",
    "price",
    "what",
    "about",
}


class NewsSummarizer:
    """Tóm tắt từng bài và tổng hợp cuối cho news tool."""

    def __init__(self, settings: NewsToolSettings | None = None) -> None:
        self.settings = settings or get_news_tool_settings()
        self._provider_name = self.settings.summary_provider
        self._pool = self._build_pool()

    def summarize_articles(self, question: str, articles: list[NewsCrawledArticle]) -> list[dict[str, Any]]:
        """Tóm tắt từng bài báo và trả về payload grounded theo source."""

        summaries: list[dict[str, Any]] = []
        for article in articles:
            summary = self._summarize_one(question, article)
            summaries.append(
                {
                    "article_id": article.article_id,
                    "title": article.title,
                    "site": article.site,
                    "url": article.url,
                    "summary": summary,
                    "status": article.status,
                }
            )
        return summaries

    def synthesize(self, question: str, article_summaries: list[dict[str, Any]]) -> str:
        """Tổng hợp câu trả lời cuối cho news-only query."""

        if not article_summaries:
            return "Chưa tìm thấy bài viết phù hợp để tổng hợp tin tức."

        selected_summaries = self.select_relevant_summaries(question, article_summaries)
        grounded_summary = self._grounded_synthesis(selected_summaries)
        if self._pool is None:
            return self._append_source_links(grounded_summary, selected_summaries)

        prompt = FINAL_PROMPT_TEMPLATE.format(
            question=question,
            article_summaries=json.dumps(selected_summaries, ensure_ascii=False, indent=2),
        )
        try:
            output = self._generate_with_retry(prompt)
            cleaned = self._format_final_summary(
                self._clean_model_text(output, preserve_lines=True)
            )
            if cleaned and self._looks_informative(cleaned):
                return self._append_source_links(cleaned, selected_summaries)
        except Exception:
            pass
        return self._append_source_links(grounded_summary, selected_summaries)

    def select_relevant_summaries(self, question: str, article_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Lọc các bài thực sự liên quan trước khi tổng hợp câu trả lời cuối.

        Args:
            question: Câu hỏi news gốc của người dùng.
            article_summaries: Danh sách tóm tắt từng bài đã tạo xong.

        Returns:
            Danh sách bài liên quan nhất để dùng cho bước synthesis.
        """

        if not article_summaries:
            return []

        entity_tokens = self._extract_entity_tokens(question)
        if not entity_tokens:
            return article_summaries

        scored_items: list[tuple[int, dict[str, Any]]] = []
        for item in article_summaries:
            score = self._score_relevance(item, entity_tokens)
            if score > 0:
                scored_items.append((score, item))

        if not scored_items:
            return []

        scored_items.sort(key=lambda value: value[0], reverse=True)
        return [item for _, item in scored_items]

    def _summarize_one(self, question: str, article: NewsCrawledArticle) -> str:
        content = article.cleaned_text or article.snippet or article.title
        if not content:
            return f"[{article.site}] Không đủ nội dung để tóm tắt bài viết này."
        if self._pool is None:
            return self._fallback_article_summary(article)

        prompt = ARTICLE_PROMPT_TEMPLATE.format(
            title=article.title,
            site=article.site,
            url=article.url,
            content=content,
        )
        try:
            output = self._generate_with_retry(prompt)
            cleaned = self._clean_model_text(output)
            if cleaned:
                return cleaned
        except Exception:
            pass
        return self._fallback_article_summary(article)

    def _generate_with_retry(self, prompt: str) -> str:
        if self._pool is None:
            raise RuntimeError("No model provider is configured for news summarizer.")
        return self._pool.generate_text(prompt)

    def _build_pool(self) -> GeminiKeyPool | GroqKeyPool | None:
        """Chọn provider summary theo env nhưng vẫn có fallback an toàn."""

        if self._provider_name == "fallback":
            return None

        if self._provider_name == "groq":
            groq_pool = GroqKeyPool(self.settings)
            if groq_pool.has_keys():
                return groq_pool
            gemini_pool = GeminiKeyPool(
                self.settings,
                generation_config={"temperature": 0.2},
            )
            return gemini_pool if gemini_pool.has_keys() else None

        gemini_pool = GeminiKeyPool(
            self.settings,
            generation_config={"temperature": 0.2},
        )
        if gemini_pool.has_keys():
            return gemini_pool
        groq_pool = GroqKeyPool(self.settings)
        return groq_pool if groq_pool.has_keys() else None

    @staticmethod
    def _normalize_free_text(text: str) -> str:
        lowered = text.lower().replace("đ", "d")
        normalized = unicodedata.normalize("NFD", lowered)
        return "".join(char for char in normalized if unicodedata.category(char) != "Mn")

    def _extract_entity_tokens(self, question: str) -> list[str]:
        tokens: list[str] = []

        for match in QUERY_TICKER_PATTERN.findall(question.upper()):
            normalized_match = match.lower()
            if normalized_match not in QUERY_STOPWORDS:
                tokens.append(normalized_match)

        company_match = QUERY_COMPANY_PATTERN.search(question)
        if company_match:
            entity_text = company_match.group(1)
            entity_text = re.split(r"\b(?:la gi|co gi|có gì|ra sao|bao nhieu)\b", entity_text, maxsplit=1)[0]
            normalized_entity = self._normalize_free_text(entity_text)
            normalized_entity = re.sub(r"\s+", " ", normalized_entity).strip(" ?")
            if normalized_entity:
                tokens.append(normalized_entity)
                for part in normalized_entity.split():
                    if len(part) >= 3 and part not in QUERY_STOPWORDS:
                        tokens.append(part)

        deduped_tokens: list[str] = []
        for token in tokens:
            if token and token not in deduped_tokens:
                deduped_tokens.append(token)
        return deduped_tokens

    def _score_relevance(self, article_summary: dict[str, Any], entity_tokens: list[str]) -> int:
        title_text = self._normalize_free_text(str(article_summary.get("title") or ""))
        summary_text = self._normalize_free_text(str(article_summary.get("summary") or ""))
        url_text = self._normalize_free_text(str(article_summary.get("url") or ""))

        score = 0
        for token in entity_tokens:
            if " " in token:
                if token in title_text:
                    score += 6
                if token in summary_text:
                    score += 4
                if token in url_text:
                    score += 3
                continue

            pattern = rf"\b{re.escape(token)}\b"
            if re.search(pattern, title_text):
                score += 5
            if re.search(pattern, summary_text):
                score += 3
            if re.search(pattern, url_text):
                score += 2
        return score

    @staticmethod
    def _clean_model_text(value: str, *, preserve_lines: bool = False) -> str:
        if preserve_lines:
            lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
            cleaned = "\n".join(line for line in lines if line).strip()
            return cleaned
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned

    @staticmethod
    def _format_final_summary(value: str) -> str:
        """Ép phần summary cuối xuống dòng rõ ràng theo từng ý."""

        if not value:
            return value

        formatted = value.strip()
        formatted = re.sub(r"(?<!\n)\s+(?=\d+\.\s+)", "\n", formatted)
        formatted = re.sub(r"(?<!\n)\s+(?=Hạn chế:)", "\n\n", formatted)
        formatted = re.sub(r"(?<!\n)\s+(?=\*\*Hạn chế:)", "\n\n", formatted)
        formatted = re.sub(r"\n{3,}", "\n\n", formatted)
        return formatted.strip()

    @staticmethod
    def _fallback_article_summary(article: NewsCrawledArticle) -> str:
        basis = article.cleaned_excerpt or article.snippet or "Bài viết không có đủ nội dung để trích yếu."
        return f"[{article.site}] {article.title}: {basis}"

    @staticmethod
    def _fallback_synthesis(article_summaries: list[dict[str, Any]]) -> str:
        top_items = article_summaries[:3]
        snippets = []
        for item in top_items:
            snippets.append(f"[{item['site']}] {item['summary']}")
        return " ".join(snippets)

    def _grounded_synthesis(self, article_summaries: list[dict[str, Any]]) -> str:
        if not article_summaries:
            return "Chưa tìm thấy bài viết phù hợp để tổng hợp tin tức."

        bullet_lines: list[str] = []
        limited_count = 0
        for item in article_summaries[:3]:
            site = str(item.get("site") or "unknown")
            title = str(item.get("title") or "Bài viết không có tiêu đề").strip()
            summary = self._clean_model_text(str(item.get("summary") or ""), preserve_lines=False)
            if self._is_limited_summary(summary):
                limited_count += 1
            bullet_lines.append(f"- [{site}] {title}: {summary}")

        limitation_line = ""
        if limited_count:
            limitation_line = (
                f"\n\nHạn chế: {limited_count}/{len(article_summaries[:3])} bài chỉ cung cấp tín hiệu hạn chế,"
                " nên phần tổng hợp cuối có thể chưa đủ chiều sâu."
            )

        return "Các ý đáng chú ý từ các bài đã chọn:\n" + "\n".join(bullet_lines) + limitation_line

    @staticmethod
    def _append_source_links(summary: str, article_summaries: list[dict[str, Any]]) -> str:
        """Gắn thêm danh sách link nguồn để người dùng kiểm tra nhanh từng bài báo."""

        source_lines: list[str] = []
        seen_urls: set[str] = set()

        for item in article_summaries[:5]:
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            site = str(item.get("site") or "unknown").strip()
            title = str(item.get("title") or url).strip()
            source_lines.append(f"- {site}: {title} -> {url}")

        if not source_lines:
            return summary

        return f"{summary}\n\nNguồn tham khảo:\n" + "\n".join(source_lines)

    @staticmethod
    def _is_limited_summary(summary: str) -> bool:
        lowered = summary.lower()
        limited_markers = (
            "tín hiệu hạn chế",
            "không có nội dung chi tiết",
            "chỉ cung cấp tiêu đề",
            "rất hạn chế",
            "không thể tóm tắt",
        )
        return any(marker in lowered for marker in limited_markers)

    @staticmethod
    def _looks_informative(summary: str) -> bool:
        lowered = summary.lower()
        bad_markers = (
            "không thể đưa ra 2-4 ý",
            "do chỉ có một bài viết",
            "không thể đưa ra",
        )
        if any(marker in lowered for marker in bad_markers):
            return False
        return len(summary) >= 120
