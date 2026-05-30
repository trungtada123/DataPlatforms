"""Tests for the financial report embedding worker and Qdrant setup."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from ingestion.financial_reports.embedding_worker import (
    FinancialReportEmbeddingWorker,
    chunk_payload_to_chunk,
)
from ingestion.financial_reports.qdrant_setup import PAYLOAD_INDEX_FIELDS, ensure_qdrant_collection
from ingestion.financial_reports.rabbitmq_messages import FinancialEmbeddingJob


def _sample_embedding_job() -> FinancialEmbeddingJob:
    return FinancialEmbeddingJob(
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
        chunks_bucket="financial-reports-parsed",
        chunks_object_key="chunks/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json",
        qdrant_collection="bctc_chunks",
    )


def _sample_chunk_payload() -> dict[str, object]:
    return {
        "chunk_id": "chunk-1",
        "retrieval_id": "financial_report_vi_table_1_row_0000",
        "chunk_type": "table_row",
        "doc_id": "ACB_2025_Q2_6T_Soatxet_Congtyme",
        "ticker": "ACB",
        "year": 2025,
        "fiscal_year": 2025,
        "quarter": 2,
        "period": "6T",
        "scope": "Congtyme",
        "report_type": "Soatxet",
        "report_family": "BCTC",
        "page": 6,
        "section_title": "Bao cao tinh hinh tai chinh",
        "raw_content": "Tong tai san | 911.617.856",
        "content_for_embedding": "Tong tai san | 30.6.2025 Trieu VND=911.617.856",
        "source_ids": ["table-1", "row-1"],
        "metadata": {
            "row_label": "Tong tai san",
            "row_values": {"30.6.2025 Trieu VND": "911.617.856"},
            "parent_table_id": "table-1",
        },
    }


class _FakeEmbedder:
    def encode_documents(self, texts):  # type: ignore[no-untyped-def]
        return [[0.1, 0.2, 0.3] for _ in texts]


class EmbeddingWorkerTests(TestCase):
    def test_chunk_payload_to_chunk_promotes_top_level_metadata(self) -> None:
        chunk = chunk_payload_to_chunk(_sample_chunk_payload())

        self.assertEqual(chunk.chunk_id, "chunk-1")
        self.assertEqual(chunk.text, "Tong tai san | 30.6.2025 Trieu VND=911.617.856")
        self.assertEqual(chunk.page_start, 6)
        self.assertEqual(chunk.metadata["ticker"], "ACB")
        self.assertEqual(chunk.metadata["row_values"], {"30.6.2025 Trieu VND": "911.617.856"})

    def test_ensure_qdrant_collection_creates_collection_and_payload_indexes(self) -> None:
        client = Mock()
        client.collection_exists.return_value = False

        ensure_qdrant_collection(client, collection_name="bctc_chunks", vector_size=3)

        client.create_collection.assert_called_once()
        self.assertEqual(client.create_payload_index.call_count, len(PAYLOAD_INDEX_FIELDS))

    def test_process_job_embeds_ensures_collection_upserts_and_updates_status(self) -> None:
        minio_client = object()
        fake_store = SimpleNamespace(client=Mock())
        download = Mock(return_value=json.dumps({"chunks": [_sample_chunk_payload()]}).encode("utf-8"))
        ensure_collection = Mock()
        update_status = Mock()
        update_paths = Mock()
        add_event = Mock()
        worker = FinancialReportEmbeddingWorker(
            minio_client=minio_client,
            qdrant_store=fake_store,
            embedder=_FakeEmbedder(),
            download_callable=download,
            ensure_collection_callable=ensure_collection,
            update_status_callable=update_status,
            update_paths_callable=update_paths,
            add_event_callable=add_event,
        )

        with patch("qdrant_client.models.PointStruct") as point_struct:
            point_struct.side_effect = lambda **kwargs: kwargs
            result = worker._process_job(_sample_embedding_job())

        download.assert_called_once_with(
            "financial-reports-parsed",
            "chunks/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json",
            client=minio_client,
        )
        ensure_collection.assert_called_once_with(
            fake_store.client,
            collection_name="bctc_chunks",
            vector_size=3,
        )
        fake_store.client.upsert.assert_called_once()
        payload = fake_store.client.upsert.call_args.kwargs["points"][0]["payload"]
        self.assertEqual(payload["retrieval_id"], "financial_report_vi_table_1_row_0000")
        self.assertEqual(payload["ticker"], "ACB")
        self.assertEqual(payload["year"], 2025)
        self.assertEqual(payload["chunk_type"], "table_row")
        self.assertEqual(payload["metadata"]["row_values"], {"30.6.2025 Trieu VND": "911.617.856"})
        update_paths.assert_called_once_with(
            "ACB_2025_Q2_6T_Soatxet_Congtyme",
            qdrant_collection="bctc_chunks",
        )
        update_status.assert_called_once_with("ACB_2025_Q2_6T_Soatxet_Congtyme", "EMBEDDED")
        self.assertEqual(add_event.call_args.kwargs["event_type"], "EMBEDDING_COMPLETED")
        self.assertEqual(result.vector_size, 3)

    def test_on_message_marks_failed_and_acks_when_embedding_fails(self) -> None:
        channel = Mock()
        method = SimpleNamespace(delivery_tag=71)
        update_status = Mock()
        add_event = Mock()
        worker = FinancialReportEmbeddingWorker(
            minio_client=object(),
            qdrant_store=SimpleNamespace(client=Mock()),
            download_callable=Mock(side_effect=RuntimeError("chunks missing")),
            update_status_callable=update_status,
            add_event_callable=add_event,
        )

        worker._on_message(channel, method, None, _sample_embedding_job().to_json().encode("utf-8"))

        update_status.assert_called_once_with(
            "ACB_2025_Q2_6T_Soatxet_Congtyme",
            "FAILED",
            error_message="chunks missing",
        )
        self.assertEqual(add_event.call_args.kwargs["event_type"], "EMBEDDING_FAILED")
        channel.basic_ack.assert_called_once_with(delivery_tag=71) 