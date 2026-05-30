"""Tests for the financial report chunk worker."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from ingestion.financial_reports.chunk_worker import (
    FinancialReportChunkWorker,
    build_chunks_object_key,
    chunk_to_payload,
)
from ingestion.financial_reports.chunker import Chunk
from ingestion.financial_reports.rabbitmq_messages import FinancialChunkJob


def _sample_chunk_job() -> FinancialChunkJob:
    return FinancialChunkJob(
        doc_id="ACB_2025_Q2_6T_Soatxet_Congtyme",
        ticker="ACB",
        fiscal_year=2025,
        period="6T",
        quarter=2,
        report_type="Soatxet",
        report_family="BCTC",
        scope="Congtyme",
        source="VIETSTOCK",
        source_url="https://static2.vietstock.vn/data/HOSE/2025/BCTC/VN/QUY%202/report.pdf",
        markdown_bucket="financial-reports-parsed",
        markdown_object_key="markdown/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.md",
        json_bucket="financial-reports-parsed",
        json_object_key="json/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json",
    )


def _sample_markdown() -> str:
    return "\n".join(
        [
            "# Bao cao tinh hinh tai chinh",
            "| Chi tieu | 30.6.2025 Trieu VND | 31.12.2024 Trieu VND |",
            "| --- | --- | --- |",
            "| Tong tai san | 911.617.856 | 846.431.405 |",
            "| Cho vay khach hang | 619.850.276 | 569.734.624 |",
        ]
    )


def _sample_json() -> str:
    return json.dumps(
        {
            "doc_id": "ACB_2025_Q2_6T_Soatxet_Congtyme",
            "metadata": {"provider": "agentic-doc"},
            "doc_type": "financial_report",
        }
    )


class ChunkWorkerTests(TestCase):
    def test_build_chunks_object_key_uses_canonical_layout(self) -> None:
        self.assertEqual(
            build_chunks_object_key(_sample_chunk_job()),
            "chunks/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json",
        )

    def test_chunk_to_payload_promotes_runtime_metadata(self) -> None:
        chunk = Chunk(
            chunk_id="chunk-1",
            text="Tong tai san | 2025=100",
            section_title="Bao cao",
            page_start=3,
            page_end=3,
            metadata={
                "retrieval_id": "financial_report_vi_row_1",
                "chunk_type": "table_row",
                "doc_id": "DOC1",
                "ticker": "ACB",
                "fiscal_year": 2025,
                "row_values": {"2025": "100"},
            },
        )

        payload = chunk_to_payload(chunk)

        self.assertEqual(payload["retrieval_id"], "financial_report_vi_row_1")
        self.assertEqual(payload["chunk_type"], "table_row")
        self.assertEqual(payload["ticker"], "ACB")
        self.assertEqual(payload["year"], 2025)
        self.assertEqual(payload["metadata"]["row_values"], {"2025": "100"})

    def test_process_job_chunks_uploads_updates_status_and_builds_embedding_job(self) -> None:
        minio_client = object()
        download = Mock(side_effect=[_sample_markdown().encode("utf-8"), _sample_json().encode("utf-8")])
        ensure_bucket = Mock()
        upload = Mock()
        update_status = Mock()
        add_event = Mock()
        published = []
        worker = FinancialReportChunkWorker(
            chunks_bucket="financial-reports-parsed",
            qdrant_collection="bctc_chunks",
            minio_client=minio_client,
            download_callable=download,
            ensure_bucket_callable=ensure_bucket,
            upload_callable=upload,
            update_status_callable=update_status,
            add_event_callable=add_event,
        )

        result = worker._process_job(_sample_chunk_job(), publish_embedding_job=published.append)

        self.assertEqual(download.call_count, 2)
        ensure_bucket.assert_called_once_with("financial-reports-parsed", client=minio_client)
        upload.assert_called_once()
        self.assertEqual(upload.call_args.args[0], "financial-reports-parsed")
        self.assertEqual(upload.call_args.args[1], "chunks/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json")
        uploaded = json.loads(upload.call_args.args[2].decode("utf-8"))
        chunk_types = {item["chunk_type"] for item in uploaded["chunks"]}
        table_row = next(item for item in uploaded["chunks"] if item["chunk_type"] == "table_row")
        self.assertIn("table_full", chunk_types)
        self.assertIn("table_row", chunk_types)
        self.assertIn("table_row_window", chunk_types)
        self.assertEqual(table_row["metadata"]["row_values"]["30.6.2025 Trieu VND"], "911.617.856")
        update_status.assert_called_once_with("ACB_2025_Q2_6T_Soatxet_Congtyme", "CHUNKED")
        add_event.assert_called_once()
        self.assertEqual(add_event.call_args.kwargs["event_type"], "CHUNK_COMPLETED")
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].chunks_bucket, "financial-reports-parsed")
        self.assertEqual(published[0].qdrant_collection, "bctc_chunks")
        self.assertEqual(result.chunk_count, len(uploaded["chunks"]))

    def test_on_message_publishes_embedding_job_and_acks(self) -> None:
        channel = Mock()
        method = SimpleNamespace(delivery_tag=61)
        worker = FinancialReportChunkWorker(
            chunks_bucket="financial-reports-parsed",
            qdrant_collection="bctc_chunks",
            minio_client=object(),
            download_callable=Mock(side_effect=[_sample_markdown().encode("utf-8"), _sample_json().encode("utf-8")]),
            ensure_bucket_callable=Mock(),
            upload_callable=Mock(),
            update_status_callable=Mock(),
            add_event_callable=Mock(),
            embedding_queue_name="financial_embedding_jobs_test",
        )

        worker._on_message(channel, method, None, _sample_chunk_job().to_json().encode("utf-8"))

        channel.queue_declare.assert_called_once_with(queue="financial_embedding_jobs_test", durable=True)
        channel.basic_publish.assert_called_once()
        payload = json.loads(channel.basic_publish.call_args.kwargs["body"])
        self.assertEqual(payload["doc_id"], "ACB_2025_Q2_6T_Soatxet_Congtyme")
        self.assertEqual(payload["chunks_object_key"], "chunks/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json")
        self.assertEqual(payload["qdrant_collection"], "bctc_chunks")
        channel.basic_ack.assert_called_once_with(delivery_tag=61)

    def test_on_message_marks_failed_and_acks_when_chunking_fails(self) -> None:
        channel = Mock()
        method = SimpleNamespace(delivery_tag=62)
        update_status = Mock()
        add_event = Mock()
        worker = FinancialReportChunkWorker(
            minio_client=object(),
            download_callable=Mock(side_effect=RuntimeError("minio down")),
            ensure_bucket_callable=Mock(),
            upload_callable=Mock(),
            update_status_callable=update_status,
            add_event_callable=add_event,
        )

        worker._on_message(channel, method, None, _sample_chunk_job().to_json().encode("utf-8"))

        update_status.assert_called_once_with(
            "ACB_2025_Q2_6T_Soatxet_Congtyme",
            "FAILED",
            error_message="minio down",
        )
        self.assertEqual(add_event.call_args.kwargs["event_type"], "CHUNK_FAILED")
        channel.basic_publish.assert_not_called()
        channel.basic_ack.assert_called_once_with(delivery_tag=62)