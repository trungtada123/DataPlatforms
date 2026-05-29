"""Crawler dùng crawl4ai cho news tool."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from html import unescape
from typing import Any

from src.config.news import NewsToolSettings, get_news_tool_settings
from src.schemas.api import NewsCrawledArticle, NewsSearchHit
from .storage import normalize_url, url_hash


WHITESPACE_PATTERN = re.compile(r"\s+")
TAG_PATTERN = re.compile(r"<[^>]+>")
IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]+\)")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]+\)")
BARE_URL_PATTERN = re.compile(r"https?://\S+")
NOISE_MARKERS = (
    "kênh thông tin kinh tế",
    "bang gia dien tu",
    "bảng giá điện tử",
    "danh muc dau tu",
    "danh mục đầu tư",
    "moi nhat",
    "mới nhất",
    "doc nhanh",
    "đọc nhanh",
    "tin moi nhan",
    "tin mới nhận",
    "chia se bai viet",
    "chia sẻ bài viết",
    "binh luan",
    "bình luận",
    "tro lai",
    "trở lại",
)
TAIL_BREAK_MARKERS = (
    "tin lien quan",
    "tin liên quan",
    "xem them",
    "xem thêm",
    "co the ban quan tam",
    "có thể bạn quan tâm",
)


class Crawl4aiNewsCrawler:
    """Crawler bài viết news bằng crawl4ai."""

    def __init__(self, settings: NewsToolSettings | None = None) -> None:
        self.settings = settings or get_news_tool_settings()

    def crawl_hits(self, hits: list[NewsSearchHit]) -> list[NewsCrawledArticle]:
        """Crawl nhiều link news và bỏ qua lỗi từng link.

        Args:
            hits: Các kết quả search đã được chọn.

        Returns:
            Danh sách `NewsCrawledArticle` cùng trạng thái crawl từng link.
        """

        if not hits:
            return []
        return asyncio.run(self._crawl_hits_async(hits))

    async def _crawl_hits_async(self, hits: list[NewsSearchHit]) -> list[NewsCrawledArticle]:
        AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig = self._load_crawl4ai()
        browser_config = BrowserConfig(
            headless=True,
            verbose=False,
            extra_args=self._build_browser_extra_args(),
        )
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=self.settings.crawl_word_count_threshold,
            excluded_tags=["nav", "footer", "header", "aside", "form"],
            remove_overlay_elements=True,
            page_timeout=self.settings.crawl_timeout_ms,
        )
        async with AsyncWebCrawler(config=browser_config) as crawler:
            tasks = [self._crawl_one(crawler, hit, run_config) for hit in hits[: self.settings.max_articles_to_crawl]]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[NewsCrawledArticle] = []
        for hit, result in zip(hits[: self.settings.max_articles_to_crawl], results, strict=False):
            if isinstance(result, Exception):
                articles.append(self._build_error_article(hit, str(result)))
                continue
            articles.append(result)
        return articles

    async def _crawl_one(self, crawler: Any, hit: NewsSearchHit, run_config: Any) -> NewsCrawledArticle:
        result = await crawler.arun(url=hit.url, config=run_config)
        markdown_value = self._extract_markdown(result)
        raw_html = getattr(result, "html", None)
        cleaned_text = self._extract_article_text(
            markdown_value=markdown_value,
            title=hit.title,
            snippet=hit.snippet,
        )
        if len(cleaned_text) > self.settings.max_article_chars:
            cleaned_text = cleaned_text[: self.settings.max_article_chars].rstrip()

        status = "success"
        error_message = None
        if not getattr(result, "success", False):
            status = "partial"
            error_message = str(getattr(result, "error_message", "") or "crawl4ai returned unsuccessful result")

        if len(cleaned_text.split()) < max(10, self.settings.crawl_word_count_threshold // 4):
            status = "partial"
            if not error_message:
                error_message = "Crawler content too short, fell back to snippet."
            cleaned_text = self._clean_text(hit.snippet)

        normalized_url = normalize_url(str(getattr(result, "url", None) or hit.url))
        return NewsCrawledArticle(
            url=hit.url,
            normalized_url=normalized_url,
            url_hash=url_hash(normalized_url),
            title=hit.title,
            site=hit.site,
            position=hit.position,
            snippet=hit.snippet,
            published_at=hit.published_at,
            status=status,
            error_message=error_message,
            raw_html=raw_html,
            markdown=markdown_value,
            cleaned_text=cleaned_text,
            cleaned_excerpt=cleaned_text[:280] if cleaned_text else hit.snippet[:280],
            metadata={
                "crawler_success": bool(getattr(result, "success", False)),
                "status_code": getattr(result, "status_code", None),
                "redirected_url": getattr(result, "redirected_url", None),
                "metadata": getattr(result, "metadata", None),
            },
        )

    @staticmethod
    def _load_crawl4ai() -> tuple[Any, Any, Any, Any]:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        except ImportError as exc:  # pragma: no cover - phụ thuộc runtime ngoài.
            raise RuntimeError("crawl4ai is required for news crawling. Please install `crawl4ai`.") from exc
        return AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    @staticmethod
    def _build_browser_extra_args() -> list[str]:
        """Build stable extra args for Chromium in container/runtime."""

        # Keep minimal stable flags here. Do not duplicate or override all Crawl4AI defaults.
        # /dev/shm size is configured in docker-compose (backend shm_size) as primary mitigation.
        return [
            "--no-sandbox",
            "--disable-gpu",
            "--enable-unsafe-swiftshader",
        ]

    @staticmethod
    def _extract_markdown(result: Any) -> str | None:
        markdown_result = getattr(result, "markdown", None)
        if markdown_result is not None:
            fit_markdown = getattr(markdown_result, "fit_markdown", None)
            raw_markdown = getattr(markdown_result, "raw_markdown", None)
            if fit_markdown:
                return str(fit_markdown)
            if raw_markdown:
                return str(raw_markdown)

        fit_markdown = getattr(result, "fit_markdown", None)
        if fit_markdown:
            return str(fit_markdown)
        raw_markdown = getattr(result, "raw_markdown", None)
        if raw_markdown:
            return str(raw_markdown)
        return None

    @staticmethod
    def _clean_text(value: str | None) -> str:
        if not value:
            return ""
        no_tags = TAG_PATTERN.sub(" ", value)
        normalized = WHITESPACE_PATTERN.sub(" ", unescape(no_tags)).strip()
        return normalized

    def _extract_article_text(self, *, markdown_value: str | None, title: str, snippet: str) -> str:
        """Cố gắng bóc riêng phần thân bài, tránh menu/share/footer."""

        if not markdown_value:
            return self._clean_text(snippet)

        raw_lines = markdown_value.replace("\r\n", "\n").splitlines()
        start_index = self._find_anchor_line(raw_lines, title)
        content_lines: list[str] = []
        content_length = 0

        for raw_line in raw_lines[start_index:]:
            stripped_line = raw_line.strip()
            if not stripped_line:
                continue

            if self._should_break_tail(stripped_line, content_length):
                break

            cleaned_line = self._sanitize_markdown_line(stripped_line)
            if not cleaned_line:
                continue
            if self._is_noise_line(stripped_line, cleaned_line):
                continue

            content_lines.append(cleaned_line)
            content_length += len(cleaned_line)
            if content_length >= self.settings.max_article_chars:
                break

        cleaned_text = self._clean_text("\n".join(content_lines))
        if not cleaned_text or self._looks_like_navigation(cleaned_text):
            return self._clean_text(snippet)
        return cleaned_text

    def _find_anchor_line(self, raw_lines: list[str], title: str) -> int:
        """Tìm vị trí gần tiêu đề để cắt bỏ phần đầu trang."""

        normalized_title = self._normalize_for_match(title)
        title_tokens = [token for token in re.findall(r"[a-z0-9]+", normalized_title) if len(token) >= 3]
        if "bao" in title_tokens and "vnexpress" in title_tokens:
            title_tokens = [token for token in title_tokens if token not in {"bao", "vnexpress", "cafef"}]

        best_index = 0
        best_score = 0
        for index, raw_line in enumerate(raw_lines):
            normalized_line = self._normalize_for_match(raw_line)
            if not normalized_line:
                continue
            overlap = sum(1 for token in title_tokens[:8] if token in normalized_line)
            if overlap > best_score:
                best_index = index
                best_score = overlap
            if best_score >= max(2, min(4, len(title_tokens[:8]))):
                return best_index

        for index, raw_line in enumerate(raw_lines):
            if raw_line.lstrip().startswith("#"):
                return index
        return best_index

    def _should_break_tail(self, raw_line: str, content_length: int) -> bool:
        """Dừng khi đã vào vùng bài liên quan sau thân bài chính."""

        normalized_line = self._normalize_for_match(raw_line)
        if raw_line.startswith("[ ![") or raw_line.startswith("#### ["):
            return content_length >= 120
        if any(marker in normalized_line for marker in TAIL_BREAK_MARKERS):
            return content_length >= 120
        if content_length < 350:
            return False
        return False

    def _is_noise_line(self, raw_line: str, cleaned_line: str) -> bool:
        """Loại các line menu/share/breadcrumb không thuộc thân bài."""

        normalized_raw = self._normalize_for_match(raw_line)
        normalized_cleaned = self._normalize_for_match(cleaned_line)

        if any(marker in normalized_raw or marker in normalized_cleaned for marker in NOISE_MARKERS):
            return True
        if raw_line.startswith("[](") or raw_line.startswith("![]("):
            return True
        if raw_line.count("](") >= 2 and len(cleaned_line.split()) < 12:
            return True
        if cleaned_line in {"*", "-", "#"}:
            return True
        return False

    @staticmethod
    def _sanitize_markdown_line(raw_line: str) -> str:
        """Chuyển markdown line về plain text gọn hơn cho summarizer."""

        line = IMAGE_LINK_PATTERN.sub("", raw_line)
        line = MARKDOWN_LINK_PATTERN.sub(lambda match: match.group(1).strip(), line)
        line = BARE_URL_PATTERN.sub(" ", line)
        line = re.sub(r"^[#>*\-\s]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        return unescape(line)

    @staticmethod
    def _normalize_for_match(value: str) -> str:
        lowered = value.lower().replace("đ", "d")
        normalized = unicodedata.normalize("NFD", lowered)
        ascii_text = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
        return re.sub(r"\s+", " ", ascii_text).strip()

    @staticmethod
    def _looks_like_navigation(cleaned_text: str) -> bool:
        """Phát hiện text vẫn còn đậm đặc dấu hiệu navigation."""

        normalized_text = Crawl4aiNewsCrawler._normalize_for_match(cleaned_text)
        noise_hits = sum(1 for marker in NOISE_MARKERS if marker in normalized_text)
        short_word_count = len(cleaned_text.split())
        return noise_hits >= 2 or short_word_count < 20

    @staticmethod
    def _build_error_article(hit: NewsSearchHit, error_message: str) -> NewsCrawledArticle:
        normalized_url = normalize_url(hit.url)
        return NewsCrawledArticle(
            url=hit.url,
            normalized_url=normalized_url,
            url_hash=url_hash(normalized_url),
            title=hit.title,
            site=hit.site,
            position=hit.position,
            snippet=hit.snippet,
            published_at=hit.published_at,
            status="error",
            error_message=error_message,
            cleaned_text=hit.snippet,
            cleaned_excerpt=hit.snippet[:280],
            metadata={"crawler_success": False},
        )
