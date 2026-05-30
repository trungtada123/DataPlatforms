"""DuckDuckGo search helpers cho news tool."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from src.config.news import NewsToolSettings, get_news_tool_settings
from src.schemas.api import NewsSearchHit
from .query_build import expand_entity_tokens_for_search
from .storage import normalize_url


ARTICLE_ID_PATTERN = re.compile(r"\d{5,}(?:\.\w+)?$")
CAFEF_EMBEDDED_DATE_PATTERN = re.compile(r"188(\d{2})(\d{2})(\d{2})")
VIETSTOCK_PATH_DATE_PATTERN = re.compile(r"/(20\d{2})/(\d{1,2})(?:/|$)")
THANHNIEN_EMBEDDED_DATE_PATTERN = re.compile(r"185(\d{2})(\d{2})(\d{2})")
DNSE_ARTICLE_ID_PATTERN = re.compile(r"-(\d{7,})(?:\?|$|#)")
TITLE_DATE_PATTERN = re.compile(
    r"\b(?:thu\s+[a-z]+\s*,\s*)?(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b",
    flags=re.IGNORECASE,
)
COMPANY_CLAUSE_PATTERN = re.compile(r"(?:của|cua|về|ve)\s+([^?]+)", flags=re.IGNORECASE)
ENGLISH_ENTITY_PATTERN = re.compile(r"(?:about|of|for)\s+([^?]+)", flags=re.IGNORECASE)
TICKER_PATTERN = re.compile(r"\b([A-Z]{3,5})\b")
RELATIVE_DAYS_PATTERN = re.compile(r"\b(\d+)\s+days?\s+ago\b")
SKIP_PATH_PATTERNS = (
    r"^/$",
    r"^/tag/",
    r"^/tags/",
    r"^/category/",
    r"^/categories/",
    r"^/chu-de/",
    r"^/tin-moi",
    r"^/tin-tuc-24h",
    r"^/search",
    r"^/tim-kiem",
    r"^/video/",
    r"^/photo/",
    r"^/albums/",
    r"^/infographic/",
    r"^/login",
    r"^/user",
)
ARTICLE_NUMERIC_ID_PATTERN = re.compile(r"\d{5,}")
QUERY_STOPWORDS = {
    "about",
    "bao",
    "bao nhieu",
    "chung",
    "chung khoan",
    "chu",
    "co",
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
SOURCE_PRIORITY: tuple[str, ...] = (
    "vietstock.vn",
    "cafef.vn",
    "dnse.com.vn",
    "vnexpress.net",
    "thanhnien.vn",
)
SITE_PRIORITY_DOMAINS = SOURCE_PRIORITY
TRUSTED_SITES = SOURCE_PRIORITY

RECENT_INTENT_TOKENS = (
    "hom nay",
    "moi nhat",
    "gan day",
    "gan day nhat",
    "latest",
    "recent",
    "today",
    "tuan nay",
    "thang nay",
    "trong thang",
    "thong tin moi nhat",
)


def normalize_free_text(text: str) -> str:
    """Chuẩn hoá text để match entity ổn định hơn."""

    lowered = text.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def is_article_url(url: str, site: str) -> bool:
    """Lọc URL chắc chắn không phải bài; chấp nhận numeric ID hoặc slug bài viết dài."""

    normalized = normalize_url(url)
    normalized_site = site.replace("www.", "")
    if not normalized or len(normalized) < 25:
        return False
    if normalized_site not in normalized:
        return False
    if "finance.vietstock" in normalized:
        return False

    path = normalized.split(normalized_site, 1)[-1].split("?", 1)[0].rstrip("/")
    if any(
        marker in path.lower()
        for marker in (
            "/statistics",
            "/statistic",
            "/tim-kiem",
            "/search",
            "/tag/",
            "/tags/",
        )
    ):
        return False
    if not path or len(path) < 5:
        return False

    for pattern in SKIP_PATH_PATTERNS:
        if re.match(pattern, path):
            return False

    if ARTICLE_NUMERIC_ID_PATTERN.search(path):
        return True

    slug = path.strip("/").split("/")[-1]
    if "-" in slug and len(slug) >= 25:
        return True

    return ARTICLE_ID_PATTERN.search(normalized) is not None


def infer_timelimit(query: str) -> str | None:
    """Suy ra timelimit DuckDuckGo: d/w/m/y."""

    lowered = normalize_free_text(query)
    if any(token in lowered for token in ("hom nay", "today")):
        return "d"
    if any(token in lowered for token in ("tuan nay", "this week", "gan day", "recent")):
        return "w"
    if any(
        token in lowered
        for token in ("moi nhat", "latest", "thang nay", "trong thang", "thong tin moi nhat")
    ):
        return "m"
    if any(token in lowered for token in ("nam nay", "trong nam")):
        return "y"
    return None


def resolve_timelimit(query: str, *, default: str | None = "m") -> str | None:
    """Timelimit cho DDGS; mặc định tháng gần đây như notebook mẫu."""

    explicit = infer_timelimit(query)
    if explicit:
        return explicit

    lowered = normalize_free_text(query)
    if any(token in lowered for token in RECENT_INTENT_TOKENS):
        return "m"
    return default


def parse_publication_date_from_url(url: str) -> datetime | None:
    """Suy ra ngày đăng từ URL (ưu tiên mã ngày nhúng trên cafef.vn)."""

    normalized = normalize_url(url)
    cafef_match = CAFEF_EMBEDDED_DATE_PATTERN.search(normalized)
    if cafef_match:
        parsed = _datetime_from_parts(2000 + int(cafef_match.group(1)), int(cafef_match.group(2)), int(cafef_match.group(3)))
        if parsed:
            return parsed

    vietstock_match = VIETSTOCK_PATH_DATE_PATTERN.search(normalized)
    if vietstock_match:
        parsed = _datetime_from_parts(int(vietstock_match.group(1)), int(vietstock_match.group(2)), 1)
        if parsed:
            return parsed

    thanhnien_match = THANHNIEN_EMBEDDED_DATE_PATTERN.search(normalized)
    if thanhnien_match:
        parsed = _datetime_from_parts(
            2000 + int(thanhnien_match.group(1)),
            int(thanhnien_match.group(2)),
            int(thanhnien_match.group(3)),
        )
        if parsed:
            return parsed

    return None


def _datetime_from_parts(year: int, month: int, day: int) -> datetime | None:
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_publication_date_from_title(title: str) -> datetime | None:
    """Bắt ngày trong tiêu đề/snippet kiểu 'Thứ ba, 26/5/2026'."""

    match = TITLE_DATE_PATTERN.search(title)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


def site_priority_rank(site: str, *, site_order: tuple[str, ...] | None = None) -> int:
    """Số nhỏ hơn = ưu tiên cao hơn (vietstock → cafef → dnse → vnexpress → thanhnien)."""

    normalized_site = site.replace("www.", "").lower()
    order = site_order or SOURCE_PRIORITY
    for index, domain in enumerate(order):
        if domain in normalized_site or normalized_site.endswith(domain):
            return index
    return len(order)


def hit_source_sort_key(
    hit: NewsSearchHit,
    *,
    site_order: tuple[str, ...] | None = None,
) -> tuple[int, int, float, int, str]:
    """Khóa sort: priority nguồn → thứ hạng trong site → ngày mới → relevance."""

    metadata = hit.metadata if isinstance(hit.metadata, dict) else {}
    priority = metadata.get("source_priority")
    if priority is None:
        priority = site_priority_rank(hit.site or "", site_order=site_order)
    rank_in_source = int(metadata.get("rank_in_source") or 999)
    recency = article_recency_timestamp(
        url=hit.normalized_url or hit.url,
        published_at=hit.published_at,
        title=hit.title,
        snippet=hit.snippet,
    )
    relevance = float(metadata.get("relevance_score") or 0.0)
    return (int(priority), rank_in_source, -recency, -relevance, hit.position, hit.normalized_url)


def article_recency_timestamp(
    *,
    url: str,
    published_at: str | None = None,
    title: str | None = None,
    snippet: str | None = None,
) -> float:
    """Unix timestamp để xếp bài mới; 0 nếu không suy ra được."""

    candidates: list[datetime] = []
    if published_at:
        text = str(published_at).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                candidates.append(datetime.strptime(text, fmt).replace(tzinfo=timezone.utc))
                break
            except ValueError:
                continue
        else:
            for candidate in (text, text.replace("Z", "+00:00")):
                try:
                    parsed = datetime.fromisoformat(candidate)
                    candidates.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc))
                    break
                except ValueError:
                    continue

    parsed_url = parse_publication_date_from_url(url)
    if parsed_url:
        candidates.append(parsed_url)
    for text in (title, snippet):
        if not text:
            continue
        parsed_title = parse_publication_date_from_title(str(text))
        if parsed_title:
            candidates.append(parsed_title)

    if not candidates:
        return 0.0
    return max(item.timestamp() for item in candidates)


class DuckDuckGoNewsSearch:
    """Search client cho news tool bằng DDGS (per-site + site: operator)."""

    def __init__(self, settings: NewsToolSettings | None = None) -> None:
        self.settings = settings or get_news_tool_settings()

    def search(
        self,
        question: str,
        *,
        max_results: int | None = None,
        timelimit: str | None = None,
        compact_queries: bool = False,
    ) -> list[NewsSearchHit]:
        """Tìm bài viết trên từng trusted site, lọc URL bài thật và xếp theo liên quan/mới."""

        try:
            from ddgs import DDGS
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("ddgs is required for news search. Please install `ddgs`.") from exc

        target_count = max_results or self.settings.search_candidate_limit
        entity_tokens = expand_entity_tokens_for_search(self._extract_entity_tokens(question))
        timelimit = timelimit or resolve_timelimit(question, default=self.settings.default_search_timelimit)
        query_sequence = self._search_query_sequence(question, compact=compact_queries)
        site_order = self.settings.trusted_sites

        ordered_hits: list[NewsSearchHit] = []
        seen_urls: set[str] = set()
        next_position = 1

        with DDGS() as client:
            for source_priority, site in enumerate(site_order):
                found_for_site = 0
                rank_in_source = 0

                for query_text in query_sequence:
                    if found_for_site >= self.settings.max_results_per_site:
                        break

                    site_hits = self._search_one_site(
                        client=client,
                        site=site,
                        query_text=query_text,
                        timelimit=timelimit,
                        entity_tokens=entity_tokens,
                        start_position=next_position,
                        source_priority=source_priority,
                    )
                    for relevance_score, hit in site_hits:
                        next_position = hit.position + 1
                        if hit.normalized_url in seen_urls:
                            continue
                        seen_urls.add(hit.normalized_url)
                        rank_in_source += 1
                        metadata = {
                            **(hit.metadata if isinstance(hit.metadata, dict) else {}),
                            "relevance_score": relevance_score,
                            "source_priority": source_priority,
                            "rank_in_source": rank_in_source,
                            "search_query": f"{query_text} site:{site}",
                            "timelimit": timelimit,
                        }
                        ordered_hits.append(hit.model_copy(update={"metadata": metadata}))
                        found_for_site += 1
                        if found_for_site >= self.settings.max_results_per_site:
                            break

        ordered_hits.sort(key=lambda item: hit_source_sort_key(item, site_order=site_order))
        return ordered_hits[:target_count]

    def _search_one_site(
        self,
        *,
        client: Any,
        site: str,
        query_text: str,
        timelimit: str | None,
        entity_tokens: list[str],
        start_position: int,
        source_priority: int = 0,
    ) -> list[tuple[int, NewsSearchHit]]:
        """Tìm trên một site với pattern `{query} site:{domain}` như notebook mẫu."""

        site_key = site.replace("www.", "")
        scoped_query = f"{query_text} site:{site}"
        extra = self.settings.search_extra_results_per_site
        kwargs: dict[str, Any] = {
            "max_results": self.settings.max_results_per_site + extra,
            "region": "vn-vi",
            "safesearch": "off",
        }
        if timelimit:
            kwargs["timelimit"] = timelimit

        try:
            raw_results = client.text(scoped_query, **kwargs)
        except Exception:
            return []

        accepted: list[tuple[int, NewsSearchHit]] = []
        position = start_position
        for item in raw_results:
            if len(accepted) >= self.settings.max_results_per_site:
                break

            hit = self._build_hit(item=item, site=site, position=position, search_query=scoped_query)
            if hit is None:
                continue

            if site_key not in hit.normalized_url:
                continue

            relevance_score = self._score_hit_relevance(hit, entity_tokens)
            if relevance_score <= 0 and entity_tokens:
                continue

            position += 1
            accepted.append((relevance_score, hit))

        return accepted

    def _search_query_sequence(self, question: str, *, compact: bool = False) -> list[str]:
        """Query chính (giống notebook) rồi mới fallback biến thể entity."""

        primary = self._primary_search_query(question)
        entity = self._extract_entity_phrase(question)
        tickers = self._extract_ticker_tokens(entity or question)
        if compact and (entity or tickers):
            return [primary]

        fallbacks = self._build_query_candidates(question)
        sequence: list[str] = []
        for candidate in [primary, *fallbacks[:4 if entity or tickers else 8]]:
            normalized = " ".join(candidate.split())
            if normalized and normalized not in sequence:
                sequence.append(normalized)
        return sequence

    def _primary_search_query(self, question: str) -> str:
        """Một câu query ưu tiên cho site: search — bám entity + ý 'mới nhất'."""

        raw_question = " ".join(question.strip().split())
        normalized = normalize_free_text(raw_question)
        has_recent = any(token in normalized for token in RECENT_INTENT_TOKENS)
        entity = self._extract_entity_phrase(raw_question)
        tickers = self._extract_ticker_tokens(entity or raw_question)

        if entity:
            if has_recent:
                return f"tin tức {entity} gần đây nhất"
            return f"tin tức {entity}"

        if tickers:
            ticker = tickers[0]
            if has_recent:
                return f"tin tức {ticker} mới nhất"
            return f"tin tức {ticker}"

        cleaned = self._clean_question_for_search(raw_question)
        return cleaned or raw_question

    @staticmethod
    def _clean_question_for_search(question: str) -> str:
        cleaned = question
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
            "?",
        ):
            cleaned = cleaned.replace(token, " ")
        return re.sub(r"\s+", " ", cleaned).strip()

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
        has_recent_intent = any(token in normalized_question for token in RECENT_INTENT_TOKENS)
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

        candidates.append(raw_question)

        cleaned = DuckDuckGoNewsSearch._clean_question_for_search(raw_question)
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
        return expand_entity_tokens_for_search(list(dict.fromkeys(tokens)))

    @staticmethod
    def _is_relevant_hit(hit: NewsSearchHit, entity_tokens: list[str]) -> bool:
        return DuckDuckGoNewsSearch._score_hit_relevance(hit, entity_tokens) > 0

    @staticmethod
    def _score_hit_relevance(hit: NewsSearchHit, entity_tokens: list[str]) -> int:
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

        timelimit = hit.metadata.get("timelimit") if isinstance(hit.metadata, dict) else None
        if timelimit in {"d", "w", "m"}:
            return 2

        return 0

    @staticmethod
    def _finalize_hits(
        deduped_hits: dict[str, tuple[int, NewsSearchHit]],
        target_count: int,
        *,
        site_order: tuple[str, ...] | None = None,
    ) -> list[NewsSearchHit]:
        """Giữ tương thích test: sort theo priority nguồn rồi cắt top."""

        hits = [hit for _, hit in deduped_hits.values()]
        hits.sort(key=lambda item: hit_source_sort_key(item, site_order=site_order))
        return hits[:target_count]

    @staticmethod
    def _looks_like_entity_phrase(text: str) -> bool:
        return any(part not in QUERY_STOPWORDS for part in text.split())

    @staticmethod
    def _extract_entity_phrase(question: str) -> str:
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

        stripped = re.sub(
            r"^(?:tin tức|tin tuc|thông tin|thong tin)(?:\s+mới nhất|\s+moi nhat)?\s+",
            "",
            question,
            flags=re.IGNORECASE,
        )
        stripped = re.split(
            r"\b(?:gần đây nhất|gan day nhat|gần đây|gan day|mới nhất|moi nhat|hôm nay|hom nay)\b",
            stripped,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        stripped = re.sub(r"\b(?:có gì đáng chú ý|co gi dang chu y|là gì|la gi|ra sao)\b", " ", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s+", " ", stripped).strip(" ?.,:")
        if stripped and DuckDuckGoNewsSearch._looks_like_entity_phrase(normalize_free_text(stripped)):
            return stripped
        return ""

    @staticmethod
    def _extract_ticker_tokens(text: str) -> list[str]:
        if not text:
            return []

        tickers: list[str] = []
        for token in TICKER_PATTERN.findall(text.upper()):
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
        search_query: str,
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
            metadata={"normalized_url": normalized_url, "search_query": search_query},
        )

    @staticmethod
    def _infer_site(url: str) -> str:
        match = re.search(r"https?://([^/]+)", url)
        return match.group(1).lower() if match else "unknown"
