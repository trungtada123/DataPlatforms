"""Retrieval helpers cho financial reports runtime."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .contracts import ReportCandidate, ReportQueryFilters, ReportQueryPlan


COMPANY_ALIAS_MAP = {
    "asia commercial bank": "ACB",
    "ngan hang tmcp a chau": "ACB",
    "hoa phat": "HPG",
    "tap doan hoa phat": "HPG",
    "fpt": "FPT",
    "techcombank": "TCB",
    "vinamilk": "VNM",
}
REPORT_TYPE_KEYWORDS = {
    "ket qua kinh doanh": "income_statement",
    "bao cao ket qua hoat dong kinh doanh": "income_statement",
    "bang can doi ke toan": "balance_sheet",
    "luu chuyen tien te": "cash_flow",
    "thuyet minh": "notes",
}
REPORT_FAMILY_KEYWORDS = {
    "bao cao tai chinh": "BCTC",
    "bctc": "BCTC",
    "financial report": "BCTC",
    "financial reports": "BCTC",
    "financial statement": "BCTC",
    "financial statements": "BCTC",
    "thuyet minh": "notes",
}
SCOPE_KEYWORDS = {
    "hop nhat": "Hopnhat",
    "rieng": "Congtyme",
    "cong ty me": "Congtyme",
    "consolidated": "Hopnhat",
    "separate": "Congtyme",
    "standalone": "Congtyme",
    "parent company": "Congtyme",
}
AMOUNT_KEYWORDS = (
    "bao nhieu",
    "so tien",
    "gia tri",
    "how much",
    "what is",
    "what was",
    "as of",
    "tai ngay",
)
OPINION_KEYWORDS = (
    "opinion",
    "review opinion",
    "audit opinion",
    "review conclusion",
    "reviewed financial statements",
    "soat xet",
    "kiem toan",
    "y kien soat xet",
    "y kien kiem toan",
    "ket luan kiem toan",
    "ket luan cua kiem toan vien",
)
METRIC_ALIASES = {
    "tong tai san": ("tong tai san", "total assets"),
    "cho vay khach hang": ("cho vay khach hang", "customer loans", "loans to customers"),
    "tien gui cua khach hang": ("tien gui cua khach hang", "customer deposits", "deposits from customers"),
    "loi nhuan sau thue": ("loi nhuan sau thue", "profit after tax", "net profit"),
}
BALANCE_SHEET_METRICS = {"tong tai san", "cho vay khach hang", "tien gui cua khach hang"}
INCOME_STATEMENT_METRICS = {"loi nhuan sau thue"}


def fold_text(text: str | None) -> str:
    """Bỏ dấu và lower-case để match ổn định hơn."""

    safe = (text or "").replace("đ", "d").replace("Đ", "D")
    base = unicodedata.normalize("NFKD", safe)
    no_accents = "".join(ch for ch in base if not unicodedata.combining(ch))
    return no_accents.casefold()


def normalize_spaces(text: str) -> str:
    """Co cụm whitespace về một khoảng trắng."""

    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    """Tách token đơn giản cho rerank."""

    return [token for token in re.findall(r"\w+", fold_text(text)) if token]


def payload_text(payload: dict[str, Any]) -> str:
    """Lấy text chính của payload để retrieval/synthesis dùng chung."""

    metadata = payload.get("metadata") or {}
    chunk_type = payload.get("chunk_type")
    if chunk_type == "table_row_window":
        return str(metadata.get("window_text") or payload.get("content_for_embedding") or "")
    if chunk_type == "table_row":
        return str(metadata.get("focus_row_text") or payload.get("content_for_embedding") or "")
    if chunk_type in {"table", "table_full"}:
        return str(
            payload.get("raw_content")
            or metadata.get("raw_content")
            or payload.get("content_for_embedding")
            or ""
        )
    return str(payload.get("content_for_embedding") or "")


def strip_row_prefix(label: str) -> str:
    """Loại prefix đánh số ở row label để match focus phrase chuẩn hơn."""

    cleaned = normalize_spaces(fold_text(label))
    cleaned = re.sub(r"^(?:\d+(?:\.\d+)*|[ivxlcdm]+|[a-z][\.\)])\s+", "", cleaned)
    return cleaned


def detect_focus(query: str) -> str:
    """Phân loại nhanh loại focus của query reports."""

    query_fold = fold_text(query)
    if any(token in query_fold for token in [*AMOUNT_KEYWORDS, "bien dong", "phan tram", "%"]):
        return "amount"
    if detect_metric_targets(query):
        return "amount"
    if "don vi" in query_fold:
        return "unit"
    if "phuong phap" in query_fold:
        return "method"
    if any(token in query_fold for token in ["nguyen tac", "ghi nhan", "hach toan", "trinh bay", "ke khai"]):
        return "policy"
    if re.match(r"^\d+(?:\.\d+)+\s+", query.strip()):
        return "numbered_section"
    return "generic"


def extract_focus_phrase(query: str) -> str:
    """Rút focus phrase ngắn hơn để tạo retrieval queries bám row/table."""

    metric_targets = detect_metric_targets(query)
    if metric_targets:
        return metric_targets[0]

    text = normalize_spaces(fold_text(query))
    split_patterns = [
        r"\bso dau ky\b",
        r"\bso cuoi ky\b",
        r"\bdau ky\b",
        r"\bcuoi ky\b",
        r"\bbao nhieu\b",
        r"\bbien dong\b",
        r"\bphan tram\b",
        r"\bgia tri\b",
        r"\bso tien\b",
        r"\btai ngay\b",
        r"\bngay \d{1,2}\b",
        r"\bquy \d\b",
        r"\bduoc lap\b",
        r"\btheo phuong phap\b",
        r"\bdon vi\b",
    ]
    cut = len(text)
    for pattern in split_patterns:
        match = re.search(pattern, text)
        if match:
            cut = min(cut, match.start())
    phrase = text[:cut].strip(" ,.-:;")
    phrase = re.sub(r"\b(co|la|o|tu|den|nam|thang|ngay|tong|so)\b", " ", phrase)
    return normalize_spaces(phrase)


def detect_metric_targets(query: str) -> list[str]:
    """Suy ra metric chuẩn hóa mà user đang hỏi trong report."""

    query_fold = fold_text(query)
    matched: list[str] = []
    for metric_name, aliases in METRIC_ALIASES.items():
        if any(alias in query_fold for alias in aliases):
            matched.append(metric_name)
    return matched


def question_has_opinion_signal(query: str) -> bool:
    """Nhận diện query hỏi về kết luận soát xét/kiểm toán."""

    query_fold = fold_text(query)
    return any(token in query_fold for token in OPINION_KEYWORDS)


def is_toc_like_text(text: str) -> bool:
    """Phát hiện text giống mục lục để phạt rerank."""

    text_fold = fold_text(text)
    return (
        ("noi dung=" in text_fold and "trang=" in text_fold)
        or ("muc luc" in text_fold)
        or ("noi dung" in text_fold and "trang " in text_fold and "|" in text_fold)
    )


def is_toc_like_payload(payload: dict[str, Any]) -> bool:
    """Phát hiện payload giống mục lục hoặc navigation."""

    combined = "\n".join(
        filter(
            None,
            [
                str(payload.get("section_title") or ""),
                str(payload.get("section_subtitle") or ""),
                str(payload.get("note_text") or ""),
                payload_text(payload),
            ],
        )
    )
    return is_toc_like_text(combined)


def infer_filters(question: str) -> ReportQueryFilters:
    """Suy ra các filter runtime cơ bản từ query người dùng."""

    normalized = fold_text(question)
    ticker_match = re.search(r"\b([A-Z]{3,5})\b", question)
    ticker = ticker_match.group(1) if ticker_match else None

    company_name = None
    if ticker is None:
        for alias, mapped_ticker in COMPANY_ALIAS_MAP.items():
            if alias in normalized:
                ticker = mapped_ticker
                company_name = alias
                break
    else:
        for alias, mapped_ticker in COMPANY_ALIAS_MAP.items():
            if mapped_ticker == ticker and alias in normalized:
                company_name = alias
                break

    year_match = re.search(r"\b(20\d{2})\b", question)
    quarter_match = re.search(r"\b(?:q|quy|quý|quarter)\s*([1-4])\b", normalized)

    report_type = next((value for key, value in REPORT_TYPE_KEYWORDS.items() if key in normalized), None)
    report_family = next((value for key, value in REPORT_FAMILY_KEYWORDS.items() if key in normalized), None)
    scope = next((value for key, value in SCOPE_KEYWORDS.items() if key in normalized), None)

    return ReportQueryFilters(
        ticker=ticker,
        company_name=company_name,
        year=int(year_match.group(1)) if year_match else None,
        quarter=int(quarter_match.group(1)) if quarter_match else None,
        report_type=report_type,
        report_family=report_family,
        scope=scope,
    )


def build_retrieval_queries(query: str, rewrite_info: dict[str, Any], filters: ReportQueryFilters) -> list[str]:
    """Tạo nhiều retrieval queries để tăng recall."""

    retrieval_queries = [query]
    for query_text in rewrite_info.get("retrieval_queries") or []:
        normalized_query_text = normalize_spaces(str(query_text))
        if normalized_query_text and normalized_query_text not in retrieval_queries:
            retrieval_queries.append(normalized_query_text)

    normalized_question = str(rewrite_info.get("normalized_question", query))
    focus = detect_focus(normalized_question)
    focus_phrase = extract_focus_phrase(normalized_question)
    metric_targets = detect_metric_targets(normalized_question)
    if focus_phrase and focus_phrase not in retrieval_queries:
        retrieval_queries.append(focus_phrase)

    if filters.ticker:
        ticker_query = f"{filters.ticker} {focus_phrase or normalized_question}".strip()
        if ticker_query not in retrieval_queries:
            retrieval_queries.append(ticker_query)
    if filters.company_name:
        company_query = f"{filters.company_name} {focus_phrase or normalized_question}".strip()
        if company_query not in retrieval_queries:
            retrieval_queries.append(company_query)
    if filters.quarter and filters.year:
        quarter_query = f"quý {filters.quarter} năm {filters.year} {focus_phrase or normalized_question}".strip()
        if quarter_query not in retrieval_queries:
            retrieval_queries.append(quarter_query)

    for metric_name in metric_targets:
        if metric_name not in retrieval_queries:
            retrieval_queries.append(metric_name)
        if filters.ticker and filters.quarter and filters.year:
            metric_query = f"{filters.ticker} quý {filters.quarter} năm {filters.year} {metric_name}"
            if metric_query not in retrieval_queries:
                retrieval_queries.append(metric_query)
        explicit_dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", query)
        for explicit_date in explicit_dates:
            date_query = f"{metric_name} {explicit_date.replace('/', '.')}"
            if date_query not in retrieval_queries:
                retrieval_queries.append(date_query)
        if metric_name in BALANCE_SHEET_METRICS:
            for query_text in (
                f"báo cáo tình hình tài chính {metric_name}",
                f"bảng cân đối kế toán {metric_name}",
            ):
                normalized_query_text = normalize_spaces(query_text)
                if normalized_query_text not in retrieval_queries:
                    retrieval_queries.append(normalized_query_text)
        if metric_name in INCOME_STATEMENT_METRICS:
            for query_text in (
                f"báo cáo kết quả hoạt động {metric_name}",
                f"kết quả kinh doanh {metric_name}",
            ):
                normalized_query_text = normalize_spaces(query_text)
                if normalized_query_text not in retrieval_queries:
                    retrieval_queries.append(normalized_query_text)

    opinion_signal = question_has_opinion_signal(normalized_question) and not metric_targets
    if opinion_signal:
        opinion_queries = [
            "ý kiến soát xét",
            "kết luận của kiểm toán viên",
            "báo cáo soát xét thông tin tài chính giữa niên độ",
            "không thấy có vấn đề gì",
        ]
        if filters.ticker and filters.quarter and filters.year:
            opinion_queries.extend(
                [
                    f"{filters.ticker} quý {filters.quarter} năm {filters.year} ý kiến soát xét",
                    f"{filters.ticker} quý {filters.quarter} năm {filters.year} kết luận của kiểm toán viên",
                ]
            )
        for query_text in opinion_queries:
            normalized_query_text = normalize_spaces(query_text)
            if normalized_query_text and normalized_query_text not in retrieval_queries:
                retrieval_queries.append(normalized_query_text)

    if focus == "amount" and focus_phrase:
        focused_amount_query = f"{focus_phrase} số đầu kỳ số cuối kỳ"
        if focused_amount_query not in retrieval_queries:
            retrieval_queries.append(focused_amount_query)
    elif focus == "unit":
        for query_text in ["Đơn vị tính", "Đơn vị", "unit"]:
            if query_text not in retrieval_queries:
                retrieval_queries.append(query_text)
    elif focus == "method":
        for query_text in ["phương pháp", "theo phương pháp nào"]:
            if query_text not in retrieval_queries:
                retrieval_queries.append(query_text)
    elif focus == "policy":
        policy_queries = ["nguyên tắc ghi nhận", "chính sách kế toán"]
        if focus_phrase:
            policy_queries.extend([focus_phrase, f"nguyên tắc {focus_phrase}", f"ghi nhận {focus_phrase}"])
        for query_text in policy_queries:
            normalized_query_text = normalize_spaces(query_text)
            if normalized_query_text and normalized_query_text not in retrieval_queries:
                retrieval_queries.append(normalized_query_text)

    return retrieval_queries


def build_plan(question: str, rewrite_info: dict[str, Any], filters: ReportQueryFilters) -> ReportQueryPlan:
    """Dựng plan runtime dùng cho retrieval reports."""

    normalized_question = str(rewrite_info.get("normalized_question", normalize_spaces(question)))
    retrieval_queries = build_retrieval_queries(question, rewrite_info, filters)
    return ReportQueryPlan(
        original_question=question,
        normalized_question=normalized_question,
        focus=detect_focus(normalized_question),
        filters=filters,
        retrieval_queries=retrieval_queries,
    )


def build_query_filter(filters: ReportQueryFilters):  # type: ignore[no-untyped-def]
    """Chuyển filter heuristic thành filter object cho Qdrant."""

    filter_payload = filters.as_dict()
    if not filter_payload:
        return None
    try:
        from qdrant_client import models
    except ImportError:  # pragma: no cover - cho phép unit test mock store không cần qdrant-client.
        return filter_payload

    conditions = []
    if filters.ticker:
        conditions.append(models.FieldCondition(key="ticker", match=models.MatchValue(value=filters.ticker.upper())))
    if filters.year is not None:
        conditions.append(models.FieldCondition(key="year", match=models.MatchValue(value=filters.year)))
    if filters.quarter is not None:
        conditions.append(models.FieldCondition(key="quarter", match=models.MatchValue(value=filters.quarter)))
    if filters.scope:
        conditions.append(models.FieldCondition(key="scope", match=models.MatchValue(value=filters.scope)))
    if filters.report_type:
        conditions.append(models.FieldCondition(key="report_type", match=models.MatchValue(value=filters.report_type)))
    if filters.report_family:
        conditions.append(
            models.FieldCondition(key="report_family", match=models.MatchValue(value=filters.report_family))
        )
    return models.Filter(must=conditions)


def merge_candidates(candidate_lists: list[list[ReportCandidate]]) -> list[ReportCandidate]:
    """Merge nhiều batch kết quả retrieval và giữ score cao nhất theo point id."""

    merged: dict[str, ReportCandidate] = {}
    for candidates in candidate_lists:
        for candidate in candidates:
            existing = merged.get(candidate.point_id)
            if existing is None or candidate.qdrant_score > existing.qdrant_score:
                merged[candidate.point_id] = candidate
    return list(merged.values())


def context_block(payload: dict[str, Any]) -> str:
    """Render payload thành khối context text ngắn để synthesis dùng."""

    return (
        f"retrieval_id={payload.get('retrieval_id')} "
        f"type={payload.get('chunk_type')} "
        f"page={payload.get('page')} "
        f"title={payload.get('section_title') or ''} "
        f"subtitle={payload.get('section_subtitle') or ''} "
        f"note={payload.get('note_text') or ''}\n"
        f"{payload_text(payload)}"
    )


def has_explicit_focus_evidence(focus: str, context_items: list[dict[str, Any]]) -> bool:
    """Kiểm tra context đã chứa evidence trực tiếp cho focus hay chưa."""

    hay = "\n".join(context_block(item) for item in context_items)
    hay_fold = fold_text(hay)
    if focus == "unit":
        return "don vi" in hay_fold
    if focus == "method":
        return "phuong phap" in hay_fold
    if focus == "policy":
        return any(
            token in hay_fold
            for token in ["nguyen tac", "ghi nhan", "hach toan", "ke khai", "gia goc", "gia tri thuan"]
        )
    return True


def assemble_contexts(
    store,  # type: ignore[no-untyped-def]
    query: str,
    ranked: list[ReportCandidate],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    """Chọn context pack grounded từ ranked hits."""

    selected: list[dict[str, Any]] = []
    seen_retrieval_ids: set[str] = set()
    opinion_query = question_has_opinion_signal(query) and not detect_metric_targets(query)

    def add_payload(payload: dict[str, Any] | None) -> None:
        if not payload:
            return
        retrieval_id = str(payload.get("retrieval_id") or "")
        if not retrieval_id or retrieval_id in seen_retrieval_ids or len(selected) >= max_items:
            return
        selected.append(payload)
        seen_retrieval_ids.add(retrieval_id)

        if not opinion_query:
            return
        payload_fold = fold_text(payload_text(payload))
        if (
            payload.get("chunk_type") == "text"
            and retrieval_id.endswith("_s0")
            and "ket luan cua kiem toan vien" in payload_fold
        ):
            add_payload(store.get_payload_by_retrieval_id(f"{retrieval_id[:-3]}_s1"))

    focus = detect_focus(query)
    if not ranked:
        return selected

    if focus == "unit":
        best = next(
            (
                candidate.payload
                for candidate in ranked
                if not is_toc_like_payload(candidate.payload)
                and (candidate.payload.get("note_text") or "don vi" in fold_text(payload_text(candidate.payload)))
            ),
            ranked[0].payload,
        )
    elif focus in {"method", "policy"}:
        best = next(
            (
                candidate.payload
                for candidate in ranked
                if not is_toc_like_payload(candidate.payload) and candidate.payload.get("chunk_type") == "text"
            ),
            ranked[0].payload,
        )
    else:
        metric_targets = detect_metric_targets(query)
        if metric_targets:
            from .table_html import table_payload_has_metric

            table_hit = next(
                (
                    candidate.payload
                    for candidate in ranked
                    if str(candidate.payload.get("chunk_type")) == "table"
                    and table_payload_has_metric(candidate.payload, metric_targets[0])
                    and not is_toc_like_payload(candidate.payload)
                ),
                None,
            )
            best = table_hit or ranked[0].payload
        else:
            best = ranked[0].payload
    add_payload(best)

    best_meta = best.get("metadata") or {}
    parent_table_id = best_meta.get("parent_table_id")
    linked_row_id = best_meta.get("linked_row_id")
    linked_window_id = best_meta.get("linked_window_id")

    if focus == "amount":
        if best.get("chunk_type") == "table_row_window" and linked_row_id:
            add_payload(store.get_payload_by_retrieval_id(str(linked_row_id)))
        if best.get("chunk_type") == "table_row" and linked_window_id:
            add_payload(store.get_payload_by_retrieval_id(str(linked_window_id)))
        if parent_table_id:
            add_payload(store.get_parent_table_payload(str(parent_table_id)))
    elif focus == "unit":
        note_table = next(
            (
                candidate.payload
                for candidate in ranked
                if not is_toc_like_payload(candidate.payload)
                and candidate.payload.get("chunk_type") == "table_full"
                and candidate.payload.get("note_text")
            ),
            None,
        )
        add_payload(note_table)
    elif focus in {"method", "policy"}:
        support_table = next(
            (
                candidate.payload
                for candidate in ranked
                if not is_toc_like_payload(candidate.payload) and candidate.payload.get("chunk_type") == "table_full"
            ),
            None,
        )
        add_payload(support_table)

    for candidate in ranked[1:]:
        payload = candidate.payload
        if focus == "amount" and payload.get("chunk_type") in {"table_row", "table_row_window", "table", "table_full"}:
            same_parent = (payload.get("metadata") or {}).get("parent_table_id") == parent_table_id
            if same_parent and len(selected) >= 2:
                continue
        if focus in {"unit", "method", "policy"} and is_toc_like_payload(payload):
            continue
        add_payload(payload)
        if len(selected) >= max_items:
            break
    return selected
