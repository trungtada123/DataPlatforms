"""Classifier node and canonical intent-classification logic."""

from __future__ import annotations

"""Rule-based fallback cho classifier và market adapter."""


import re
import unicodedata
from datetime import date
from typing import Any

from src.config.market import DEFAULT_SYMBOLS
from src.schemas.orchestration import IntentPlan, ToolName


COMPANY_ALIASES: dict[str, tuple[str, str]] = {
    "acb": ("ACB", "Asia Commercial Bank"),
    "ngan hang a chau": ("ACB", "Asia Commercial Bank"),
    "ngan hang tmcp a chau": ("ACB", "Asia Commercial Bank"),
    "asia commercial bank": ("ACB", "Asia Commercial Bank"),
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
    "price",
    "current price",
    "co phieu",
    "cổ phiếu",
    "stock price",
    "share price",
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
    "phan tram",
    "phần trăm",
    "%",
    "phien truoc",
    "phiên trước",
    "tang giam",
    "tăng giảm",
    "bien dong gia",
    "biến động giá",
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
    "financial report",
    "financial statements",
    "bctc",
    "ket qua kinh doanh",
    "kết quả kinh doanh",
    "bao cao thuong nien",
    "báo cáo thường niên",
    "annual report",
    "review opinion",
    "audit opinion",
    "review conclusion",
    "soat xet",
    "soát xét",
    "kiem toan",
    "kiểm toán",
    "y kien soat xet",
    "ý kiến soát xét",
    "y kien kiem toan",
    "ý kiến kiểm toán",
    "unqualified review opinion",
    "doanh thu",
    "loi nhuan",
    "lợi nhuận",
    "eps",
    "bao cao ket qua hoat dong",
    "báo cáo kết quả hoạt động",
    "ket qua hoat dong kinh doanh",
    "kết quả hoạt động kinh doanh",
    "giua nien do",
    "giữa niên độ",
    "ban niên",
    "bán niên",
    "sau 6 thang",
    "sau 6 tháng",
    "6 thang dau nam",
    "6 tháng đầu năm",
    "bang can doi",
    "bảng cân đối",
    "thuyet minh",
    "thuyết minh",
)
FINANCIAL_REPORT_METRIC_KEYWORDS = (
    "tong tai san",
    "tổng tài sản",
    "cho vay khach hang",
    "cho vay khách hàng",
    "tien gui cua khach hang",
    "tiền gửi của khách hàng",
    "loi nhuan sau thue",
    "lợi nhuận sau thuế",
    "chi phi du phong",
    "chi phí dự phòng",
    "rui ro tin dung",
    "rủi ro tín dụng",
    "thu nhap luan",
    "thu nhập lãi",
    "lai thuan",
    "lãi thuần",
    "total assets",
    "customer loans",
    "customer deposits",
    "profit after tax",
    "provision expense",
    "credit risk",
)
CURRENT_KEYWORDS = (
    "hien tai",
    "hiện tại",
    "current",
    "hom nay",
    "hôm nay",
    "moi nhat",
    "mới nhất",
    "latest",
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


def _extract_report_year(question: str) -> int | None:
    match = re.search(r"\b(20\d{2})\b", question)
    if not match:
        return None
    return int(match.group(1))


def _extract_report_quarter(question: str) -> int | None:
    quarter_match = re.search(r"\bq([1-4])\b", question, flags=re.IGNORECASE)
    if quarter_match:
        return int(quarter_match.group(1))

    vietnamese_match = re.search(r"quy\s*([1-4])", normalize_free_text(question))
    if vietnamese_match:
        return int(vietnamese_match.group(1))

    english_match = re.search(r"quarter\s*([1-4])", normalize_free_text(question))
    if english_match:
        return int(english_match.group(1))
    return None


def question_requires_financial_reports(question: str) -> bool:
    """Nhận diện câu hỏi cần nhánh BCTC kể cả khi Gemini chỉ chọn market/news."""

    normalized = normalize_free_text(question)
    asks_report_metric = any(keyword in normalized for keyword in FINANCIAL_REPORT_METRIC_KEYWORDS)
    has_filing_context = any(
        (
            any(keyword in normalized for keyword in FINANCIAL_REPORT_KEYWORDS),
            _extract_report_year(question) is not None,
            _extract_report_quarter(question) is not None,
            re.search(r"\d{1,2}[/.]\d{1,2}[/.]?\d{2,4}", question) is not None,
            "6 thang" in normalized,
            "giua nien do" in normalized,
        )
    )
    if asks_report_metric and has_filing_context:
        return True
    return any(keyword in normalized for keyword in FINANCIAL_REPORT_KEYWORDS) and has_filing_context


def _build_fallback_tool_queries(
    question: str,
    tools_to_use: list[ToolName],
    tickers: list[str],
    company_names: list[str],
    *,
    is_current: bool,
    is_technical: bool,
    is_financial_reports: bool,
) -> dict[str, str]:
    primary_ticker = tickers[0] if tickers else ""
    primary_company = company_names[0] if company_names else ""
    report_year = _extract_report_year(question)
    report_quarter = _extract_report_quarter(question)
    normalized_question = normalize_free_text(question)
    asks_report_metric = any(keyword in normalized_question for keyword in FINANCIAL_REPORT_METRIC_KEYWORDS)

    tool_queries: dict[str, str] = {}
    for tool in tools_to_use:
        if tool == ToolName.MARKET:
            if primary_ticker and is_technical:
                tool_queries[tool.value] = f"technical indicators for {primary_ticker}"
            elif primary_ticker and is_current:
                tool_queries[tool.value] = f"giá hiện tại của {primary_ticker}"
            elif primary_ticker:
                tool_queries[tool.value] = f"dữ liệu thị trường của {primary_ticker}"
            else:
                tool_queries[tool.value] = question
            continue

        if tool == ToolName.NEWS:
            if primary_ticker:
                tool_queries[tool.value] = f"tin tức {primary_ticker} mới nhất"
            elif primary_company:
                tool_queries[tool.value] = f"tin tức {primary_company} mới nhất"
            else:
                tool_queries[tool.value] = question
            continue

        if tool == ToolName.FINANCIAL_REPORTS:
            if primary_ticker and asks_report_metric:
                tool_queries[tool.value] = question
            elif primary_ticker and report_year and report_quarter and is_financial_reports:
                tool_queries[tool.value] = (
                    f"{primary_ticker} reviewed financial statements Q{report_quarter} {report_year} opinion"
                )
            elif primary_ticker:
                tool_queries[tool.value] = f"financial report for {primary_ticker}"
            else:
                tool_queries[tool.value] = question
            continue

        tool_queries[tool.value] = question

    return tool_queries


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
    asks_report_metric = any(keyword in normalized for keyword in FINANCIAL_REPORT_METRIC_KEYWORDS)
    is_financial_reports = question_requires_financial_reports(question) or any(
        keyword in normalized for keyword in FINANCIAL_REPORT_KEYWORDS
    )
    if asks_report_metric and not is_financial_reports:
        is_financial_reports = True
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

    tool_queries = _build_fallback_tool_queries(
        question,
        tools_to_use,
        tickers,
        company_names,
        is_current=is_current,
        is_technical=is_technical,
        is_financial_reports=is_financial_reports,
    )

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


"""Intent classifier cho orchestration market-first."""


import json
import re
from datetime import datetime, timezone
from typing import Any

from src.config import Settings, get_settings
from src.core.llm_pool import GeminiKeyPool
from src.schemas.orchestration import IntentPlan, NormalizedQueryRequest, ToolName



CLASSIFIER_PROMPT_TEMPLATE = """
You are an intent classifier for a Vietnamese stock-market orchestration service.
Downstream agents ONLY receive your JSON — especially `tool_queries`, `entities`, `time_constraints`,
and `analysis_requirements`. Choosing tools is not enough; each selected tool needs a concrete query.

Current date: {today}

Supported tools (exact keys):
- market — live/historical prices, volume, MA/MACD/RSI, intraday, compare prices across dates
- news — recent articles about tickers/companies (web search + crawl; freshness matters)
- financial_reports — BCTC, quarterly/annual reports, audit opinion, line items from filings

Routing rules:
- Price / indicators / compare dates → primary_intent `market`, include `market` in tools_to_use
- News / headlines / "tin tức" / sentiment from articles → primary_intent `news`, include `news`
- Báo cáo tài chính / financial statements / quý Q1 Q2 → primary_intent `financial_reports`
- Mixed questions (e.g. "tin mới và giá phản ứng") → list ALL needed tools in tools_to_use

CRITICAL — `tool_queries` (one entry per tool in tools_to_use, omit unused tools):
- market: Vietnamese if user wrote Vietnamese. Include ticker(s). Examples:
  "giá hiện tại của ACB", "chỉ báo kỹ thuật HPG MA50 MACD", "so sánh giá TCB ngày 13/01/2026 và 14/04/2026"
- news: Vietnamese search phrase for DuckDuckGo. MUST include ticker or company name + recency.
  Good: "tin tức FPT mới nhất", "tin tức Hòa Phát HPG mới nhất", "tin ACB hôm nay"
  Bad: "FPT latest news", "news about ACB" (English hurts search on VN sites)
- financial_reports: keep quarter/year and audit/metric wording from the user when present.
  Good: "báo cáo tài chính quý 2 năm 2025 ACB", "ACB reviewed financial statements Q2 2025 opinion"
  Bad: generic "financial report for ACB" when user specified Q2/2025

CRITICAL — `entities`:
- tickers: uppercase HOSE symbols only (ACB, FPT, HPG, …). Never put words like TIN from "tin tức".
- company_names: Vietnamese or English legal/common names when known (e.g. "Hòa Phát", "Vinamilk")
- Do NOT put analysis flags inside entities; use analysis_requirements instead.

CRITICAL — `time_constraints`:
- explicit_dates: DD/MM/YYYY strings copied from the user for market compare or report as-of dates
- date_range: [start, end] when user gives a range
- relative_periods: e.g. "current_session", "year_to_date", "month_to_date", "latest_news", "quarter_2_2025"

CRITICAL — `analysis_requirements` (booleans used by merger/router):
- intraday, historical, technical_analysis, comparison, news, financial_reports, health_debug
- Set `news: true` when news tool is used; `financial_reports: true` when reports tool is used.

`normalized_query`: short faithful paraphrase of user intent (Vietnamese if user used Vietnamese).

Return valid JSON only:
{{
  "primary_intent": "market|news|financial_reports|unknown",
  "normalized_query": "...",
  "tools_to_use": ["market"],
  "tool_queries": {{"market": "giá hiện tại của ACB"}},
  "entities": {{
    "tickers": ["ACB"],
    "company_names": ["Asia Commercial Bank"]
  }},
  "time_constraints": {{
    "explicit_dates": [],
    "date_range": [],
    "relative_periods": []
  }},
  "analysis_requirements": {{
    "intraday": true,
    "historical": false,
    "technical_analysis": false,
    "comparison": false,
    "news": false,
    "financial_reports": false,
    "health_debug": false
  }},
  "reasoning_brief": "short explanation",
  "confidence": 0.0
}}

User query:
{question}
"""


class IntentClassifier:
    """Phân loại intent và tạo IntentPlan cho router.

    Args:
        settings: Settings override nếu caller muốn tái sử dụng config hiện có.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def classify(self, request: NormalizedQueryRequest | str) -> IntentPlan:
        """Classify một query thành IntentPlan.

        Args:
            request: Request chuẩn hóa hoặc raw string.

        Returns:
            IntentPlan dùng cho router.
        """

        normalized_request = request if isinstance(request, NormalizedQueryRequest) else NormalizedQueryRequest(question=request)
        fallback_plan = build_rule_based_intent_plan(normalized_request.question)

        if not self.settings.google_api_keys:
            return fallback_plan

        try:
            plan = self._classify_with_gemini(normalized_request.question, fallback_plan)
            plan = self._preserve_multi_tool_guard(normalized_request.question, plan, fallback_plan)
            return self._refine_intent_plan(normalized_request.question, plan, fallback_plan)
        except Exception:
            fallback_plan.classifier_mode = "fallback_rule_based"
            return fallback_plan

    def _classify_with_gemini(self, question: str, fallback_plan: IntentPlan) -> IntentPlan:
        """Dùng Gemini để enrich thêm plan khi có model khả dụng."""

        now_tz = getattr(self.settings, "tzinfo", timezone.utc)
        prompt = CLASSIFIER_PROMPT_TEMPLATE.format(
            today=datetime.now(now_tz).date().isoformat(),
            question=question,
        )
        response_text = GeminiKeyPool(
            self.settings,
            generation_config={"temperature": 0.0},
        ).generate_text(prompt)
        payload = self._extract_json_payload(response_text or "")
        return self._plan_from_payload(question, payload, fallback_plan)

    @staticmethod
    def _extract_json_payload(text: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Classifier model did not return JSON.")
        return json.loads(match.group(0))

    @staticmethod
    def _normalize_tools(raw_tools: list[Any], fallback_plan: IntentPlan) -> list[ToolName]:
        tools: list[ToolName] = []
        for raw_tool in raw_tools:
            try:
                tool = ToolName(str(raw_tool))
            except ValueError:
                continue
            if tool not in tools:
                tools.append(tool)

        if tools:
            return tools
        if fallback_plan.tools_to_use:
            return fallback_plan.tools_to_use
        primary_intent = fallback_plan.primary_intent
        try:
            return [ToolName(primary_intent)]
        except ValueError:
            return []

    def _plan_from_payload(
        self,
        question: str,
        payload: dict[str, Any],
        fallback_plan: IntentPlan,
    ) -> IntentPlan:
        tools_to_use = self._normalize_tools(payload.get("tools_to_use") or [], fallback_plan)
        normalized_query = str(payload.get("normalized_query") or fallback_plan.normalized_query)

        tool_queries = dict(fallback_plan.tool_queries)
        raw_tool_queries = payload.get("tool_queries") or {}
        for key, value in raw_tool_queries.items():
            if value:
                tool_queries[str(key)] = str(value)
        fallback_reports_query = fallback_plan.tool_queries.get(ToolName.FINANCIAL_REPORTS.value)
        current_reports_query = tool_queries.get(ToolName.FINANCIAL_REPORTS.value)
        if self._is_metric_report_question(question) and ToolName.FINANCIAL_REPORTS in tools_to_use:
            tool_queries[ToolName.FINANCIAL_REPORTS.value] = question
        elif (
            fallback_reports_query
            and current_reports_query
            and self._should_prefer_fallback_reports_query(fallback_reports_query, current_reports_query)
        ):
            tool_queries[ToolName.FINANCIAL_REPORTS.value] = fallback_reports_query
        for tool in tools_to_use:
            tool_queries.setdefault(tool.value, normalized_query)

        entities = dict(fallback_plan.entities)
        entities.update(payload.get("entities") or {})

        analysis_requirements = dict(fallback_plan.analysis_requirements)
        analysis_requirements.update(payload.get("analysis_requirements") or {})

        time_constraints = dict(fallback_plan.time_constraints)
        time_constraints.update(payload.get("time_constraints") or {})

        primary_intent = str(payload.get("primary_intent") or fallback_plan.primary_intent)
        valid_primary_intents = {tool.value for tool in ToolName} | {"unknown"}
        if primary_intent not in valid_primary_intents:
            primary_intent = fallback_plan.primary_intent
        if primary_intent == "unknown" and tools_to_use:
            primary_intent = tools_to_use[0].value
        if not tools_to_use and primary_intent in {tool.value for tool in ToolName}:
            tools_to_use = [ToolName(primary_intent)]
            tool_queries.setdefault(primary_intent, normalized_query)

        confidence = payload.get("confidence", fallback_plan.confidence)
        try:
            normalized_confidence = float(confidence)
        except (TypeError, ValueError):
            normalized_confidence = fallback_plan.confidence

        plan = IntentPlan(
            original_query=question,
            normalized_query=normalized_query,
            tools_to_use=tools_to_use,
            tool_queries=tool_queries,
            entities=entities,
            time_constraints=time_constraints,
            analysis_requirements=analysis_requirements,
            reasoning_brief=str(payload.get("reasoning_brief") or fallback_plan.reasoning_brief),
            primary_intent=primary_intent,
            classifier_mode="gemini",
            confidence=normalized_confidence,
        )
        return self._refine_intent_plan(question, plan, fallback_plan)

    @staticmethod
    def _question_uses_vietnamese(text: str) -> bool:
        return bool(
            re.search(
                r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]",
                text,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _should_prefer_fallback_tool_query(
        tool: ToolName,
        question: str,
        fallback_query: str,
        current_query: str,
    ) -> bool:
        fallback = " ".join((fallback_query or "").split())
        current = " ".join((current_query or "").split())
        if not fallback:
            return False
        if not current:
            return True

        if tool == ToolName.FINANCIAL_REPORTS:
            return IntentClassifier._should_prefer_fallback_reports_query(fallback, current)

        if tool == ToolName.NEWS:
            if IntentClassifier._question_uses_vietnamese(question) and not IntentClassifier._question_uses_vietnamese(
                current
            ):
                return True
            fb_norm = normalize_free_text(fallback)
            cur_norm = normalize_free_text(current)
            news_hints = ("tin tuc", "tin ", "moi nhat", "hom nay")
            if any(hint in fb_norm for hint in news_hints) and "tin" not in cur_norm:
                return True
            if re.search(r"\b(?:latest news|news about)\b", current, flags=re.IGNORECASE):
                return True
            return False

        if tool == ToolName.MARKET:
            if IntentClassifier._question_uses_vietnamese(question) and not IntentClassifier._question_uses_vietnamese(
                current
            ):
                return True
            cur_norm = normalize_free_text(current)
            if "price" in cur_norm or "current price" in cur_norm:
                vn_market = ("gia", "ma50", "macd", "rsi", "so sanh", "chi bao")
                if not any(token in cur_norm for token in vn_market):
                    return True
            return False

        return False

    def _refine_intent_plan(self, question: str, plan: IntentPlan, fallback_plan: IntentPlan) -> IntentPlan:
        """Gộp metadata rule-based và sửa tool_queries mơ hồ từ LLM."""

        tickers = [
            str(item).strip().upper()
            for item in (plan.entities.get("tickers") or [])
            if str(item).strip()
        ]
        for ticker in detect_tickers(question):
            if ticker not in tickers:
                tickers.append(ticker)
        for ticker in fallback_plan.entities.get("tickers") or []:
            normalized = str(ticker).strip().upper()
            if normalized and normalized not in tickers:
                tickers.append(normalized)

        companies = [
            str(item).strip()
            for item in (plan.entities.get("company_names") or [])
            if str(item).strip()
        ]
        for name in detect_company_names(question):
            if name not in companies:
                companies.append(name)
        for name in fallback_plan.entities.get("company_names") or []:
            normalized = str(name).strip()
            if normalized and normalized not in companies:
                companies.append(normalized)

        analysis_requirements = dict(fallback_plan.analysis_requirements)
        analysis_requirements.update(plan.analysis_requirements or {})
        if ToolName.NEWS in plan.tools_to_use:
            analysis_requirements["news"] = True
        if ToolName.FINANCIAL_REPORTS in plan.tools_to_use:
            analysis_requirements["financial_reports"] = True

        expected_queries = _build_fallback_tool_queries(
            question,
            plan.tools_to_use,
            tickers,
            companies,
            is_current=bool(analysis_requirements.get("intraday")),
            is_technical=bool(analysis_requirements.get("technical_analysis")),
            is_financial_reports=bool(analysis_requirements.get("financial_reports")),
        )

        tool_queries = dict(plan.tool_queries)
        for tool in plan.tools_to_use:
            fallback_query = expected_queries.get(tool.value) or fallback_plan.tool_queries.get(tool.value, "")
            current_query = tool_queries.get(tool.value, "")
            if self._is_metric_report_question(question) and tool == ToolName.FINANCIAL_REPORTS:
                tool_queries[tool.value] = question
                continue
            if self._should_prefer_fallback_tool_query(tool, question, fallback_query, current_query):
                tool_queries[tool.value] = fallback_query
            elif not current_query.strip():
                tool_queries[tool.value] = fallback_query

        entities = dict(fallback_plan.entities)
        entities.update(plan.entities or {})
        entities["tickers"] = tickers
        entities["company_names"] = companies

        time_constraints = dict(fallback_plan.time_constraints)
        raw_time = plan.time_constraints or {}
        for key, value in raw_time.items():
            if not value:
                continue
            if key == "relative_periods":
                merged = list(time_constraints.get("relative_periods", []))
                for item in value:
                    if item not in merged:
                        merged.append(item)
                time_constraints["relative_periods"] = merged
            elif key == "explicit_dates":
                merged = list(time_constraints.get("explicit_dates", []))
                for item in value:
                    if item not in merged:
                        merged.append(item)
                time_constraints["explicit_dates"] = merged
            else:
                time_constraints[key] = value

        normalized_query = plan.normalized_query
        if self._question_uses_vietnamese(question) and not self._question_uses_vietnamese(normalized_query):
            normalized_query = question

        return plan.model_copy(
            update={
                "tool_queries": tool_queries,
                "entities": entities,
                "time_constraints": time_constraints,
                "analysis_requirements": analysis_requirements,
                "normalized_query": normalized_query,
            }
        )

    @staticmethod
    def _should_prefer_fallback_reports_query(fallback_query: str, current_query: str) -> bool:
        """Giữ query reports cụ thể hơn nếu model làm rơi mốc thời gian/ý định kiểm toán."""

        fallback_normalized = fallback_query.casefold()
        current_normalized = current_query.casefold()
        fallback_has_year = re.search(r"\b20\d{2}\b", fallback_normalized) is not None
        fallback_has_quarter = re.search(r"\bq[1-4]\b", fallback_normalized) is not None
        fallback_has_opinion = any(token in fallback_normalized for token in ["opinion", "review", "audit"])
        current_has_year = re.search(r"\b20\d{2}\b", current_normalized) is not None
        current_has_quarter = re.search(r"\bq[1-4]\b", current_normalized) is not None
        current_has_opinion = any(token in current_normalized for token in ["opinion", "review", "audit"])

        return (
            (fallback_has_year and not current_has_year)
            or (fallback_has_quarter and not current_has_quarter)
            or (fallback_has_opinion and not current_has_opinion)
        )

    @staticmethod
    def _is_metric_report_question(question: str) -> bool:
        """Giữ nguyên câu hỏi reports dạng lấy chỉ tiêu/số liệu trong bảng."""

        normalized = question.casefold()
        metric_keywords = tuple(FINANCIAL_REPORT_METRIC_KEYWORDS)
        report_keywords = tuple(FINANCIAL_REPORT_KEYWORDS)
        has_metric = any(metric in normalized for metric in metric_keywords)
        has_report = any(keyword in normalized for keyword in report_keywords) or _extract_report_year(
            question
        ) is not None
        return has_metric and has_report

    @staticmethod
    def _preserve_multi_tool_guard(
        question: str,
        plan: IntentPlan,
        fallback_plan: IntentPlan,
    ) -> IntentPlan:
        """Gộp tool từ fallback + tín hiệu BCTC trong câu hỏi để tránh Gemini bỏ sót financial_reports."""

        merged_tools = list(fallback_plan.tools_to_use)
        for tool in plan.tools_to_use:
            if tool not in merged_tools:
                merged_tools.append(tool)
        if question_requires_financial_reports(question) and ToolName.FINANCIAL_REPORTS not in merged_tools:
            merged_tools.append(ToolName.FINANCIAL_REPORTS)

        if merged_tools == list(plan.tools_to_use):
            return plan

        merged_tool_queries = dict(fallback_plan.tool_queries)
        merged_tool_queries.update(plan.tool_queries)
        for tool in merged_tools:
            merged_tool_queries.setdefault(tool.value, plan.normalized_query)

        return plan.model_copy(
            update={
                "tools_to_use": merged_tools,
                "tool_queries": merged_tool_queries,
                "reasoning_brief": f"{plan.reasoning_brief}; giữ/bổ sung multi-tool (fallback + BCTC signal)",
            }
        )

from src.orchestration.state import OrchestrationState

def classify(state: OrchestrationState) -> dict[str, Any]:
    query = state.get("query", "").strip()
    trace = list(state.get("trace", [])); errors = list(state.get("errors", [])); metadata = dict(state.get("metadata", {}))
    if not query:
        errors.append("missing_query"); trace.append({"step":"classifier","status":"error","detail":"State does not contain a valid query."})
        return {"intent":None,"intent_confidence":None,"trace":trace,"errors":errors,"metadata":metadata}
    try:
        plan = IntentClassifier().classify(query)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"classifier_error:{exc}"); trace.append({"step":"classifier","status":"error","detail":str(exc)})
        return {"intent":None,"intent_confidence":None,"trace":trace,"errors":errors,"metadata":metadata}
    metadata["intent_plan"] = plan.model_dump(mode="json")
    trace.append({"step":"classifier","status":"ok","detail":plan.reasoning_brief,"metadata":{"primary_intent":plan.primary_intent,"tools_to_use":[tool.value for tool in plan.tools_to_use],"classifier_mode":plan.classifier_mode,"confidence":plan.confidence}})
    return {"intent":plan.primary_intent,"intent_confidence":plan.confidence,"trace":trace,"errors":errors,"metadata":metadata}
