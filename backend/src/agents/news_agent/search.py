"""DuckDuckGo search helpers cho news tool."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from src.config.news import NewsToolSettings, get_news_tool_settings
from src.schemas.api import NewsSearchHit
from .storage import normalize_url


ARTICLE_ID_PATTERN = re.compile(r"\d{5,}(?:\.\w+)?$")
COMPANY_CLAUSE_PATTERN = re.compile(r"(?:của|cua|về|ve)\s+([^?]+)", flags=re.IGNORECASE)
ENGLISH_ENTITY_PATTERN = re.compile(r"(?:about|of|for)\s+([^?]+)", flags=re.IGNORECASE)
TICKER_PATTERN = re.compile(r"\b([A-Z]{3,5})\b")
RELATIVE_DAYS_PATTERN = re.compile(r"\b(\d+)\s+days?\s+ago\b")
SKIP_PATH_PATTERNS = (
    r"^/tag/",
    r"^/tags/",
    r"^/category/",
    r"^/chu-de/",
    r"^/$",
    r"^/tin-moi",
    r"^/tin-tuc-24h",
    r"^/search",
    r"^/video/",
    r"^/photo/",
    r"^/albums/",
    r"^/infographic/",
)
QUERY_STOPWORDS = {
    "about",
    "bao",
    "bao nhieu",
    "chung",
    "chung khoan",
    "chu",
    "co",
    "current",
    "dang",
    "day",
    "financial",
    "gan",
    "gia",
    "gi",
    "historical",
    "hom",
    "indicator",
    "latest",
    "market",
    "moi",
    "nay",
    "news",
    "noteworthy",
    "price",
    "query",
    "recent",
    "report",
    "technical",
    "what",
    "y",
}
NON_TICKER_TOKENS = {
    "ABOUT",
    "AFTER",
    "DATA",
    "FOR",
    "FROM",
    "LATEST",
    "MARKET",
    "NEWS",
    "PRICE",
    "QUERY",
    "RANGE",
    "RECENT",
    "REPORT",
    "REPORTS",
    "TECH",
    "TODAY",
    "WHAT",
    "WHEN",
    "WHICH",
    "WITH",
}


def normalize_free_text(text: str) -> str:
    """Chuẩn hoá text để match entity ổn định hơn."""

    lowered = text.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def is_article_url(url: str, site: str) -> bool:
    """Chỉ giữ URL bài viết thật, loại listing/category/tag.

    Args:
        url: URL cần đánh giá.
        site: Domain dự kiến của nguồn.

    Returns:
        `True` nếu URL trông giống một bài viết hợp lệ.
    """

    normalized = normalize_url(url)
    normalized_site = site.replace("www.", "")
    if not normalized or len(normalized) < 25:
        return False
    if normalized_site not in normalized:
        return False

    path = normalized.split(normalized_site, 1)[-1].rstrip("/")
    if len(path) < 5:
        return False

    for pattern in SKIP_PATH_PATTERNS:
        if re.match(pattern, path):
            return False

    return ARTICLE_ID_PATTERN.search(normalized) is not None


def infer_timelimit(query: str) -> str | None:
    """Suy ra timelimit của DuckDuckGo từ câu hỏi news."""

    lowered = normalize_free_text(query)
    if any(token in lowered for token in ("hom nay", "moi nhat", "latest")):
        return "d"
    if any(token in lowered for token in ("gan day", "tuan nay", "recent")):
        return "w"
    if any(token in lowered for token in ("thang nay", "trong thang")):
        return "m"
    return None


class DuckDuckGoNewsSearch:
    """Search client cho news tool bằng DDGS."""

    def __init__(self, settings: NewsToolSettings | None = None) -> None:
        self.settings = settings or get_news_tool_settings()

    def search(self, question: str, *, max_results: int | None = None) -> list[NewsSearchHit]:
        """Tìm top bài viết phù hợp cho câu hỏi news.

        Args:
            question: Query news đã chuẩn hoá.
            max_results: Giới hạn kết quả trả về nếu caller muốn override.

        Returns:
            Danh sách `NewsSearchHit` đã dedupe URL.
        """

        try:
            from ddgs import DDGS
        except ImportError as exc:  # pragma: no cover - phụ thuộc runtime ngoài.
            raise RuntimeError("ddgs is required for news search. Please install `ddgs`.") from exc

        target_count = max_results or self.settings.max_search_results
        entity_tokens = self._extract_entity_tokens(question)
        timelimit = infer_timelimit(question)
        query_candidates = self._build_query_candidates(question)

        deduped_hits: dict[str, tuple[int, NewsSearchHit]] = {}
        next_position = 1
        with DDGS() as client:
            for site in self.settings.trusted_sites:
                found_for_site = 0
                for query_candidate in query_candidates:
                    scoped_query = f"{query_candidate} site:{site}"
                    try:
                        kwargs: dict[str, Any] = {
                            "max_results": self.settings.max_results_per_site + 3,
                            "region": "vn-vi",
                            "safesearch": "off",
                        }
                        if timelimit:
                            kwargs["timelimit"] = timelimit
                        results = client.text(scoped_query, **kwargs)
                    except Exception:
                        continue

                    for item in results:
                        hit = self._build_hit(item=item, site=site, position=next_position)
                        if hit is None:
                            continue
                        next_position += 1

                        relevance_score = self._score_hit_relevance(hit, entity_tokens)
                        if relevance_score <= 0:
                            continue

                        existing = deduped_hits.get(hit.normalized_url)
                        if existing and existing[0] >= relevance_score:
                            continue

                        deduped_hits[hit.normalized_url] = (
                            relevance_score,
                            hit.model_copy(
                                update={
                                    "metadata": {
                                        **hit.metadata,
                                        "relevance_score": relevance_score,
                                    }
                                }
                            ),
                        )
                        found_for_site += 1
                        if found_for_site >= self.settings.max_results_per_site:
                            break
                        if len(deduped_hits) >= target_count:
                            return self._finalize_hits(deduped_hits, target_count)

                    if found_for_site >= self.settings.max_results_per_site:
                        break
                if len(deduped_hits) >= target_count:
                    return self._finalize_hits(deduped_hits, target_count)

        return self._finalize_hits(deduped_hits, target_count)

    @staticmethod
    def _build_query_candidates(question: str) -> list[str]:
        raw_question = " ".join(question.strip().split())
        normalized_question = normalize_free_text(raw_question)
        candidates: list[str] = []
        entity = DuckDuckGoNewsSearch._extract_entity_phrase(raw_question)
        tickers = DuckDuckGoNewsSearch._extract_ticker_tokens(entity or raw_question)
        primary_subject = (entity or (tickers[0] if tickers else "")).strip()
        has_negative_intent = any(
            token in normalized_question
            for token in (
                "negative",
                "tieu cuc",
                "xau",
                "rui ro",
                "giam",
                "lo",
                "kien",
                "bi phat",
                "canh bao",
                "kho khan",
                "sa thai",
                "no",
                "tranh chap",
            )
        )
        has_recent_intent = any(
            token in normalized_question
            for token in ("gan day", "moi nhat", "hom nay", "tuan nay", "recent", "latest", "today", "this week")
        )
        is_stock_or_company_query = bool(tickers) or any(
            token in normalized_question
            for token in (
                "co phieu",
                "chung khoan",
                "doanh nghiep",
                "cong ty",
                "tai chinh",
                "ket qua kinh doanh",
                "stock",
                "shares",
                "business",
                "company",
            )
        )

        if entity:
            candidates.append(entity)
            candidates.append(f"tin tức {entity}")
            candidates.append(f"{entity} chứng khoán")
            for ticker in tickers:
                if ticker not in entity.upper():
                    candidates.append(f"{entity} {ticker}")
                    candidates.append(f"{entity} {ticker} chứng khoán")

        for ticker in tickers:
            candidates.append(ticker)
            candidates.append(f"tin tức {ticker}")
            candidates.append(f"{ticker} chứng khoán")
            candidates.append(f"{ticker} tin tức mới nhất")

        if is_stock_or_company_query and primary_subject:
            candidates.append(f"{primary_subject} kết quả kinh doanh")
            candidates.append(f"{primary_subject} doanh nghiệp")

        if has_recent_intent and primary_subject:
            candidates.append(f"{primary_subject} tin tức gần đây")
            candidates.append(f"{primary_subject} tin tức mới nhất")

        if has_negative_intent and primary_subject:
            candidates.append(f"{primary_subject} tin tiêu cực gần đây")
            candidates.append(f"{primary_subject} rủi ro cổ phiếu")
            candidates.append(f"{primary_subject} bị phạt")
            candidates.append(f"{primary_subject} khó khăn")
            candidates.append(f"{primary_subject} tin tức mới nhất")
            candidates.append(f"{primary_subject} tin tiêu cực gần đây OR rủi ro OR bị phạt OR khó khăn")

        candidates.append(raw_question)

        cleaned = raw_question
        for token in (
            "Tin mới nhất",
            "Tin gần đây",
            "Tin tức mới nhất",
            "Tin tức gần đây",
            "hôm nay",
            "Hôm nay",
            "mới nhất",
            "gần đây",
            "là gì",
            "có gì đáng chú ý",
            "ra sao",
        ):
            cleaned = cleaned.replace(token, " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?")
        if cleaned:
            candidates.append(cleaned)

        deduped: list[str] = []
        for candidate in candidates:
            normalized_candidate = " ".join(candidate.split())
            if normalized_candidate and normalized_candidate not in deduped:
                deduped.append(normalized_candidate)
        return deduped

    @staticmethod
    def _extract_entity_tokens(question: str) -> list[str]:
        tokens: list[str] = []
        entity = DuckDuckGoNewsSearch._extract_entity_phrase(question)
        for ticker in DuckDuckGoNewsSearch._extract_ticker_tokens(entity or question):
            tokens.append(ticker.lower())

        if entity:
            entity = normalize_free_text(entity)
            entity = re.sub(r"\b(?:hom nay|moi nhat|gan day|recent|latest|news|noteworthy)\b", " ", entity)
            entity = re.sub(r"\b(?:co gi dang chu y|co gi|dang chu y|la gi|ra sao)\b", " ", entity)
            entity = re.sub(r"\s+", " ", entity).strip()
            if entity:
                if DuckDuckGoNewsSearch._looks_like_entity_phrase(entity):
                    tokens.append(entity)
                for part in entity.split():
                    if len(part) >= 3 and part not in QUERY_STOPWORDS:
                        tokens.append(part)
        return list(dict.fromkeys(tokens))

    @staticmethod
    def _is_relevant_hit(hit: NewsSearchHit, entity_tokens: list[str]) -> bool:
        """Kiểm tra hit có bám thực thể được hỏi hay không."""

        return DuckDuckGoNewsSearch._score_hit_relevance(hit, entity_tokens) > 0

    @staticmethod
    def _score_hit_relevance(hit: NewsSearchHit, entity_tokens: list[str]) -> int:
        """Chấm điểm hit theo thực thể và độ mới để loại bớt kết quả lạc đề."""

        if not entity_tokens:
            return DuckDuckGoNewsSearch._score_hit_freshness(hit)

        title_text = normalize_free_text(hit.title)
        snippet_text = normalize_free_text(hit.snippet)
        url_text = normalize_free_text(hit.url)

        score = 0
        for token in entity_tokens:
            if " " in token:
                if token in title_text:
                    score += 6
                if token in snippet_text:
                    score += 4
                if token in url_text:
                    score += 3
                continue

            pattern = rf"\b{re.escape(token)}\b"
            if re.search(pattern, title_text):
                score += 5
            if re.search(pattern, snippet_text):
                score += 3
            if re.search(pattern, url_text):
                score += 2

        if score <= 0:
            return 0
        return score + DuckDuckGoNewsSearch._score_hit_freshness(hit)

    @staticmethod
    def _score_hit_freshness(hit: NewsSearchHit) -> int:
        """Ưu tiên bài có tín hiệu thời gian gần hiện tại."""

        haystack = normalize_free_text(" ".join(filter(None, [hit.title, hit.snippet, hit.published_at or ""])))
        if any(marker in haystack for marker in ("hom nay", "today", "minutes ago", "minute ago", "hours ago", "hour ago")):
            return 4

        relative_days_match = RELATIVE_DAYS_PATTERN.search(haystack)
        if relative_days_match:
            days = int(relative_days_match.group(1))
            if days <= 7:
                return 3
            if days <= 30:
                return 2
            return 1

        return 0

    @staticmethod
    def _finalize_hits(
        deduped_hits: dict[str, tuple[int, NewsSearchHit]],
        target_count: int,
    ) -> list[NewsSearchHit]:
        """Sắp xếp lại hit theo độ liên quan trước khi trả về."""

        ordered_hits = sorted(
            deduped_hits.values(),
            key=lambda item: (-item[0], item[1].position, item[1].normalized_url),
        )
        return [hit for _, hit in ordered_hits[:target_count]]

    @staticmethod
    def _looks_like_entity_phrase(text: str) -> bool:
        """Giữ lại phrase thực thể, loại phrase toàn từ chức năng."""

        return any(part not in QUERY_STOPWORDS for part in text.split())

    @staticmethod
    def _extract_entity_phrase(question: str) -> str:
        """Tách thực thể chính khỏi câu hỏi tiếng Việt hoặc tiếng Anh."""

        for pattern in (COMPANY_CLAUSE_PATTERN, ENGLISH_ENTITY_PATTERN):
            match = pattern.search(question)
            if not match:
                continue

            entity = re.split(
                r"\b(?:là gì|co gi|có gì|ra sao|noteworthy|latest|recent news|recent|today|current price)\b",
                match.group(1),
                maxsplit=1,
            )[0]
            entity = re.sub(r"\b(?:news|tin tức|tin)\b", " ", entity, flags=re.IGNORECASE)
            entity = re.sub(r"\s+", " ", entity).strip(" ?.,:")
            if entity and DuckDuckGoNewsSearch._looks_like_entity_phrase(normalize_free_text(entity)):
                return entity
        return ""

    @staticmethod
    def _extract_ticker_tokens(text: str) -> list[str]:
        """Lấy ticker hợp lệ và loại các từ tiếng Anh dễ bị bắt nhầm."""

        if not text:
            return []

        tickers: list[str] = []
        for token in re.findall(r"\b[A-Z]{3,5}\b", text.upper()):
            if token in NON_TICKER_TOKENS:
                continue
            if token not in tickers:
                tickers.append(token)
        return tickers

    def _build_hit(
        self,
        *,
        item: dict[str, Any],
        site: str,
        position: int,
    ) -> NewsSearchHit | None:
        url = str(item.get("href") or item.get("url") or "").strip()
        if not url:
            return None
        normalized_url = normalize_url(url)
        effective_site = site or self._infer_site(url)
        if effective_site.replace("www.", "") not in normalized_url:
            return None
        if not is_article_url(normalized_url, effective_site):
            return None
        title = str(item.get("title") or item.get("heading") or normalized_url)
        snippet = str(item.get("body") or item.get("snippet") or "").strip()
        return NewsSearchHit(
            url=url,
            normalized_url=normalized_url,
            title=title,
            snippet=snippet,
            site=effective_site,
            position=position,
            published_at=item.get("date"),
            metadata={"normalized_url": normalized_url},
        )

    @staticmethod
    def _infer_site(url: str) -> str:
        match = re.search(r"https?://([^/]+)", url)
        return match.group(1).lower() if match else "unknown"
