"""Gemini-powered natural-language-to-SQL helper."""

from __future__ import annotations

import json
import re
import unicodedata
from hashlib import sha256
from datetime import date, datetime
from decimal import Decimal
from threading import Lock
from typing import Any

from src.config import get_settings
from src.config.base import PROJECT_ROOT
from src.agents.market_agent.sql_executor import execute_readonly_sql
from src.core.llm_pool import GeminiKeyPool


SQL_PROMPT_TEMPLATE = """
You are an expert PostgreSQL analyst for Vietnamese stock-market data.

Current local date in Asia/Ho_Chi_Minh: {today}

You can only query these relations:

1. vw_daily_stock_llm
Columns:
- ticker, name_vi, name_en, exchange, market, current_listed_shares, symbol_updated_at
- trading_date, ref_price, ceiling_price, floor_price, open_price, high_price, low_price, close_price
- avg_price, adj_close_price, effective_close_price, matched_volume, matched_value, put_through_volume, put_through_value
- total_volume, total_value, foreign_buy_vol, foreign_sell_vol, foreign_buy_value, foreign_sell_value
- foreign_room_left, total_buy_orders, total_buy_vol, total_sell_orders, total_sell_vol
- foreign_net_vol, foreign_net_value, price_change, price_change_pct
- ssi_returned_at, system_ingested_at
- snapshot_listed_shares, market_cap, ma20, ma50, ma200, rsi_14, macd, macd_signal
- flag_above_ma50, flag_overbought, flag_oversold, formula_version, calculated_at

2. vw_intraday_latest_llm
Columns:
- ticker, name_vi, name_en, exchange, market, trading_date, timestamp
- open, high, low, close, volume, api_intraday_value, updated_at

Rules:
- Use PostgreSQL syntax only.
- Return exactly one SQL query.
- The query must be read-only and start with SELECT or WITH.
- Never modify data.
- Prefer vw_daily_stock_llm unless the user explicitly asks intraday or time-of-day details.
- For historical comparisons, returns, trend analysis, ranking over time, and any question spanning multiple trading dates, prefer effective_close_price.
- When the user says "giá" in daily historical queries, default to effective_close_price unless they explicitly ask for close_price/raw close.
- When the user asks intraday or current session prices, use close from vw_intraday_latest_llm.
- When the user says "từ đầu năm", use the first available trading_date in the current calendar year for that ticker.
- When the user says "hiện tại", "hôm nay", or "mới nhất", use the latest available trading_date in the database.
- For questions comparing 2 explicit dates of the same ticker, return both dates, both effective close prices, absolute change, and percentage change.
- If you create a CTE, only reference columns that are actually selected inside that CTE.
- Always compare tickers in uppercase, e.g. ticker = 'HPG'.
- Return only the columns needed to answer the question.
- Add LIMIT when returning a list.

Return valid JSON only in this shape:
{{"sql": "...", "explanation": "short Vietnamese explanation"}}

User question:
{question}
"""


USAGE_FILE = PROJECT_ROOT / "tmp" / "gemini_usage.json"
USAGE_LOCK = Lock()


def _extract_json_block(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Gemini did not return JSON: {text}")
    return json.loads(match.group(0))


def _validate_sql(sql: str) -> str:
    candidate = sql.strip().rstrip(";")
    if not candidate:
        raise ValueError("Generated SQL is empty.")
    if ";" in candidate:
        raise ValueError("Generated SQL contains multiple statements.")
    if not re.match(r"^(select|with)\b", candidate, flags=re.IGNORECASE):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    forbidden = re.search(
        r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|copy|merge)\b",
        candidate,
        flags=re.IGNORECASE,
    )
    if forbidden:
        raise ValueError("Generated SQL contains forbidden keywords.")
    if not re.search(r"\blimit\b", candidate, flags=re.IGNORECASE):
        candidate = f"{candidate}\nLIMIT 200"
    return candidate


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_symbol_from_question(question: str) -> str | None:
    match = re.search(r"\b([A-Z]{3,5})\b", question.upper())
    return match.group(1) if match else None


def _normalize_question(question: str) -> str:
    lowered = question.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _describe_period_from_question(question: str) -> str:
    lowered = _normalize_question(question)
    if "dau thang" in lowered:
        month_match = re.search(r"thang\s+(\d{1,2})[/-](\d{4})", lowered)
        if month_match:
            return f"từ đầu tháng {int(month_match.group(1))}/{month_match.group(2)} đến phiên mới nhất"
        return "từ đầu tháng đến phiên mới nhất"
    if "dau nam" in lowered:
        year_match = re.search(r"(\d{4})", lowered)
        if year_match:
            return f"từ đầu năm {year_match.group(1)} đến phiên mới nhất"
        return "từ đầu năm đến phiên mới nhất"
    if "hien tai" in lowered or "moi nhat" in lowered or "hom nay" in lowered:
        return "đến phiên mới nhất"
    return "trong khoảng dữ liệu hiện có"


def _parse_vietnamese_date(value: str) -> date:
    day, month, year = value.split("/")
    return date(int(year), int(month), int(day))


def _build_date_comparison_sql(question: str) -> tuple[str, str] | None:
    normalized = _normalize_question(question)
    if "so sanh" not in normalized or "gia" not in normalized:
        return None

    ticker = _extract_symbol_from_question(question)
    dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", question)
    if not ticker or len(dates) < 2:
        return None

    first_date = _parse_vietnamese_date(dates[0]).isoformat()
    second_date = _parse_vietnamese_date(dates[1]).isoformat()

    sql = f"""
WITH price_1 AS (
    SELECT ticker, trading_date, effective_close_price
    FROM vw_daily_stock_llm
    WHERE ticker = '{ticker}'
      AND trading_date = '{first_date}'
),
price_2 AS (
    SELECT ticker, trading_date, effective_close_price
    FROM vw_daily_stock_llm
    WHERE ticker = '{ticker}'
      AND trading_date = '{second_date}'
)
SELECT
    price_1.ticker,
    price_1.trading_date AS date_1,
    price_1.effective_close_price AS price_1,
    price_2.trading_date AS date_2,
    price_2.effective_close_price AS price_2,
    (price_2.effective_close_price - price_1.effective_close_price) AS price_change,
    ROUND(((price_2.effective_close_price - price_1.effective_close_price) * 100.0 / NULLIF(price_1.effective_close_price, 0))::numeric, 2) AS percent_change
FROM price_1
CROSS JOIN price_2
""".strip()
    reasoning = (
        f"So sánh giá đóng cửa {ticker} giữa hai ngày {dates[0]} và {dates[1]}, "
        "trả về giá từng ngày, mức chênh lệch tuyệt đối và phần trăm biến động."
    )
    reasoning = (
        f"Compare adjusted prices of {ticker} between {dates[0]} and {dates[1]}, "
        "return the price for each date, the absolute change, and the percentage change."
    )
    return sql, reasoning


def _build_simple_market_sql(question: str) -> tuple[str, str] | None:
    """Dựng SQL heuristic cho một số câu hỏi market phổ biến khi Gemini không khả dụng.

    Args:
        question: Câu hỏi gốc của người dùng hoặc tool query đã được router tách ra.

    Returns:
        Tuple gồm SQL và reasoning ngắn nếu match được mẫu hỗ trợ; ngược lại trả về `None`.
    """

    normalized = _normalize_question(question)
    ticker = _extract_symbol_from_question(question)
    if not ticker:
        return None

    asks_current_price = any(
        token in normalized
        for token in [
            "current price",
            "latest price",
            "stock price",
            "share price",
            "gia hien tai",
            "gia moi nhat",
            "gia hom nay",
        ]
    )
    if asks_current_price:
        sql = f"""
SELECT ticker, close AS current_price, timestamp
FROM vw_intraday_latest_llm
WHERE ticker = '{ticker}'
ORDER BY timestamp DESC
LIMIT 1
""".strip()
        reasoning = f"Truy vấn giá hiện tại của {ticker} từ dữ liệu intraday mới nhất đang có trong database."
        return sql, reasoning

    return None


def _recover_sql(question: str, error_message: str) -> tuple[str, str] | None:
    lowered_error = error_message.lower()
    comparison_sql = _build_date_comparison_sql(question)
    if comparison_sql and (
        "undefinedcolumn" in lowered_error
        or "does not exist" in lowered_error
        or "syntax error" in lowered_error
    ):
        return comparison_sql
    return None


def _fallback_intraday_to_daily_sql(question: str, sql: str) -> tuple[str, str] | None:
    if "vw_intraday_latest_llm" not in sql.lower():
        return None

    ticker_match = re.search(r"\bticker\s*=\s*'([A-Z]{3,5})'", sql, flags=re.IGNORECASE)
    ticker = ticker_match.group(1).upper() if ticker_match else None
    if not ticker:
        ticker = _extract_symbol_from_question(question)
    if not ticker:
        return None

    fallback_sql = f"""
SELECT
    ticker,
    effective_close_price AS current_price,
    total_volume AS volume,
    trading_date
FROM vw_daily_stock_llm
WHERE ticker = '{ticker}'
ORDER BY trading_date DESC
LIMIT 1
""".strip()
    reasoning = (
        f"Không có dữ liệu intraday mới nhất cho {ticker}; dùng phiên daily mới nhất có trong database "
        "làm fallback cho giá và khối lượng."
    )
    return fallback_sql, reasoning


def _local_answer(question: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Chưa có dữ liệu phù hợp trong database để trả lời câu hỏi này."

    first = rows[0]
    lower_question = question.lower()

    if {"start_price", "end_price", "change_pct"} <= set(first):
        start_price = _format_scalar(first.get("start_price"))
        end_price = _format_scalar(first.get("end_price"))
        change_pct = _safe_float(first.get("change_pct"))
        ticker = first.get("ticker") or "mã này"
        current_date = first.get("current_date") or first.get("end_date") or "hiện tại"
        base_date = first.get("base_date") or "đầu kỳ"
        if change_pct is None:
            return (
                f"Đã tìm thấy dữ liệu giá cho {ticker} từ {base_date} đến {current_date}, "
                "nhưng chưa đủ dữ liệu để tính phần trăm thay đổi."
            )
        direction = "tăng" if change_pct >= 0 else "giảm"
        return (
            f"Giá cổ phiếu {ticker} đã {direction} từ {start_price} vào {base_date} "
            f"lên/xuống {end_price} vào {current_date}, tương đương {abs(change_pct):.2f}%."
        ).replace("lên/xuống", "lên" if change_pct >= 0 else "xuống")

    if "percentage_change" in first:
        ticker = first.get("ticker") or _extract_symbol_from_question(question) or "mã này"
        percentage_change = _safe_float(first.get("percentage_change"))
        if percentage_change is None:
            return (
                f"Đã tìm thấy dữ liệu cho {ticker}, nhưng chưa đủ "
                "giá trị để tính phần trăm biến động."
            )
        direction = "tăng" if percentage_change >= 0 else "giảm"
        return (
            f"Giá {ticker} đã {direction} khoảng {abs(percentage_change):.2f}% "
            f"{_describe_period_from_question(question)}."
        )

    if {"date_1", "price_1", "date_2", "price_2", "price_change", "percent_change"} <= set(first):
        ticker = first.get("ticker") or _extract_symbol_from_question(question) or "mã này"
        price_change = _safe_float(first.get("price_change"))
        percent_change = _safe_float(first.get("percent_change"))
        if price_change is None or percent_change is None:
            return (
                f"Đã tìm thấy giá {ticker} cho hai mốc thời gian, nhưng chưa đủ "
                "dữ liệu để tính chênh lệch và phần trăm biến động."
            )
        direction = "tăng" if price_change >= 0 else "giảm"
        return (
            f"Giá {ticker} đã {direction} từ {_format_scalar(first['price_1'])} vào {first['date_1']} "
            f"xuống/lên {_format_scalar(first['price_2'])} vào {first['date_2']}, "
            f"chênh {_format_scalar(abs(price_change))} và biến động {abs(percent_change):.2f}%."
        ).replace("xuống/lên", "lên" if price_change >= 0 else "xuống")

    if len(rows) == 1:
        details = ", ".join(f"{key}={_format_scalar(value)}" for key, value in first.items())
        return f"Kết quả phù hợp nhất là: {details}."

    if "top" in lower_question or "nhiều nhất" in lower_question:
        preview = "; ".join(
            ", ".join(f"{key}={_format_scalar(value)}" for key, value in row.items())
            for row in rows[:5]
        )
        return f"Tìm thấy {len(rows)} dòng. 5 dòng đầu là: {preview}."

    preview = "; ".join(
        ", ".join(f"{key}={_format_scalar(value)}" for key, value in row.items())
        for row in rows[:3]
    )
    return f"Tìm thấy {len(rows)} dòng dữ liệu. Một vài dòng đầu là: {preview}."


def _load_usage() -> dict[str, Any]:
    if not USAGE_FILE.exists():
        return {"recent_calls_by_key": {}}
    return json.loads(USAGE_FILE.read_text(encoding="utf-8"))


def _save_usage(payload: dict[str, Any]) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class GeminiSQLAssistant:
    """Generate, validate, execute, and summarize SQL with Gemini."""

    def __init__(self) -> None:
        self.settings = get_settings()
        if not self.settings.google_api_keys:
            raise ValueError("GOOGLE_API_KEY is required for NL2SQL.")
        self.generator = GeminiKeyPool(
            self.settings,
            generation_config={"temperature": 0.1},
            before_request=self._enforce_quota,
            after_success=self._record_usage,
        )

    def _generate_with_retry(self, prompt: str) -> str:
        return self.generator.generate_text(prompt)

    def _enforce_quota(self, api_key: str) -> None:
        now = datetime.now(self.settings.tzinfo)
        with USAGE_LOCK:
            usage = _load_usage()
            usage_by_key = usage.get("recent_calls_by_key", {})
            bucket = self._usage_bucket_for_key(api_key)
            recent_calls = [
                ts for ts in usage_by_key.get(bucket, [])
                if now.timestamp() - float(ts) < 60
            ]
            if len(recent_calls) >= self.settings.gemini_requests_per_minute:
                raise RuntimeError("Gemini quota guard: đã chạm giới hạn request mỗi phút.")

    def _record_usage(self, api_key: str) -> None:
        now = datetime.now(self.settings.tzinfo)
        with USAGE_LOCK:
            usage = _load_usage()
            usage_by_key = usage.setdefault("recent_calls_by_key", {})
            bucket = self._usage_bucket_for_key(api_key)
            recent_calls = [
                ts for ts in usage_by_key.get(bucket, [])
                if now.timestamp() - float(ts) < 60
            ]
            recent_calls.append(now.timestamp())
            usage_by_key[bucket] = recent_calls
            _save_usage(usage)

    @staticmethod
    def _usage_bucket_for_key(api_key: str) -> str:
        return sha256(api_key.encode("utf-8")).hexdigest()[:12]

    def ask(self, question: str) -> dict[str, Any]:
        today = datetime.now(self.settings.tzinfo).date().isoformat()
        normalized_question = question.strip()
        reasoning: str | None = None

        fallback_sql = _build_date_comparison_sql(normalized_question)
        if fallback_sql:
            sql, reasoning = fallback_sql
            sql = _validate_sql(sql)
        else:
            sql_prompt = SQL_PROMPT_TEMPLATE.format(today=today, question=normalized_question)
            try:
                sql_payload = _extract_json_block(self._generate_with_retry(sql_prompt))
                sql = _validate_sql(sql_payload["sql"])
                reasoning = sql_payload.get("explanation")
            except Exception:
                heuristic_sql = _build_simple_market_sql(normalized_question)
                if heuristic_sql is None:
                    raise
                sql, reasoning = heuristic_sql
                sql = _validate_sql(sql)

        try:
            rows = execute_readonly_sql(sql)
        except Exception as exc:  # noqa: BLE001
            recovered = _recover_sql(normalized_question, str(exc))
            if not recovered:
                raise
            sql, reasoning = recovered
            sql = _validate_sql(sql)
            rows = execute_readonly_sql(sql)
        if not rows:
            recovered = _fallback_intraday_to_daily_sql(normalized_question, sql)
            if recovered:
                sql, reasoning = recovered
                sql = _validate_sql(sql)
                rows = execute_readonly_sql(sql)

        safe_rows = [{key: _json_safe(value) for key, value in row.items()} for row in rows]

        return {
            "question": normalized_question,
            "sql": sql,
            "reasoning": reasoning,
            "row_count": len(safe_rows),
            "rows": safe_rows,
            "answer": _local_answer(normalized_question, safe_rows),
        }
