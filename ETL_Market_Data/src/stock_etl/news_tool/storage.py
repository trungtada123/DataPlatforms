"""Storage abstraction cho artifact của news tool."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PREFIXES = (
    "utm_",
    "ga_",
)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "gbraid",
    "wbraid",
    "igshid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "_ga",
    "_gl",
}


def _is_tracking_query_key(key: str) -> bool:
    lowered = key.strip().lower()
    if not lowered:
        return False
    if lowered in TRACKING_QUERY_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)


def canonicalize_url(url: str) -> str:
    """Chuẩn hoá URL để dedupe và tạo hash ổn định.

    Args:
        url: URL gốc của bài viết.

    Returns:
        URL đã bỏ fragment, bỏ tracking query params và sort query string.
    """

    parts = urlsplit(url.strip())
    normalized_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if _is_tracking_query_key(key):
            continue
        normalized_pairs.append((key, value))

    normalized_query = urlencode(sorted(normalized_pairs))
    normalized_path = parts.path or "/"
    if normalized_path != "/" and normalized_path.endswith("/"):
        normalized_path = normalized_path.rstrip("/")

    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), normalized_path, normalized_query, ""))


def normalize_url(url: str) -> str:
    """Backward-compatible alias cho canonicalize_url()."""

    return canonicalize_url(url)


def url_hash(url: str) -> str:
    """Tạo hash ổn định cho URL chuẩn hoá."""

    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def content_hash(value: str) -> str:
    """Tạo hash nội dung để truy vết artifact."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LocalArtifactStorage:
    """Filesystem storage dùng cho dev mode của news tool."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def persist_article_artifacts(
        self,
        query_id: str,
        normalized_url_hash: str,
        *,
        raw_html: str | None,
        markdown: str | None,
        cleaned_text: str | None,
        extracted_payload: dict[str, Any],
    ) -> dict[str, str | None]:
        """Lưu bộ artifact của một bài viết xuống local filesystem.

        Args:
            query_id: Query id để group artifact theo run.
            normalized_url_hash: Hash của URL chuẩn hoá.
            raw_html: HTML thô sau crawl nếu có.
            markdown: Markdown do crawler sinh ra nếu có.
            cleaned_text: Plain text đã làm sạch nếu có.
            extracted_payload: Metadata/payload có cấu trúc của bài viết.

        Returns:
            Mapping từ artifact type sang key tương đối.
        """

        article_dir = self.root / query_id / normalized_url_hash
        article_dir.mkdir(parents=True, exist_ok=True)

        keys: dict[str, str | None] = {
            "raw_html_artifact_key": self._write_text(article_dir / "raw.html", raw_html),
            "markdown_artifact_key": self._write_text(article_dir / "article.md", markdown),
            "cleaned_text_artifact_key": self._write_text(article_dir / "cleaned.txt", cleaned_text),
            "extracted_payload_artifact_key": self._write_json(article_dir / "payload.json", extracted_payload),
        }
        return keys

    def _write_text(self, path: Path, content: str | None) -> str | None:
        if content is None:
            return None
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.root))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> str | None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.relative_to(self.root))
