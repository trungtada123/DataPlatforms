"""Financial reports ingestion package exports.

The package is intentionally lazy: Airflow imports lightweight modules such as
``vietstock_source`` and should not load LandingAI, Qdrant, or LLM dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "Chunk": "chunker",
    "chunk_document": "chunker",
    "FinancialChunkResult": "chunk_worker",
    "FinancialReportChunkWorker": "chunk_worker",
    "build_chunks_object_key": "chunk_worker",
    "chunk_to_payload": "chunk_worker",
    "VALID_DOCUMENT_STATUSES": "document_repository",
    "add_ingest_event": "document_repository",
    "create_or_update_document": "document_repository",
    "get_document_by_doc_id": "document_repository",
    "update_document_paths": "document_repository",
    "update_document_status": "document_repository",
    "FinancialDownloadResult": "download_worker",
    "FinancialReportDownloadWorker": "download_worker",
    "build_raw_object_key": "download_worker",
    "EmbeddedChunk": "embedder",
    "embed_chunks": "embedder",
    "FinancialEmbeddingResult": "embedding_worker",
    "FinancialReportEmbeddingWorker": "embedding_worker",
    "chunk_payload_to_chunk": "embedding_worker",
    "AgenticDocParseResult": "landing_ai",
    "LandingAIParseError": "landing_ai",
    "LandingAIResult": "landing_ai",
    "ocr_pdf": "landing_ai",
    "parse_pdf_with_agentic_doc": "landing_ai",
    "ParsedDocument": "markdown_parser",
    "ParsedSection": "markdown_parser",
    "ParsedTable": "markdown_parser",
    "parse_landingai_output": "markdown_parser",
    "MetadataSaveResult": "metadata_storage",
    "save_document_metadata": "metadata_storage",
    "save_parsed_markdown": "metadata_storage",
    "FinancialParseResult": "parse_worker",
    "FinancialReportParseWorker": "parse_worker",
    "build_json_object_key": "parse_worker",
    "build_markdown_object_key": "parse_worker",
    "PAYLOAD_INDEX_FIELDS": "qdrant_setup",
    "ensure_qdrant_collection": "qdrant_setup",
    "FinancialIngestConsumer": "rabbitmq_consumer",
    "FinancialChunkJob": "rabbitmq_messages",
    "FinancialDownloadJob": "rabbitmq_messages",
    "FinancialEmbeddingJob": "rabbitmq_messages",
    "FinancialParseJob": "rabbitmq_messages",
    "financial_queue_names": "rabbitmq_messages",
    "WriteReport": "vector_writer",
    "build_qdrant_payload": "vector_writer",
    "write_chunks": "vector_writer",
    "VIETSTOCK_SOURCE": "vietstock_source",
    "VietstockReportCandidate": "vietstock_source",
    "VietstockSourceError": "vietstock_source",
    "build_bctc_url": "vietstock_source",
    "build_bctn_url": "vietstock_source",
    "check_url": "vietstock_source",
    "discover_reports": "vietstock_source",
    "download_pdf_bytes": "vietstock_source",
    "generate_candidate_urls": "vietstock_source",
}

__all__ = sorted(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value
