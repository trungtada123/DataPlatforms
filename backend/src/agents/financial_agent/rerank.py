"""Heuristic rerank cho financial reports runtime."""

from __future__ import annotations

import re

from .contracts import get_profile
from .contracts import ReportCandidate
from .retrieval import (
    BALANCE_SHEET_METRICS,
    INCOME_STATEMENT_METRICS,
    detect_focus,
    detect_metric_targets,
    extract_focus_phrase,
    fold_text,
    is_toc_like_payload,
    payload_text,
    question_has_opinion_signal,
    strip_row_prefix,
    tokenize,
)


def rerank_candidate(query: str, candidate: ReportCandidate) -> None:
    """Chấm lại candidate sau bước vector retrieval."""

    profile = get_profile("financial_report_vi")
    scoring = profile.scoring
    payload = candidate.payload
    text = payload_text(payload)
    hay = fold_text(
        "\n".join(
            filter(
                None,
                [
                    str(payload.get("section_title") or ""),
                    str(payload.get("section_subtitle") or ""),
                    str(payload.get("note_text") or ""),
                    text,
                ],
            )
        )
    )
    query_tokens = [token for token in tokenize(query) if len(token) > 1]
    matched = [token for token in query_tokens if token in hay]

    score = candidate.qdrant_score * 10.0
    why = [f"qdrant={candidate.qdrant_score:.4f}"]
    if query_tokens:
        coverage = len(set(matched)) / len(set(query_tokens))
        score += coverage * scoring.retrieval_token_coverage_weight
        why.append(f"token_coverage={coverage:.2f}")

    focus = detect_focus(query)
    focus_phrase = extract_focus_phrase(query)
    query_fold = fold_text(query)
    chunk_type = str(payload.get("chunk_type") or "")
    metadata = payload.get("metadata") or {}
    row_label = fold_text(str(metadata.get("row_label") or ""))
    row_label_core = strip_row_prefix(str(metadata.get("row_label") or ""))
    toc_like = is_toc_like_payload(payload)
    metric_targets = detect_metric_targets(query)
    opinion_query = question_has_opinion_signal(query) and not metric_targets

    if focus == "amount":
        if metric_targets:
            title_fold = fold_text(str(payload.get("section_title") or ""))
            subtitle_fold = fold_text(str(payload.get("section_subtitle") or ""))
            row_values = metadata.get("row_values") or {}
            row_value_keys = {fold_text(str(key)) for key in row_values.keys()} if isinstance(row_values, dict) else set()
            for metric_name in metric_targets:
                if row_label_core == metric_name:
                    score += 9.0
                    why.append("metric_row_exact_bonus=9.0")
                elif metric_name in row_label_core:
                    score += 7.0
                    why.append("metric_row_partial_bonus=7.0")
                elif metric_name in hay:
                    score += 3.5
                    why.append("metric_context_bonus=3.5")
                elif chunk_type in {"table_row", "table_row_window"}:
                    score -= 2.5
                    why.append("metric_row_miss_penalty=-2.5")

                if metric_name in BALANCE_SHEET_METRICS:
                    if any(token in title_fold for token in ("bao cao tinh hinh tai chinh", "bang can doi ke toan")):
                        score += 4.0
                        why.append("balance_sheet_title_bonus=4.0")
                    if any(token in subtitle_fold for token in ("tai ngay", "30 thang 6 nam 2025", "30/06/2025")):
                        score += 2.5
                        why.append("balance_sheet_subtitle_bonus=2.5")
                    if any(token in title_fold for token in ("muc do tap trung", "rui ro", "ngoai bang", "dia ly")):
                        score -= 6.0
                        why.append("balance_sheet_noise_penalty=-6.0")
                    if "tom tat cac chinh sach ke toan" in title_fold:
                        score -= 6.5
                        why.append("policy_table_penalty=-6.5")
                    if {"usd", "vang", "eur", "jpy", "aud", "cad", "khac", "tong cong"} & row_value_keys:
                        score -= 5.5
                        why.append("currency_breakdown_penalty=-5.5")
                    if any("trieu vnd" in key for key in row_value_keys):
                        score += 3.0
                        why.append("date_value_columns_bonus=3.0")
                if metric_name in INCOME_STATEMENT_METRICS:
                    if any(token in title_fold for token in ("bao cao ket qua hoat dong", "ket qua kinh doanh")):
                        score += 4.0
                        why.append("income_statement_title_bonus=4.0")

        if focus_phrase:
            if chunk_type in {"table_row", "table_row_window"}:
                if row_label_core == focus_phrase:
                    score += scoring.retrieval_exact_row_bonus
                    why.append(f"focus_row_exact_bonus={scoring.retrieval_exact_row_bonus:.1f}")
                elif row_label_core.startswith(focus_phrase + " "):
                    score += scoring.retrieval_row_prefix_bonus
                    why.append(f"focus_row_prefix_bonus={scoring.retrieval_row_prefix_bonus:.1f}")
                    if row_label_core.endswith(" khac"):
                        score -= 1.0
                        why.append("focus_row_suffix_khac_penalty=-1.0")
                elif focus_phrase in row_label:
                    score += scoring.retrieval_row_partial_bonus
                    why.append(f"focus_row_partial_bonus={scoring.retrieval_row_partial_bonus:.1f}")
                elif focus_phrase in hay:
                    score += scoring.retrieval_context_only_bonus
                    why.append(f"focus_context_only_bonus={scoring.retrieval_context_only_bonus:.1f}")
                else:
                    score -= scoring.retrieval_focus_row_miss_penalty
                    why.append(f"focus_row_miss_penalty=-{scoring.retrieval_focus_row_miss_penalty:.1f}")
            elif focus_phrase in hay:
                score += 3.0
                why.append("focus_phrase_bonus=3.0")
        if chunk_type == "table_row_window":
            score += scoring.retrieval_table_row_window_bonus
            why.append(f"table_row_window_bonus={scoring.retrieval_table_row_window_bonus:.1f}")
        elif chunk_type == "table_row":
            score += scoring.retrieval_table_row_bonus
            why.append(f"table_row_bonus={scoring.retrieval_table_row_bonus:.1f}")
        elif chunk_type == "table_full":
            score += scoring.retrieval_table_full_context_bonus
            why.append(f"table_full_context_bonus={scoring.retrieval_table_full_context_bonus:.1f}")
        else:
            score -= scoring.retrieval_text_penalty
            why.append(f"text_penalty=-{scoring.retrieval_text_penalty:.1f}")
        if metadata.get("row_code"):
            score += scoring.retrieval_row_code_bonus
            why.append(f"row_code_bonus={scoring.retrieval_row_code_bonus:.1f}")
        if re.search(r"\d[\d\.,]{5,}", text):
            score += scoring.retrieval_numeric_value_bonus
            why.append(f"numeric_value_bonus={scoring.retrieval_numeric_value_bonus:.1f}")
        if any(token in fold_text(query) for token in ["phan tram", "%", "bien dong"]):
            number_count = len(re.findall(r"\d[\d\.,]{2,}", text))
            if number_count >= 2:
                score += scoring.retrieval_delta_ready_bonus
                why.append(f"delta_ready_bonus={scoring.retrieval_delta_ready_bonus:.1f}")
    elif focus == "unit":
        if payload.get("note_text"):
            score += scoring.retrieval_unit_note_bonus
            why.append(f"note_bonus={scoring.retrieval_unit_note_bonus:.1f}")
        if "don vi" in hay:
            score += scoring.retrieval_unit_phrase_bonus
            why.append(f"unit_phrase_bonus={scoring.retrieval_unit_phrase_bonus:.1f}")
        if chunk_type == "text":
            score += scoring.retrieval_unit_text_bonus
            why.append(f"unit_text_bonus={scoring.retrieval_unit_text_bonus:.1f}")
        if chunk_type in {"table_row", "table_row_window"}:
            score -= scoring.retrieval_unit_row_penalty
            why.append(f"unit_row_penalty=-{scoring.retrieval_unit_row_penalty:.1f}")
    elif focus == "method":
        if "phuong phap" in hay:
            score += scoring.retrieval_method_phrase_bonus
            why.append(f"method_bonus={scoring.retrieval_method_phrase_bonus:.1f}")
        if chunk_type == "text":
            score += scoring.retrieval_method_text_bonus
            why.append(f"method_text_bonus={scoring.retrieval_method_text_bonus:.1f}")
        if chunk_type in {"table_row", "table_row_window"}:
            score -= scoring.retrieval_method_row_penalty
            why.append(f"method_row_penalty=-{scoring.retrieval_method_row_penalty:.1f}")
    elif focus == "policy":
        if any(token in hay for token in ["nguyen tac", "ghi nhan", "hach toan", "ke khai", "gia goc", "gia tri thuan"]):
            score += scoring.retrieval_policy_phrase_bonus
            why.append(f"policy_phrase_bonus={scoring.retrieval_policy_phrase_bonus:.1f}")
        if chunk_type == "text":
            score += scoring.retrieval_policy_text_bonus
            why.append(f"policy_text_bonus={scoring.retrieval_policy_text_bonus:.1f}")
        if chunk_type in {"table_row", "table_row_window"}:
            score -= scoring.retrieval_policy_row_penalty
            why.append(f"policy_row_penalty=-{scoring.retrieval_policy_row_penalty:.1f}")
    elif focus == "numbered_section":
        if chunk_type == "text":
            score += scoring.retrieval_numbered_section_text_bonus
            why.append(f"numbered_text_bonus={scoring.retrieval_numbered_section_text_bonus:.1f}")

    if opinion_query:
        if chunk_type == "text" and any(
            token in hay
            for token in (
                "ket luan cua kiem toan vien",
                "khong thay co van de gi",
                "bao cao soat xet thong tin tai chinh giua nien do",
                "chung toi da soat xet bao cao tai chinh",
            )
        ):
            score += 7.0
            why.append("opinion_text_bonus=7.0")
        elif chunk_type in {"table_row", "table_row_window", "table_full"}:
            score -= 3.0
            why.append("opinion_table_penalty=-3.0")

    if focus in {"unit", "method", "policy"} and toc_like:
        score -= scoring.retrieval_toc_penalty
        why.append(f"toc_penalty=-{scoring.retrieval_toc_penalty:.1f}")

    title = fold_text(str(payload.get("section_title") or ""))
    if title and fold_text(query) == title and chunk_type == "table_full":
        score += scoring.retrieval_exact_table_title_bonus
        why.append(f"exact_table_title_bonus={scoring.retrieval_exact_table_title_bonus:.1f}")

    candidate.rerank_score = score
    candidate.why = why
