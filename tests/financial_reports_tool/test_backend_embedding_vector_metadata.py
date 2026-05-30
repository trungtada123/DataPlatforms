"""Tests for embedding/vector-write/metadata storage adapters."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from ingestion.financial_reports.chunker import Chunk
from ingestion.financial_reports.embedder import EmbeddedChunk, embed_chunks
from ingestion.financial_reports.markdown_parser import parse_landingai_output
from ingestion.financial_reports.metadata_storage import save_document_metadata, save_parsed_markdown
from ingestion.financial_reports.vector_writer import write_chunks


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "landingai_output_mock.json"


def _sample_chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id="doc_chunk_0001",
            text="Doanh thu thuan tang truong on dinh.",
            section_title="Tong quan",
            page_start=1,
            page_end=1,
            metadata={"chunk_type": "text", "doc_id": "ACB_Q2_2024"},
        ),
        Chunk(
            chunk_id="doc_chunk_0002",
            text="Loi nhuan sau thue dat 320.",
            section_title="Bang ket qua kinh doanh",
            page_start=1,
            page_end=1,
            metadata={"chunk_type": "table_fragment", "doc_id": "ACB_Q2_2024"},
        ),
    ]


class BackendEmbeddingVectorMetadataTests(TestCase):
    """Validate new ingestion adapters with mocked runtime dependencies."""

    def test_embed_chunks_with_mock_embedder(self) -> None:
        mock_embedder = Mock()
        mock_embedder.encode_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]

        output = embed_chunks(_sample_chunks(), embedder=mock_embedder, batch_size=8)

        self.assertEqual(len(output), 2)
        self.assertIsInstance(output[0], EmbeddedChunk)
        self.assertEqual(output[0].chunk_id, "doc_chunk_0001")
        self.assertEqual(output[0].vector, [0.1, 0.2])
        mock_embedder.encode_documents.assert_called_once()

    def test_embed_chunks_detects_vector_count_mismatch(self) -> None:
        mock_embedder = Mock()
        mock_embedder.encode_documents.return_value = [[0.1, 0.2]]

        with self.assertRaises(RuntimeError):
            embed_chunks(_sample_chunks(), embedder=mock_embedder, batch_size=8)

    def test_write_chunks_calls_store_upsert_idempotently(self) -> None:
        fake_client = Mock()
        fake_store = Mock()
        fake_store.client = fake_client

        embedded = [
            EmbeddedChunk(
                chunk_id="doc_chunk_0001",
                text="abc",
                vector=[0.1, 0.2, 0.3],
                section_title="S1",
                page_start=1,
                page_end=1,
                metadata={
                    "retrieval_id": "financial_report_vi_doc_chunk_0001",
                    "doc_id": "ACB_Q2_2025",
                    "ticker": "ACB",
                    "fiscal_year": 2025,
                    "quarter": 2,
                    "period": "6T",
                    "scope": "Congtyme",
                    "report_type": "Soatxet",
                    "report_family": "BCTC",
                    "page": 7,
                    "chunk_type": "table_row",
                    "raw_content": "Tong tai san | 911.617.856",
                    "content_for_embedding": "Tong tai san | 30.6.2025=911.617.856",
                    "source_ids": ["table-1", "row-1"],
                    "row_label": "Tong tai san",
                    "row_values": {"30.6.2025": "911.617.856"},
                    "parent_table_id": "table-1",
                },
            )
        ]

        with patch("qdrant_client.models.PointStruct") as point_struct:
            point_struct.side_effect = lambda **kwargs: kwargs
            report = write_chunks("bctc_chunks", embedded, store=fake_store)

        fake_client.upsert.assert_called_once()
        point_payload = fake_client.upsert.call_args.kwargs["points"][0]["payload"]
        self.assertEqual(point_payload["retrieval_id"], "financial_report_vi_doc_chunk_0001")
        self.assertEqual(point_payload["ticker"], "ACB")
        self.assertEqual(point_payload["year"], 2025)
        self.assertEqual(point_payload["chunk_type"], "table_row")
        self.assertEqual(point_payload["page"], 7)
        self.assertEqual(point_payload["raw_content"], "Tong tai san | 911.617.856")
        self.assertEqual(point_payload["metadata"]["row_values"], {"30.6.2025": "911.617.856"})
        self.assertEqual(point_payload["source_ids"], ["table-1", "row-1"])
        self.assertEqual(report.collection, "bctc_chunks")
        self.assertEqual(report.attempted, 1)
        self.assertEqual(report.upserted, 1)
        self.assertEqual(report.failed, 0)
        self.assertEqual(len(report.point_ids), 1)

    def test_save_document_metadata_to_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict("os.environ", {"FINANCIAL_REPORTS_PARSED_OUTPUT_DIR": tmp_dir}, clear=False):
                result = save_document_metadata(
                    doc_id="DOC_META_01",
                    metadata={"ticker": "ACB"},
                    extra={"source": "test"},
                )

            file_path = Path(result.location)
            self.assertTrue(file_path.exists())
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["doc_id"], "DOC_META_01")
            self.assertEqual(payload["metadata"]["ticker"], "ACB")

    def test_save_parsed_markdown_fallback_filesystem_when_minio_unavailable(self) -> None:
        raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        parsed = parse_landingai_output(raw)

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ",
                {
                    "FINANCIAL_REPORTS_PARSED_OUTPUT_DIR": tmp_dir,
                    "MINIO_ENDPOINT": "",
                    "MINIO_ACCESS_KEY": "",
                    "MINIO_SECRET_KEY": "",
                },
                clear=False,
            ):
                result = save_parsed_markdown(parsed, prefer_minio=True)

            self.assertEqual(result.storage_backend, "filesystem")
            file_path = Path(result.location)
            self.assertTrue(file_path.exists())
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["doc_id"], "ACB_Q2_2024")

    def test_save_parsed_markdown_to_minio_when_client_available(self) -> None:
        raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        parsed = parse_landingai_output(raw)

        mock_client = Mock()
        with patch.dict(
            "os.environ",
            {
                "MINIO_ENDPOINT": "minio:9000",
                "MINIO_ACCESS_KEY": "access",
                "MINIO_SECRET_KEY": "secret",
                "MINIO_SECURE": "false",
                "FINANCIAL_REPORTS_MINIO_BUCKET": "financial-reports-parsed",
                "FINANCIAL_REPORTS_MINIO_PREFIX": "parsed",
            },
            clear=False,
        ), patch("ingestion.financial_reports.metadata_storage.get_minio_client", return_value=mock_client), patch(
            "ingestion.financial_reports.metadata_storage.ensure_bucket"
        ) as ensure_bucket_mock, patch(
            "ingestion.financial_reports.metadata_storage.upload_bytes"
        ) as upload_bytes_mock:
            result = save_parsed_markdown(parsed, prefer_minio=True)

        self.assertEqual(result.storage_backend, "minio")
        ensure_bucket_mock.assert_called_once()
        upload_bytes_mock.assert_called_once()
