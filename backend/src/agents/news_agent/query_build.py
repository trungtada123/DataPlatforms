"""Chuẩn hoá câu query gửi sang DuckDuckGo (ưu tiên tiếng Việt + mã CP)."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime


TICKER_PATTERN = re.compile(r"\b([A-Z]{3,5})\b")
NON_TICKER_TOKENS = {
    "ABOUT",
    "AFTER",
    "BANK",
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
    "STOCK",
    "TECH",
    "TODAY",
    "WHAT",
    "WHEN",
    "WHICH",
    "WITH",
}


def normalize_free_text(text: str) -> str:
    lowered = text.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


TICKER_COMPANY_NAMES: dict[str, str] = {
    "HPG": "Hòa Phát",
    "ACB": "ACB",
    "FPT": "FPT",
    "VCB": "Vietcombank",
    "VHM": "Vinhomes",
    "MWG": "Thế Giới Di Động",
    "SSI": "SSI",
    "STB": "Sacombank",
    "CTG": "VietinBank",
    "BID": "BIDV",
    "GAS": "PV Gas",
    "PLX": "Petrolimex",
    "VNM": "Vinamilk",
}

TICKER_SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "HPG": ("hoa phat", "tap doan hoa phat", "cong ty hoa phat"),
    "ACB": ("ngan hang acb", "asia commercial bank"),
    "FPT": ("tap doan fpt",),
    "VNM": ("vinamilk", "cong ty vinamilk"),
}

RECENT_MARKERS = (
    "moi nhat",
    "gan day",
    "hom nay",
    "latest",
    "recent",
    "today",
    "thong tin moi nhat",
)


def extract_tickers(text: str) -> list[str]:
    scrubbed = re.sub(r"\btin(?:\s+tuc)?\b", " ", text, flags=re.IGNORECASE)
    scrubbed = re.sub(r"\bthong tin\b", " ", scrubbed, flags=re.IGNORECASE)
    tickers: list[str] = []
    for token in TICKER_PATTERN.findall(scrubbed.upper()):
        if token in NON_TICKER_TOKENS:
            continue
        if token not in tickers:
            tickers.append(token)
    return tickers


def _has_vietnamese_diacritics(text: str) -> bool:
    return any(ord(char) > 127 for char in text)


def _wants_recent_news(*texts: str) -> bool:
    normalized = normalize_free_text(" ".join(texts))
    return any(marker in normalized for marker in RECENT_MARKERS)


def build_news_search_question(planned_query: str, original_query: str = "") -> str:
    """Đổi query planner (thường tiếng Anh) sang câu search DDGS giống notebook."""

    planned = " ".join(str(planned_query or "").split())
    original = " ".join(str(original_query or "").split())
    if not planned and not original:
        return ""

    combined = f"{planned} {original}".strip()
    tickers = extract_tickers(combined)
    primary_ticker = tickers[0] if tickers else ""
    company_name = TICKER_COMPANY_NAMES.get(primary_ticker, primary_ticker)
    year = datetime.now().year

    if planned and _has_vietnamese_diacritics(planned):
        if _wants_recent_news(planned, original) and primary_ticker:
            label = company_name or primary_ticker
            if label != primary_ticker:
                return f"tin tức {label} {primary_ticker} mới nhất {year}"
            return f"tin tức {primary_ticker} mới nhất {year}"
        return planned

    if primary_ticker:
        label = company_name or primary_ticker
        if _wants_recent_news(planned, original):
            if label != primary_ticker:
                return f"tin tức {label} {primary_ticker} mới nhất {year}"
            return f"tin tức {primary_ticker} mới nhất {year}"
        if label != primary_ticker:
            return f"tin tức {label} {primary_ticker}"
        return f"tin tức {primary_ticker}"

    if original and _has_vietnamese_diacritics(original):
        return original

    cleaned = re.sub(
        r"\b(?:recent|latest|news about|news|about|stock|shares)\b",
        " ",
        planned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and _has_vietnamese_diacritics(cleaned):
        return cleaned
    if original:
        return original
    return planned or original


def expand_entity_tokens_for_search(tokens: list[str]) -> list[str]:
    """Thêm alias tên công ty để khớp tiêu đề cafef (Hòa Phát thay vì HPG)."""

    expanded = list(tokens)
    for token in tokens:
        ticker = token.upper()
        if ticker in TICKER_SEARCH_ALIASES:
            for alias in TICKER_SEARCH_ALIASES[ticker]:
                if alias not in expanded:
                    expanded.append(alias)
        if ticker in TICKER_COMPANY_NAMES:
            name = normalize_free_text(TICKER_COMPANY_NAMES[ticker])
            if name and name not in expanded:
                expanded.append(name)
            for part in name.split():
                if len(part) >= 3 and part not in expanded:
                    expanded.append(part)
    return list(dict.fromkeys(expanded))
