"""Summarizer cho news tool với provider có thể thay thế."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from ..gemini_pool import GeminiKeyPool
from ..groq_pool import GroqKeyPool
from .config import NewsToolSettings, get_news_tool_settings
from .schemas import NewsCrawledArticle
from .storage import canonicalize_url


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
FINANCIAL_NEWS_DOMAINS = {
    "cafef.vn",
    "vietstock.vn",
    "ndh.vn",
    "tinnhanhchungkhoan.vn",
    "fireant.vn",
    "dnse.com.vn",
    "vneconomy.vn",
    "vietnamfinance.vn",
    "stockbiz.vn",
    "cophieu68.vn",
}
STOCK_CONTEXT_TERMS = (
    "co phieu",
    "chung khoan",
    "doanh nghiep",
    "cong ty",
    "tai chinh",
    "loi nhuan",
    "doanh thu",
    "ket qua kinh doanh",
    "bao cao tai chinh",
    "securities",
    "stock",
    "shares",
    "profit",
    "revenue",
)
ENTERTAINMENT_NOISE_TERMS = (
    "fpt play",
    "play",
    "giai tri",
    "phim",
    "am nhac",
    "showbiz",
    "truyen hinh",
    "gameshow",
    "anime",
    "dien anh",
)
NEGATIVE_QUERY_TERMS = (
    "tiêu cực",
    "tieu cuc",
    "xấu",
    "xau",
    "rủi ro",
    "rui ro",
    "giảm",
    "giam",
    "lỗ",
    "lo",
    "kiện",
    "kien",
    "bị phạt",
    "bi phat",
    "cảnh báo",
    "canh bao",
    "khó khăn",
    "kho khan",
    "sa thải",
    "sa thai",
    "nợ",
    "no",
    "tranh chấp",
    "tranh chap",
)
NEGATIVE_SIGNAL_TERMS = (
    "lỗ",
    "thua lỗ",
    "thua lo",
    "lỗ ròng",
    "lo rong",
    "suy giảm",
    "suy giam",
    "giảm",
    "giam",
    "bị phạt",
    "bi phat",
    "khởi tố",
    "khoi to",
    "điều tra",
    "dieu tra",
    "tranh chấp",
    "tranh chap",
    "sa thải",
    "sa thai",
    "nợ xấu",
    "no xau",
    "downgrade",
    "cảnh báo",
    "canh bao",
)
LATEST_QUERY_TERMS = (
    "mới nhất",
    "moi nhat",
    "gần đây",
    "gan day",
    "hôm nay",
    "hom nay",
    "tuần này",
    "tuan nay",
    "recent",
    "latest",
    "today",
    "this week",
)
TOP_SELECTION_LIMIT = 5
TITLE_NEAR_DUP_THRESHOLD = 0.84
TOPIC_OVERLAP_THRESHOLD = 0.86
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
YMD_PATH_PATTERN = re.compile(r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:/|$)")
DMY_TEXT_PATTERN = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b")
YYMMDD_6_PATTERN = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")
YYYYMMDD_8_PATTERN = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")


@dataclass(slots=True)
class QueryIntent:
    negative_news: bool
    latest_news: bool
    stock_or_company_news: bool
    entity_tokens: list[str]


@dataclass(slots=True)
class ArticleCandidate:
    article_id: str | None
    url: str
    canonical_url: str
    title: str
    snippet: str
    source_domain: str
    published_at: str | None
    crawled_text: str
    summary: str
    status: str
    parsed_published_at: datetime | None
    relevance_score: float
    recency_score: float
    negative_signal_score: float
    source_quality_score: float
    query_alignment_score: float
    final_score: float
    duplicate_key: str
    reason_selected: str | None = None
    reason_rejected: str | None = None


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
                    "canonical_url": canonicalize_url(article.url),
                    "snippet": article.snippet,
                    "published_at": article.published_at,
                    "cleaned_text": article.cleaned_text or "",
                    "summary": summary,
                    "status": article.status,
                    "metadata": article.metadata or {},
                }
            )
        return summaries

    def synthesize(self, question: str, article_summaries: list[dict[str, Any]]) -> str:
        """Tổng hợp câu trả lời cuối cho news-only query."""

        if not article_summaries:
            return "Chưa tìm thấy bài viết phù hợp để tổng hợp tin tức."

        intent = self._detect_intent(question)
        selected_summaries = self.select_relevant_summaries(question, article_summaries)
        if intent.negative_news and not selected_summaries:
            return (
                "Không tìm thấy đủ tin tiêu cực rõ ràng trong các bài mới crawl được.\n"
                "Dưới đây là các bài gần nhất và liên quan nhất để tham khảo:\n"
                "Chưa có bài nào đáp ứng tiêu chí lọc hiện tại."
            )
        no_clear_negative = any(
            "Không tìm thấy đủ tin tiêu cực rõ ràng" in str(item.get("reason_selected") or "")
            for item in selected_summaries
        )
        grounded_summary = self._grounded_synthesis(selected_summaries)
        if self._pool is None:
            if no_clear_negative and "Không tìm thấy đủ tin tiêu cực rõ ràng" not in grounded_summary:
                grounded_summary = (
                    "Không tìm thấy đủ tin tiêu cực rõ ràng trong các bài mới crawl được.\n"
                    + grounded_summary
                )
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
                if no_clear_negative and "Không tìm thấy đủ tin tiêu cực rõ ràng" not in cleaned:
                    cleaned = (
                        "Không tìm thấy đủ tin tiêu cực rõ ràng trong các bài mới crawl được.\n\n"
                        + cleaned
                    )
                return self._append_source_links(cleaned, selected_summaries)
        except Exception:
            pass
        if no_clear_negative and "Không tìm thấy đủ tin tiêu cực rõ ràng" not in grounded_summary:
            grounded_summary = (
                "Không tìm thấy đủ tin tiêu cực rõ ràng trong các bài mới crawl được.\n"
                + grounded_summary
            )
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

        intent = self._detect_intent(question)
        candidates = self._build_candidates(question, article_summaries, intent)
        if not candidates:
            return []

        selected_candidates, rejected_candidates = self._select_top_candidates(candidates, intent)
        if not selected_candidates:
            return []

        if intent.negative_news and not any(c.negative_signal_score > 0 for c in selected_candidates):
            fallback_note = "Không tìm thấy đủ tin tiêu cực rõ ràng trong các bài mới crawl được."
            for candidate in selected_candidates:
                candidate.reason_selected = self._append_reason(candidate.reason_selected, "fallback_no_clear_negative")
            selected_candidates[0].reason_selected = self._append_reason(
                selected_candidates[0].reason_selected, fallback_note
            )

        selected_payloads: list[dict[str, Any]] = []
        for candidate in selected_candidates:
            selected_payloads.append(
                {
                    "article_id": candidate.article_id,
                    "title": candidate.title,
                    "site": candidate.source_domain,
                    "url": candidate.url,
                    "canonical_url": candidate.canonical_url,
                    "snippet": candidate.snippet,
                    "published_at": candidate.published_at,
                    "summary": candidate.summary,
                    "status": candidate.status,
                    "relevance_score": round(candidate.relevance_score, 3),
                    "recency_score": round(candidate.recency_score, 3),
                    "final_score": round(candidate.final_score, 3),
                    "duplicate_key": candidate.duplicate_key,
                    "reason_selected": candidate.reason_selected,
                    "metadata": {
                        "negative_signal_score": round(candidate.negative_signal_score, 3),
                        "source_quality_score": round(candidate.source_quality_score, 3),
                        "query_alignment_score": round(candidate.query_alignment_score, 3),
                    },
                }
            )

        if rejected_candidates:
            rejected_meta = [
                {
                    "url": c.url,
                    "canonical_url": c.canonical_url,
                    "title": c.title,
                    "reason_rejected": c.reason_rejected,
                    "final_score": round(c.final_score, 3),
                }
                for c in rejected_candidates[:10]
            ]
            selected_payloads[0].setdefault("metadata", {})
            selected_payloads[0]["metadata"]["rejected_candidates"] = rejected_meta

        return selected_payloads

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

    def _detect_intent(self, question: str) -> QueryIntent:
        normalized = self._normalize_free_text(question)
        entity_tokens = self._extract_entity_tokens(question)

        negative_news = any(term in normalized for term in NEGATIVE_QUERY_TERMS)
        latest_news = any(term in normalized for term in LATEST_QUERY_TERMS)
        stock_or_company_news = bool(entity_tokens) and any(
            keyword in normalized
            for keyword in (
                "co phieu",
                "chung khoan",
                "doanh nghiep",
                "cong ty",
                "ket qua kinh doanh",
                "tai chinh",
                "stock",
                "shares",
                "business",
                "company",
            )
        )

        if not stock_or_company_news:
            stock_or_company_news = bool(entity_tokens)

        return QueryIntent(
            negative_news=negative_news,
            latest_news=latest_news,
            stock_or_company_news=stock_or_company_news,
            entity_tokens=entity_tokens,
        )

    def _build_candidates(
        self,
        question: str,
        article_summaries: list[dict[str, Any]],
        intent: QueryIntent,
    ) -> list[ArticleCandidate]:
        candidates: list[ArticleCandidate] = []
        for item in article_summaries:
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue

            snippet = str(item.get("snippet") or "")
            cleaned_text = str(item.get("cleaned_text") or "")
            summary = str(item.get("summary") or "")
            source_domain = str(item.get("site") or self._infer_domain(url)).lower()
            canonical_url = str(item.get("canonical_url") or canonicalize_url(url))
            published_at = self._extract_best_published_at(item)
            parsed_dt = self._parse_datetime_value(published_at) or self._infer_datetime_from_url_or_text(
                url=url,
                title=title,
                snippet=snippet,
                cleaned_text=cleaned_text,
            )

            relevance_score = float(self._score_relevance(item, intent.entity_tokens) if intent.entity_tokens else 1.0)
            recency_score = self._score_recency(parsed_dt, intent.latest_news)
            negative_signal_score = self._score_negative_signal(
                title=title,
                snippet=snippet,
                summary=summary,
                cleaned_text=cleaned_text,
                negative_query=intent.negative_news,
            )
            source_quality_score = self._score_source_quality(
                domain=source_domain,
                title=title,
                snippet=snippet,
                summary=summary,
                cleaned_text=cleaned_text,
                stock_or_company_query=intent.stock_or_company_news,
                negative_query=intent.negative_news,
            )
            query_alignment_score = self._score_query_alignment(
                title=title,
                snippet=snippet,
                summary=summary,
                cleaned_text=cleaned_text,
                intent=intent,
            )
            final_score = (
                relevance_score * 1.7
                + recency_score * 2.2
                + negative_signal_score * (2.4 if intent.negative_news else 0.5)
                + source_quality_score
                + query_alignment_score * 1.4
            )

            duplicate_key = self._build_duplicate_key(title=title, url=canonical_url)
            candidate = ArticleCandidate(
                article_id=item.get("article_id"),
                url=url,
                canonical_url=canonical_url,
                title=title,
                snippet=snippet,
                source_domain=source_domain,
                published_at=published_at,
                crawled_text=cleaned_text,
                summary=summary,
                status=str(item.get("status") or ""),
                parsed_published_at=parsed_dt,
                relevance_score=relevance_score,
                recency_score=recency_score,
                negative_signal_score=negative_signal_score,
                source_quality_score=source_quality_score,
                query_alignment_score=query_alignment_score,
                final_score=final_score,
                duplicate_key=duplicate_key,
            )
            candidates.append(candidate)

        candidates.sort(
            key=lambda c: (
                -c.final_score,
                -(c.parsed_published_at.timestamp() if c.parsed_published_at else 0),
                c.canonical_url,
            )
        )
        return candidates

    def _select_top_candidates(
        self,
        candidates: list[ArticleCandidate],
        intent: QueryIntent,
    ) -> tuple[list[ArticleCandidate], list[ArticleCandidate]]:
        selected: list[ArticleCandidate] = []
        rejected: list[ArticleCandidate] = []
        selected_urls: set[str] = set()
        selected_title_norms: list[str] = []
        selected_topic_signatures: list[set[str]] = []

        for candidate in candidates:
            if len(selected) >= TOP_SELECTION_LIMIT:
                candidate.reason_rejected = "over_top_limit"
                rejected.append(candidate)
                continue

            if candidate.relevance_score <= 0:
                candidate.reason_rejected = "relevance_score<=0"
                rejected.append(candidate)
                continue

            if candidate.canonical_url in selected_urls:
                candidate.reason_rejected = "duplicate_canonical_url"
                rejected.append(candidate)
                continue

            normalized_title = self._normalize_title_for_duplicate(candidate.title)
            duplicate_title = any(
                SequenceMatcher(None, normalized_title, existing).ratio() >= TITLE_NEAR_DUP_THRESHOLD
                for existing in selected_title_norms
            )
            if duplicate_title:
                candidate.reason_rejected = "near_duplicate_title"
                rejected.append(candidate)
                continue

            topic_signature = self._topic_signature(candidate.title, candidate.summary, candidate.snippet)
            if topic_signature:
                duplicate_topic = any(
                    self._token_overlap_ratio(topic_signature, existing_signature) >= TOPIC_OVERLAP_THRESHOLD
                    for existing_signature in selected_topic_signatures
                )
                if duplicate_topic:
                    candidate.reason_rejected = "near_duplicate_topic"
                    rejected.append(candidate)
                    continue

            if intent.latest_news and candidate.recency_score <= -2.0 and len(selected) < 3:
                candidate.reason_rejected = "too_old_for_latest_query"
                rejected.append(candidate)
                continue

            if self._should_reject_low_signal_negative_candidate(
                candidate=candidate,
                intent=intent,
                selected=selected,
            ):
                candidate.reason_rejected = "low_negative_signal_for_negative_query"
                rejected.append(candidate)
                continue

            reason_parts = [
                f"score={candidate.final_score:.2f}",
                f"relevance={candidate.relevance_score:.2f}",
                f"recency={candidate.recency_score:.2f}",
            ]
            if intent.negative_news:
                reason_parts.append(f"negative={candidate.negative_signal_score:.2f}")
            if intent.stock_or_company_news:
                reason_parts.append(f"alignment={candidate.query_alignment_score:.2f}")
            candidate.reason_selected = "; ".join(reason_parts)

            selected.append(candidate)
            selected_urls.add(candidate.canonical_url)
            selected_title_norms.append(normalized_title)
            selected_topic_signatures.append(topic_signature)

        selected.sort(
            key=lambda c: (
                -c.final_score,
                -(c.parsed_published_at.timestamp() if c.parsed_published_at else 0),
            )
        )
        return selected, rejected

    def _extract_best_published_at(self, payload: dict[str, Any]) -> str | None:
        direct_value = payload.get("published_at")
        if isinstance(direct_value, str) and direct_value.strip():
            return direct_value.strip()

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            nested_meta = metadata.get("metadata")
            if isinstance(nested_meta, dict):
                for key in ("publishedTime", "publishTime", "datePublished", "pubDate", "date"):
                    value = nested_meta.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            for key in ("published_at", "publishedTime", "publishTime", "datePublished"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def _parse_datetime_value(self, raw_value: str | None) -> datetime | None:
        if not raw_value:
            return None
        raw_text = raw_value.strip()
        if not raw_text:
            return None

        normalized = self._normalize_free_text(raw_text)

        # Relative English markers from DDG.
        minute_match = re.search(r"(\d+)\s+minutes?\s+ago", normalized)
        if minute_match:
            return datetime.now(self.settings.tzinfo) - timedelta(minutes=int(minute_match.group(1)))

        hour_match = re.search(r"(\d+)\s+hours?\s+ago", normalized)
        if hour_match:
            return datetime.now(self.settings.tzinfo) - timedelta(hours=int(hour_match.group(1)))

        day_match = re.search(r"(\d+)\s+days?\s+ago", normalized)
        if day_match:
            return datetime.now(self.settings.tzinfo) - timedelta(days=int(day_match.group(1)))

        if "today" in normalized or "hom nay" in normalized:
            return datetime.now(self.settings.tzinfo)

        for parser in (
            self._parse_iso_datetime,
            self._parse_dmy_datetime,
            self._parse_ymd_datetime,
        ):
            parsed = parser(raw_text)
            if parsed is not None:
                return parsed
        return None

    def _parse_iso_datetime(self, value: str) -> datetime | None:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=self.settings.tzinfo)
        return parsed.astimezone(self.settings.tzinfo)

    def _parse_dmy_datetime(self, value: str) -> datetime | None:
        match = DMY_TEXT_PATTERN.search(value)
        if not match:
            return None
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return datetime(year, month, day, tzinfo=self.settings.tzinfo)
        except ValueError:
            return None

    def _parse_ymd_datetime(self, value: str) -> datetime | None:
        match = YMD_PATH_PATTERN.search(value)
        if not match:
            return None
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return datetime(year, month, day, tzinfo=self.settings.tzinfo)
        except ValueError:
            return None

    def _infer_datetime_from_url_or_text(
        self,
        *,
        url: str,
        title: str,
        snippet: str,
        cleaned_text: str,
    ) -> datetime | None:
        url_date = self._parse_ymd_datetime(url)
        if url_date is not None:
            return url_date

        for yyMMdd_match in YYMMDD_6_PATTERN.finditer(url):
            yy = int(yyMMdd_match.group(1))
            month = int(yyMMdd_match.group(2))
            day = int(yyMMdd_match.group(3))
            year = 2000 + yy
            try:
                return datetime(year, month, day, tzinfo=self.settings.tzinfo)
            except ValueError:
                continue

        for yyyymmdd_match in YYYYMMDD_8_PATTERN.finditer(url):
            year = int(yyyymmdd_match.group(1))
            month = int(yyyymmdd_match.group(2))
            day = int(yyyymmdd_match.group(3))
            try:
                return datetime(year, month, day, tzinfo=self.settings.tzinfo)
            except ValueError:
                continue

        for text in (title, snippet, cleaned_text):
            parsed = self._parse_dmy_datetime(text)
            if parsed is not None:
                return parsed
            parsed = self._parse_ymd_datetime(text)
            if parsed is not None:
                return parsed

        return None

    def _score_recency(self, published_at: datetime | None, latest_query: bool) -> float:
        if published_at is None:
            return -1.2 if latest_query else -0.4

        now = datetime.now(self.settings.tzinfo)
        age_days = max((now - published_at).total_seconds() / 86400.0, 0.0)
        if age_days <= 1:
            return 3.0
        if age_days <= 3:
            return 2.4
        if age_days <= 7:
            return 1.9
        if age_days <= 30:
            return 1.1
        if age_days <= 90:
            return -0.5 if latest_query else 0.2
        if age_days <= 365:
            return -2.2 if latest_query else -0.8
        return -3.0 if latest_query else -1.2

    def _score_negative_signal(
        self,
        *,
        title: str,
        snippet: str,
        summary: str,
        cleaned_text: str,
        negative_query: bool,
    ) -> float:
        haystack = self._normalize_free_text(" ".join([title, snippet, summary, cleaned_text]))
        signal_hits = 0
        strong_hits = 0
        for term in NEGATIVE_SIGNAL_TERMS:
            if term in haystack:
                signal_hits += 1
                if term in {"lỗ", "thua lỗ", "lo rong", "bị phạt", "bi phat", "khởi tố", "khoi to", "điều tra", "dieu tra"}:
                    strong_hits += 1

        base = float(signal_hits) * 0.8 + float(strong_hits) * 0.6
        if negative_query and base == 0:
            return -1.3
        if negative_query:
            return base + 0.6
        return min(base, 0.8)

    def _score_source_quality(
        self,
        *,
        domain: str,
        title: str,
        snippet: str,
        summary: str,
        cleaned_text: str,
        stock_or_company_query: bool,
        negative_query: bool,
    ) -> float:
        score = 0.0
        if domain in FINANCIAL_NEWS_DOMAINS:
            score += 1.6 if stock_or_company_query else 0.6

        haystack = self._normalize_free_text(" ".join([title, snippet, summary, cleaned_text]))
        entertainment_noise_hits = sum(1 for keyword in ENTERTAINMENT_NOISE_TERMS if keyword in haystack)
        if stock_or_company_query:
            if any(keyword in haystack for keyword in STOCK_CONTEXT_TERMS):
                score += 0.9
            if entertainment_noise_hits:
                score -= 1.3 + min(1.1, 0.35 * entertainment_noise_hits)
                if negative_query:
                    score -= 0.7
        return score

    def _score_query_alignment(
        self,
        *,
        title: str,
        snippet: str,
        summary: str,
        cleaned_text: str,
        intent: QueryIntent,
    ) -> float:
        haystack = self._normalize_free_text(" ".join([title, snippet, summary, cleaned_text]))
        score = 0.0

        stock_context_hits = sum(1 for keyword in STOCK_CONTEXT_TERMS if keyword in haystack)
        if stock_context_hits:
            score += min(2.0, 0.45 * stock_context_hits)
        elif intent.stock_or_company_news:
            score -= 0.5

        entertainment_noise_hits = sum(1 for keyword in ENTERTAINMENT_NOISE_TERMS if keyword in haystack)
        if entertainment_noise_hits and intent.stock_or_company_news:
            score -= 1.2 + min(1.2, 0.35 * entertainment_noise_hits)
            if intent.negative_news:
                score -= 0.9

        if intent.negative_news:
            negative_hits = sum(1 for term in NEGATIVE_SIGNAL_TERMS if term in haystack)
            if negative_hits:
                score += min(1.8, 0.55 * negative_hits)
            else:
                score -= 0.8

        return score

    @staticmethod
    def _should_reject_low_signal_negative_candidate(
        *,
        candidate: ArticleCandidate,
        intent: QueryIntent,
        selected: list[ArticleCandidate],
    ) -> bool:
        if not intent.negative_news:
            return False

        if candidate.negative_signal_score > 0:
            return False

        if candidate.query_alignment_score < -0.4:
            return True

        if candidate.source_quality_score < -0.8:
            return True

        # Keep only strongest fallback articles when no negative signal exists.
        if len(selected) >= 2 and candidate.final_score < 2.0:
            return True

        return False

    @staticmethod
    def _infer_domain(url: str) -> str:
        match = re.search(r"https?://([^/]+)", url)
        if not match:
            return "unknown"
        return match.group(1).lower().replace("www.", "")

    def _normalize_title_for_duplicate(self, title: str) -> str:
        normalized = self._normalize_free_text(title)
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _topic_signature(self, title: str, summary: str, snippet: str) -> set[str]:
        normalized = self._normalize_free_text(" ".join([title, summary, snippet]))
        tokens = [token for token in re.findall(r"[a-z0-9]{3,}", normalized) if token not in QUERY_STOPWORDS]
        token_counts: dict[str, int] = {}
        for token in tokens:
            token_counts[token] = token_counts.get(token, 0) + 1

        ordered = sorted(token_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        signature = {token for token, _ in ordered[:8]}
        return signature

    @staticmethod
    def _token_overlap_ratio(first: set[str], second: set[str]) -> float:
        if not first or not second:
            return 0.0
        intersection = len(first.intersection(second))
        denominator = min(len(first), len(second))
        return intersection / max(denominator, 1)

    def _build_duplicate_key(self, *, title: str, url: str) -> str:
        normalized_title = self._normalize_title_for_duplicate(title)
        base = normalized_title[:64] if normalized_title else "untitled"
        domain = self._infer_domain(url)
        year = ""
        year_match = YEAR_PATTERN.search(url)
        if year_match:
            year = year_match.group(1)
        return f"{domain}:{base}:{year}"

    @staticmethod
    def _append_reason(existing: str | None, incoming: str) -> str:
        if not existing:
            return incoming
        if incoming in existing:
            return existing
        return f"{existing}; {incoming}"

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

        no_clear_negative = any(
            "Không tìm thấy đủ tin tiêu cực rõ ràng" in str(item.get("reason_selected") or "")
            for item in article_summaries
        )

        bullet_lines: list[str] = []
        limited_count = 0
        for item in article_summaries[:TOP_SELECTION_LIMIT]:
            site = str(item.get("site") or "unknown")
            title = str(item.get("title") or "Bài viết không có tiêu đề").strip()
            summary = self._clean_model_text(str(item.get("summary") or ""), preserve_lines=False)
            article_date = str(item.get("published_at") or "").strip()
            date_label = f" ({article_date})" if article_date else ""
            if self._is_limited_summary(summary):
                limited_count += 1
            bullet_lines.append(f"- [{site}]{date_label} {title}: {summary}")

        limitation_line = ""
        if limited_count:
            limitation_line = (
                f"\n\nHạn chế: {limited_count}/{len(article_summaries[:TOP_SELECTION_LIMIT])} bài chỉ cung cấp tín hiệu hạn chế,"
                " nên phần tổng hợp cuối có thể chưa đủ chiều sâu."
            )

        header = "Các ý đáng chú ý từ các bài đã chọn:\n"
        if no_clear_negative:
            header = (
                "Không tìm thấy đủ tin tiêu cực rõ ràng trong các bài mới crawl được.\n"
                "Dưới đây là các bài gần nhất và liên quan nhất để tham khảo:\n"
            )
        return header + "\n".join(bullet_lines) + limitation_line

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
            published_at = str(item.get("published_at") or "").strip()
            date_label = f" ({published_at})" if published_at else ""
            source_lines.append(f"- {site}{date_label}: {title} -> {url}")

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
