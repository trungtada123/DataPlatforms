"""Synchronous MVP demo for one financial report ingestion + RAG query.

This script intentionally runs worker stages directly instead of requiring
RabbitMQ consumers. It still uses the same production services for Vietstock,
PostgreSQL metadata, MinIO artifacts, chunking, embedding, Qdrant, and query.
Use mock flags when LandingAI, embedding model, or LLM credentials are missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
LEGACY_SRC = PROJECT_ROOT / "src"
for path in (BACKEND_SRC, LEGACY_SRC):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _split_artifact_path(path: str) -> tuple[str, str]:
    bucket, separator, object_key = path.partition("/")
    if not separator or not bucket or not object_key:
        raise ValueError(f"Artifact path must look like bucket/object-key, got: {path!r}")
    return bucket, object_key


def _document_payload(doc_id: str) -> dict[str, Any]:
    from sqlalchemy import select

    from core.database import get_session_factory
    from core.models import FinancialReportDocument

    with get_session_factory().begin() as session:
        document = session.execute(
            select(FinancialReportDocument).where(FinancialReportDocument.doc_id == doc_id)
        ).scalar_one_or_none()
        if document is None:
            raise LookupError(f"Document not found in PostgreSQL: {doc_id}")
        return {
            "doc_id": document.doc_id,
            "ticker": document.ticker,
            "fiscal_year": document.fiscal_year,
            "period": document.period,
            "quarter": document.quarter,
            "report_type": document.report_type,
            "report_family": document.report_family,
            "scope": document.scope,
            "source": document.source,
            "source_url": document.source_url,
            "raw_path": document.raw_path,
            "markdown_path": document.markdown_path,
            "json_path": document.json_path,
            "qdrant_collection": document.qdrant_collection,
            "status": document.status,
            "error_message": document.error_message,
        }


def _print_stage(stage: str, payload: dict[str, Any]) -> None:
    print(json.dumps({"stage": stage, **payload}, ensure_ascii=True, indent=2, default=str))


def discover(args: argparse.Namespace) -> dict[str, Any]:
    from core.database import ensure_schema
    from ingestion.financial_reports.vietstock_source import discover_reports

    ensure_schema()
    reports = discover_reports(
        ticker=args.ticker,
        exchange=args.exchange,
        fiscal_year=args.fiscal_year,
        quarters=[args.quarter],
        report_types=[args.report_type],
        scopes=[args.scope],
        include_annual=False,
        persist=True,
    )
    if not reports:
        raise RuntimeError(
            "No Vietstock report URL was discovered. Check ticker/exchange/year/quarter/report_type/scope."
        )
    selected = reports[0]
    _print_stage("DISCOVERED", {"doc_id": selected["doc_id"], "source_url": selected["source_url"]})
    return selected


def _download_job_from_payload(payload: dict[str, Any]) -> Any:
    from ingestion.financial_reports.rabbitmq_messages import FinancialDownloadJob

    return FinancialDownloadJob.from_dict(payload)


def download(args: argparse.Namespace, payload: dict[str, Any] | None = None) -> Any:
    from ingestion.financial_reports.download_worker import FinancialReportDownloadWorker

    active_payload = payload or _document_payload(args.doc_id)
    job = _download_job_from_payload(active_payload)
    worker = FinancialReportDownloadWorker()
    result = worker._process_job(job, publish_parse_job=lambda next_job: None)
    _print_stage(
        "DOWNLOADED",
        {
            "doc_id": result.doc_id,
            "raw_path": result.raw_path,
            "raw_sha256": result.raw_sha256,
            "bytes_downloaded": result.bytes_downloaded,
        },
    )
    return result.parse_job


def _mock_parse_result(raw_pdf: bytes, *, metadata: dict[str, Any]) -> Any:
    from ingestion.financial_reports.landing_ai import AgenticDocParseResult

    doc_id = str(metadata["doc_id"])
    ticker = str(metadata["ticker"])
    year = int(metadata["fiscal_year"])
    quarter = metadata.get("quarter")
    markdown = f"""# Báo cáo tình hình tài chính

Đơn vị tính: triệu đồng.

| Chỉ tiêu | 30/06/{year} | 31/12/{year - 1} |
| --- | ---: | ---: |
| Tổng tài sản | 1.234.567 | 1.111.111 |
| Cho vay khách hàng | 900.000 | 850.000 |

# Báo cáo kết quả hoạt động kinh doanh

| Chỉ tiêu | Quý {quarter}/{year} | Quý {quarter}/{year - 1} |
| --- | ---: | ---: |
| Lợi nhuận sau thuế | 12.345 | 10.100 |
"""
    json_payload = {
        "doc_id": doc_id,
        "ticker": ticker,
        "fiscal_year": year,
        "quarter": quarter,
        "period": metadata.get("period"),
        "report_type": metadata.get("report_type"),
        "report_family": metadata.get("report_family"),
        "scope": metadata.get("scope"),
        "doc_type": "mock_financial_report",
        "metadata": dict(metadata),
        "pages": [{"page": 1, "markdown": markdown}],
        "chunks": [],
        "tables": [],
        "provider_metadata": {
            "mode": "mock",
            "raw_pdf_sha256": hashlib.sha256(raw_pdf).hexdigest(),
        },
    }
    return AgenticDocParseResult(
        markdown=markdown,
        json_payload=json_payload,
        doc_id=doc_id,
        doc_type="mock_financial_report",
        pages={"count": 1},
        chunks=[],
        tables=[],
        metadata=dict(metadata),
    )


def _parse_job_from_document(doc_id: str) -> Any:
    from ingestion.financial_reports.rabbitmq_messages import FinancialParseJob

    document = _document_payload(doc_id)
    if not document.get("raw_path"):
        raise RuntimeError(f"Document {doc_id} does not have raw_path. Run download first.")
    raw_bucket, raw_object_key = _split_artifact_path(str(document["raw_path"]))
    return FinancialParseJob(
        doc_id=document["doc_id"],
        ticker=document["ticker"],
        fiscal_year=document["fiscal_year"],
        period=document["period"],
        quarter=document["quarter"],
        report_type=document["report_type"],
        report_family=document["report_family"],
        scope=document["scope"],
        source=document["source"],
        source_url=document["source_url"],
        raw_bucket=raw_bucket,
        raw_object_key=raw_object_key,
    )


def parse(args: argparse.Namespace, job: Any | None = None) -> Any:
    from ingestion.financial_reports.parse_worker import FinancialReportParseWorker

    active_job = job or _parse_job_from_document(args.doc_id)
    worker = FinancialReportParseWorker(parser=_mock_parse_result if args.mock_parse else None)
    result = worker._process_job(active_job, publish_chunk_job=lambda next_job: None)
    _print_stage(
        "PARSED",
        {
            "doc_id": result.doc_id,
            "markdown_path": result.markdown_path,
            "json_path": result.json_path,
        },
    )
    return result.chunk_job


def _chunk_job_from_document(doc_id: str) -> Any:
    from ingestion.financial_reports.rabbitmq_messages import FinancialChunkJob

    document = _document_payload(doc_id)
    if not document.get("markdown_path") or not document.get("json_path"):
        raise RuntimeError(f"Document {doc_id} does not have markdown_path/json_path. Run parse first.")
    markdown_bucket, markdown_object_key = _split_artifact_path(str(document["markdown_path"]))
    json_bucket, json_object_key = _split_artifact_path(str(document["json_path"]))
    return FinancialChunkJob(
        doc_id=document["doc_id"],
        ticker=document["ticker"],
        fiscal_year=document["fiscal_year"],
        period=document["period"],
        quarter=document["quarter"],
        report_type=document["report_type"],
        report_family=document["report_family"],
        scope=document["scope"],
        source=document["source"],
        source_url=document["source_url"],
        markdown_bucket=markdown_bucket,
        markdown_object_key=markdown_object_key,
        json_bucket=json_bucket,
        json_object_key=json_object_key,
    )


def chunk(args: argparse.Namespace, job: Any | None = None) -> Any:
    from ingestion.financial_reports.chunk_worker import FinancialReportChunkWorker

    active_job = job or _chunk_job_from_document(args.doc_id)
    worker = FinancialReportChunkWorker(qdrant_collection=args.qdrant_collection)
    result = worker._process_job(active_job, publish_embedding_job=lambda next_job: None)
    _print_stage(
        "CHUNKED",
        {
            "doc_id": result.doc_id,
            "chunks_path": result.chunks_path,
            "chunk_count": result.chunk_count,
            "qdrant_collection": result.embedding_job.qdrant_collection,
        },
    )
    return result.embedding_job


class DemoEmbedder:
    """Deterministic local embedder for demos without model downloads."""

    def __init__(self, *, vector_size: int) -> None:
        self.vector_size = vector_size

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(self.vector_size)]
            norm = sum(value * value for value in values) ** 0.5 or 1.0
            vectors.append([value / norm for value in values])
        return vectors


def _embedding_job_from_document(doc_id: str, qdrant_collection: str) -> Any:
    from ingestion.financial_reports.chunk_worker import build_chunks_object_key
    from ingestion.financial_reports.rabbitmq_messages import FinancialEmbeddingJob

    document = _document_payload(doc_id)
    chunks_bucket = os.getenv("FINANCIAL_REPORTS_PARSED_BUCKET", "financial-reports-parsed").strip()
    chunks_object_key = build_chunks_object_key(
        type(
            "Job",
            (),
            {
                "fiscal_year": document["fiscal_year"],
                "ticker": document["ticker"],
                "doc_id": document["doc_id"],
            },
        )()
    )
    return FinancialEmbeddingJob(
        doc_id=document["doc_id"],
        ticker=document["ticker"],
        fiscal_year=document["fiscal_year"],
        period=document["period"],
        quarter=document["quarter"],
        report_type=document["report_type"],
        report_family=document["report_family"],
        scope=document["scope"],
        source=document["source"],
        source_url=document["source_url"],
        chunks_bucket=chunks_bucket,
        chunks_object_key=chunks_object_key,
        qdrant_collection=qdrant_collection,
    )


def embed(args: argparse.Namespace, job: Any | None = None) -> Any:
    from ingestion.financial_reports.embedding_worker import FinancialReportEmbeddingWorker

    active_job = job or _embedding_job_from_document(args.doc_id, args.qdrant_collection)
    embedder = DemoEmbedder(vector_size=args.mock_vector_size) if args.mock_embed else None
    worker = FinancialReportEmbeddingWorker(embedder=embedder)
    result = worker._process_job(active_job)
    _print_stage(
        "EMBEDDED",
        {
            "doc_id": result.doc_id,
            "collection": result.collection,
            "chunk_count": result.chunk_count,
            "vector_size": result.vector_size,
            "upserted": result.write_report.upserted,
        },
    )
    return result


class DemoSynthesizer:
    """Deterministic answerer for demos without an LLM key."""

    def rewrite_query(self, question: str) -> dict[str, Any]:
        return {
            "normalized_question": question,
            "focus": "amount",
            "retrieval_queries": [question, "tong tai san", "bao cao tinh hinh tai chinh tong tai san"],
        }

    def synthesize(self, *, user_query: str, normalized_question: str, context_items: list[dict[str, Any]]) -> str:
        if not context_items:
            return "Không đủ dữ liệu trong context để kết luận cho câu hỏi này."
        first = context_items[0]
        preview = str(first.get("content_for_embedding") or first.get("raw_content") or "")[:260]
        return (
            f"Demo grounded answer cho query '{user_query}': context phù hợp nhất là {preview}. "
            f"Nguồn: page={first.get('page')}, retrieval_id={first.get('retrieval_id')}."
        )

    def model_name(self) -> str:
        return "mock-demo"


def query(args: argparse.Namespace) -> Any:
    from agents.financial_agent.service import FinancialReportsQueryService
    from config.financial import get_financial_settings

    settings = get_financial_settings()
    settings.qdrant_collection = args.qdrant_collection
    embedder = DemoEmbedder(vector_size=args.mock_vector_size) if args.mock_embed else None
    synthesizer = DemoSynthesizer() if args.mock_llm else None
    service = FinancialReportsQueryService(settings=settings, embedder=embedder, synthesizer=synthesizer)
    response = service.ask(args.query, debug=True)
    _print_stage(
        "QUERY",
        {
            "status": response.status,
            "summary": response.summary,
            "top_k": [
                {
                    "retrieval_id": hit.retrieval_id,
                    "chunk_type": hit.chunk_type,
                    "page": hit.page,
                    "rerank_score": hit.rerank_score,
                    "preview": hit.preview,
                }
                for hit in response.hits[: args.top_k]
            ],
            "limitations": response.limitations,
        },
    )
    return response


def status(args: argparse.Namespace) -> dict[str, Any]:
    document = _document_payload(args.doc_id)
    _print_stage("STATUS", document)
    return document


def run_all(args: argparse.Namespace) -> None:
    discovered = discover(args)
    args.doc_id = discovered["doc_id"]
    parse_job = download(args, discovered)
    chunk_job = parse(args, parse_job)
    embedding_job = chunk(args, chunk_job)
    embed(args, embedding_job)
    status(args)
    query(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=["all", "discover", "download", "parse", "chunk", "embed", "query", "status"],
        help="Stage to run synchronously.",
    )
    parser.add_argument("--ticker", default="ACB")
    parser.add_argument("--exchange", default="HOSE")
    parser.add_argument("--fiscal-year", type=int, default=2025)
    parser.add_argument("--quarter", type=int, default=2)
    parser.add_argument("--report-type", default="Soatxet")
    parser.add_argument("--scope", default="Congtyme")
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--qdrant-collection", default="bctc_chunks")
    parser.add_argument("--query", default="Tổng tài sản của ACB quý 2 năm 2025 là bao nhiêu?")
    parser.add_argument("--top-k", type=_positive_int, default=5)
    parser.add_argument("--mock-parse", action="store_true", help="Use deterministic Markdown/JSON instead of LandingAI.")
    parser.add_argument("--mock-embed", action="store_true", help="Use deterministic vectors instead of SentenceTransformer.")
    parser.add_argument("--mock-llm", action="store_true", help="Use deterministic synthesis instead of Groq/Gemini.")
    parser.add_argument("--mock-vector-size", type=_positive_int, default=1024)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.stage != "discover" and not args.doc_id and args.stage != "all":
        raise SystemExit("--doc-id is required unless stage is discover/all.")

    if args.stage == "all":
        run_all(args)
    elif args.stage == "discover":
        discover(args)
    elif args.stage == "download":
        download(args)
    elif args.stage == "parse":
        parse(args)
    elif args.stage == "chunk":
        chunk(args)
    elif args.stage == "embed":
        embed(args)
    elif args.stage == "query":
        query(args)
    elif args.stage == "status":
        status(args)


if __name__ == "__main__":
    main()