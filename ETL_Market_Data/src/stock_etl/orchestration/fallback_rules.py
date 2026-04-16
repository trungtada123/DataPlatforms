"""Rule-based fallback cho classifier và market adapter."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from ..symbols import DEFAULT_SYMBOLS
from .contracts import IntentPlan, ToolName


COMPANY_ALIASES: dict[str, tuple[str, str]] = {
    "acb": ("ACB", "Asia Commercial Bank"),
    "techcombank": ("TCB", "Techcombank"),
    "hoa phat": ("HPG", "Hòa Phát"),
    "hoa phát": ("HPG", "Hòa Phát"),
    "ssi": ("SSI", "SSI Securities"),
    "fpt": ("FPT", "FPT"),
    "vinamilk": ("VNM", "Vinamilk"),
}

MARKET_KEYWORDS = (
    "gia",
    "giá",
    "co phieu",
    "cổ phiếu",
    "thi truong",
    "thị trường",
    "ma50",
    "ma20",
    "ma200",
    "macd",
    "rsi",
    "chi bao",
    "chỉ báo",
    "khoi luong",
    "khối lượng",
)
NEWS_KEYWORDS = (
    "tin",
    "tin moi nhat",
    "tin mới nhất",
    "tin gan day",
    "tin gần đây",
    "tin tuc",
    "tin tức",
    "ban tin",
    "bản tin",
    "news",
    "headline",
    "bao chi",
    "báo chí",
)
FINANCIAL_REPORT_KEYWORDS = (
    "bao cao tai chinh",
    "báo cáo tài chính",
    "bctc",
    "ket qua kinh doanh",
    "kết quả kinh doanh",
    "bao cao thuong nien",
    "báo cáo thường niên",
    "doanh thu",
    "loi nhuan",
    "lợi nhuận",
    "eps",
)
CURRENT_KEYWORDS = (
    "hien tai",
    "hiện tại",
    "hom nay",
    "hôm nay",
    "moi nhat",
    "mới nhất",
    "intraday",
    "trong phien",
    "trong phiên",
)
COMPARISON_KEYWORDS = ("so sanh", "so sánh", "chenh", "chênh", "so voi", "so với")
TECHNICAL_KEYWORDS = ("ma20", "ma50", "ma200", "macd", "rsi", "chi bao", "chỉ báo", "technical")
HEALTH_DEBUG_KEYWORDS = ("health", "debug", "trace", "router", "classifier", "status")


def normalize_free_text(text: str) -> str:
    """Chuẩn hóa text để rule-based match ổn định hơn.

    Args:
        text: Câu hỏi gốc.

    Returns:
        Chuỗi đã lowercase và bỏ dấu để match keyword.
    """

    lowered = text.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def detect_tickers(question: str) -> list[str]:
    """Phát hiện ticker phổ biến xuất hiện trong câu hỏi."""

    normalized = question.upper()
    found = [ticker for ticker in DEFAULT_SYMBOLS if re.search(rf"\b{ticker}\b", normalized)]

    normalized_free_text = normalize_free_text(question)
    for alias, (ticker, _) in COMPANY_ALIASES.items():
        if alias in normalized_free_text and ticker not in found:
            found.append(ticker)

    return found


def detect_company_names(question: str) -> list[str]:
    """Phát hiện tên công ty quen thuộc từ alias đơn giản."""

    normalized = normalize_free_text(question)
    company_names: list[str] = []
    for alias, (_, company_name) in COMPANY_ALIASES.items():
        if alias in normalized and company_name not in company_names:
            company_names.append(company_name)
    return company_names


def extract_dates(question: str) -> list[str]:
    """Trích xuất các ngày explicit dạng dd/mm/yyyy hoặc yyyy-mm-dd."""

    values = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", question)
    values.extend(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question))
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def detect_simple_market_fallback(question: str) -> dict[str, Any] | None:
    """Xử lý vài câu hỏi health/debug đơn giản mà không cần gọi LLM."""

    normalized = normalize_free_text(question)
    if not any(keyword in normalized for keyword in HEALTH_DEBUG_KEYWORDS):
        return None

    return {
        "summary": "Market orchestration đang sẵn sàng và adapter market có thể nhận query.",
        "structured_data": {
            "mode": "health_debug",
            "query_type": "health_debug",
            "handled_by": "market_fallback",
        },
        "evidence": [
            {
                "kind": "fallback_rule",
                "value": "health_debug",
            }
        ],
        "raw_response": {
            "source": "fallback_rules",
            "matched_rule": "health_debug",
        },
    }


def build_rule_based_intent_plan(question: str) -> IntentPlan:
    """Tạo IntentPlan bằng rule-based để fallback khi classifier LLM fail.

    Args:
        question: Câu hỏi gốc của người dùng.

    Returns:
        IntentPlan tối thiểu đủ để router chọn market tool trong phase A.
    """

    normalized = normalize_free_text(question)
    tickers = detect_tickers(question)
    company_names = detect_company_names(question)
    explicit_dates = extract_dates(question)

    is_current = any(keyword in normalized for keyword in CURRENT_KEYWORDS)
    is_comparison = any(keyword in normalized for keyword in COMPARISON_KEYWORDS) or len(explicit_dates) >= 2
    is_technical = any(keyword in normalized for keyword in TECHNICAL_KEYWORDS)
    is_health_debug = any(keyword in normalized for keyword in HEALTH_DEBUG_KEYWORDS)
    is_historical = bool(explicit_dates) or "tu dau nam" in normalized or "từ đầu năm" in question or "lich su" in normalized
    is_news = any(keyword in normalized for keyword in NEWS_KEYWORDS) or re.search(r"\btin\b", normalized) is not None
    is_financial_reports = any(keyword in normalized for keyword in FINANCIAL_REPORT_KEYWORDS)
    has_explicit_market_keywords = any(keyword in normalized for keyword in MARKET_KEYWORDS)

    market_signal = bool(
        has_explicit_market_keywords
        or is_health_debug
        or (
            not is_news
            and not is_financial_reports
            and (is_current or is_comparison or is_technical or is_historical or bool(tickers) or bool(company_names))
        )
    )

    tools_to_use: list[ToolName] = []
    if market_signal:
        tools_to_use.append(ToolName.MARKET)
    if is_news:
        tools_to_use.append(ToolName.NEWS)
    if is_financial_reports:
        tools_to_use.append(ToolName.FINANCIAL_REPORTS)

    if is_news and not market_signal:
        primary_intent = ToolName.NEWS.value
    elif is_financial_reports and not market_signal:
        primary_intent = ToolName.FINANCIAL_REPORTS.value
    elif market_signal:
        primary_intent = ToolName.MARKET.value
    else:
        primary_intent = "unknown"

    if primary_intent == "unknown":
        confidence = 0.25
    elif primary_intent == ToolName.MARKET.value and len(tools_to_use) == 1:
        confidence = 0.85
    else:
        confidence = 0.8

    time_constraints: dict[str, Any] = {
        "explicit_dates": explicit_dates,
        "date_range": explicit_dates[:2] if len(explicit_dates) >= 2 else [],
        "relative_periods": [],
    }
    if is_current:
        time_constraints["relative_periods"].append("current_session")
    if "tu dau nam" in normalized or "từ đầu năm" in question:
        time_constraints["relative_periods"].append("year_to_date")
    if "tu dau thang" in normalized or "từ đầu tháng" in question:
        time_constraints["relative_periods"].append("month_to_date")

    analysis_requirements = {
        "intraday": is_current,
        "historical": is_historical or is_comparison,
        "technical_analysis": is_technical,
        "comparison": is_comparison,
        "health_debug": is_health_debug,
        "news": is_news,
        "financial_reports": is_financial_reports,
    }

    reasoning_parts: list[str] = []
    if tickers:
        reasoning_parts.append(f"phát hiện ticker {', '.join(tickers)}")
    if explicit_dates:
        reasoning_parts.append(f"phát hiện mốc ngày {', '.join(explicit_dates)}")
    if is_current:
        reasoning_parts.append("nhận diện câu hỏi hiện tại/intraday")
    if is_technical:
        reasoning_parts.append("nhận diện ý định technical analysis")
    if is_comparison:
        reasoning_parts.append("nhận diện ý định so sánh")
    if is_health_debug:
        reasoning_parts.append("nhận diện health/debug query")
    if is_news:
        reasoning_parts.append("nhận diện ý định news")
    if is_financial_reports:
        reasoning_parts.append("nhận diện ý định financial reports")
    if not reasoning_parts:
        reasoning_parts.append("không đủ tín hiệu để chắc chắn ngoài rule-based cơ bản")

    tool_queries = {tool.value: question for tool in tools_to_use}

    return IntentPlan(
        original_query=question,
        normalized_query=" ".join(question.strip().split()),
        tools_to_use=tools_to_use,
        tool_queries=tool_queries,
        entities={
            "tickers": tickers,
            "company_names": company_names,
            "query_date_type": "intraday" if is_current else "historical" if is_historical else "unspecified",
            "intraday": is_current,
            "historical": is_historical or is_comparison,
            "technical_analysis": is_technical,
            "comparison": is_comparison,
        },
        time_constraints=time_constraints,
        analysis_requirements=analysis_requirements,
        reasoning_brief="; ".join(reasoning_parts),
        primary_intent=primary_intent,
        classifier_mode="rule_based",
        confidence=confidence,
    )


def parse_ddmmyyyy(value: str) -> date | None:
    """Parse an toàn ngày dd/mm/yyyy cho fallback."""

    try:
        day_text, month_text, year_text = value.split("/")
        return date(int(year_text), int(month_text), int(day_text))
    except (TypeError, ValueError):
        return None
