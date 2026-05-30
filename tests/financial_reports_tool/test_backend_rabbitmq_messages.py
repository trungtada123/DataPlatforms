"""Tests for staged RabbitMQ financial ingestion message schemas."""

from __future__ import annotations

import json
from unittest import TestCase
from unittest.mock import patch

from ingestion.financial_reports.rabbitmq_consumer import FinancialIngestMessage
from ingestion.financial_reports.rabbitmq_messages import (
    FinancialChunkJob,
    FinancialDownloadJob,
    FinancialEmbeddingJob,
    FinancialParseJob,
    financial_queue_names,
)


def _base_payload() -> dict[str, object]:
    return {
        "doc_id": "ACB_2025_Q2_6T_Soatxet_Congtyme",
        "ticker": "acb",
        "fiscal_year": 2025,
        "period": "6T",
        "quarter": 2,
        "report_type": "Soatxet",
        "report_family": "BCTC",
        "scope": "Congtyme",
        "source": "VIETSTOCK",
        "source_url": "https://static2.vietstock.vn/data/HOSE/2025/BCTC/VN/QUY%202/report.pdf",
    }


class RabbitMQMessagesTests(TestCase):
    def test_queue_names_use_defaults_and_env_overrides(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                financial_queue_names(),
                {
                    "download": "financial_download_jobs",
                    "parse": "financial_parse_jobs",
                    "chunk": "financial_chunk_jobs",
                    "embedding": "financial_embedding_jobs",
                },
            )

        with patch.dict(
            "os.environ",
            {
                "FINANCIAL_DOWNLOAD_QUEUE": "custom_download",
                "FINANCIAL_PARSE_QUEUE": "custom_parse",
                "FINANCIAL_CHUNK_QUEUE": "custom_chunk",
                "FINANCIAL_EMBEDDING_QUEUE": "custom_embedding",
            },
            clear=True,
        ):
            self.assertEqual(
                financial_queue_names(),
                {
                    "download": "custom_download",
                    "parse": "custom_parse",
                    "chunk": "custom_chunk",
                    "embedding": "custom_embedding",
                },
            )

    def test_download_job_round_trips_json(self) -> None:
        job = FinancialDownloadJob.from_dict(_base_payload())

        self.assertEqual(job.ticker, "ACB")
        self.assertEqual(job.queue_name, "financial_download_jobs")
        decoded = FinancialDownloadJob.from_json(job.to_json())
        self.assertEqual(decoded, job)

    def test_parse_job_requires_raw_artifact_fields(self) -> None:
        payload = {
            **_base_payload(),
            "raw_bucket": "financial-reports-raw",
            "raw_object_key": "raw/2025/ACB/report.pdf",
        }

        job = FinancialParseJob.from_json(json.dumps(payload))

        self.assertEqual(job.raw_bucket, "financial-reports-raw")
        self.assertEqual(job.raw_object_key, "raw/2025/ACB/report.pdf")

    def test_chunk_job_requires_markdown_and_json_artifact_fields(self) -> None:
        payload = {
            **_base_payload(),
            "markdown_bucket": "financial-reports-parsed",
            "markdown_object_key": "markdown/2025/ACB/report.md",
            "json_bucket": "financial-reports-parsed",
            "json_object_key": "json/2025/ACB/report.json",
        }

        job = FinancialChunkJob.from_dict(payload)

        self.assertEqual(job.markdown_object_key, "markdown/2025/ACB/report.md")
        self.assertEqual(job.json_object_key, "json/2025/ACB/report.json")

    def test_embedding_job_requires_chunks_and_qdrant_fields(self) -> None:
        payload = {
            **_base_payload(),
            "chunks_bucket": "financial-reports-parsed",
            "chunks_object_key": "chunks/2025/ACB/report.json",
            "qdrant_collection": "bctc_chunks",
        }

        job = FinancialEmbeddingJob.from_dict(payload)

        self.assertEqual(job.chunks_bucket, "financial-reports-parsed")
        self.assertEqual(job.qdrant_collection, "bctc_chunks")

    def test_missing_common_field_raises_clear_error(self) -> None:
        payload = _base_payload()
        payload.pop("source_url")

        with self.assertRaisesRegex(ValueError, "Missing required field\\(s\\): source_url"):
            FinancialDownloadJob.from_dict(payload)

    def test_missing_stage_field_raises_clear_error(self) -> None:
        payload = {
            **_base_payload(),
            "raw_bucket": "financial-reports-raw",
        }

        with self.assertRaisesRegex(ValueError, "Missing required field\\(s\\): raw_object_key"):
            FinancialParseJob.from_dict(payload)

    def test_invalid_json_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid RabbitMQ job JSON"):
            FinancialDownloadJob.from_json("{")

    def test_legacy_financial_ingest_message_still_parses(self) -> None:
        message = FinancialIngestMessage.from_dict(
            {
                "doc_id": "legacy_doc",
                "ticker": "acb",
                "period": "Q2",
                "fiscal_year": 2025,
                "source": "VIETSTOCK",
                "pdf_path": "D:/tmp/report.pdf",
            }
        )

        self.assertEqual(message.doc_id, "legacy_doc")
        self.assertEqual(message.ticker, "ACB")
        self.assertEqual(message.pdf_path, "D:/tmp/report.pdf")