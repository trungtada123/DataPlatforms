"""Tests for rule-based LandingAI parser and chunker."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase

from ingestion.financial_reports.chunker import chunk_document
from ingestion.financial_reports.markdown_parser import ParsedDocument, parse_landingai_output


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "landingai_output_mock.json"


class BackendMarkdownParserChunkerTests(TestCase):
    """Validate parser/chunker outputs and deterministic chunk IDs."""

    def _load_fixture(self) -> dict:
        return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_parse_landingai_output_returns_parsed_document(self) -> None:
        raw = self._load_fixture()
        parsed = parse_landingai_output(raw)

        self.assertIsInstance(parsed, ParsedDocument)
        self.assertEqual(parsed.doc_id, "ACB_Q2_2024")
        self.assertEqual(parsed.metadata["ticker"], "ACB")
        self.assertEqual(parsed.pages, [1, 2])
        self.assertGreaterEqual(len(parsed.sections), 2)
        self.assertGreaterEqual(len(parsed.tables), 1)
        self.assertTrue(any(section.title.lower().startswith("tong quan") for section in parsed.sections))

    def test_chunk_document_returns_valid_chunks(self) -> None:
        parsed = parse_landingai_output(self._load_fixture())
        chunks = chunk_document(parsed, target_tokens=20, overlap=5)

        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(chunk.chunk_id for chunk in chunks))
        self.assertTrue(all(chunk.text.strip() for chunk in chunks))
        self.assertTrue(
            any(chunk.metadata.get("chunk_type") in {"table_full", "table_row", "table_row_window"} for chunk in chunks)
        )
        self.assertTrue(any(chunk.metadata.get("chunk_type") == "text" for chunk in chunks))

    def test_chunk_document_emits_runtime_table_profiles(self) -> None:
        parsed = parse_landingai_output(
            {
                "doc_id": "ACB_Q2_2025",
                "metadata": {
                    "doc_id": "ACB_Q2_2025",
                    "ticker": "ACB",
                    "fiscal_year": 2025,
                    "quarter": 2,
                    "period": "6T",
                    "report_type": "Soatxet",
                    "report_family": "BCTC",
                    "scope": "Congtyme",
                },
                "markdown": "\n".join(
                    [
                        "# Bao cao tinh hinh tai chinh",
                        "| Chi tieu | 30.6.2025 Trieu VND | 31.12.2024 Trieu VND |",
                        "| --- | --- | --- |",
                        "| Tong tai san | 911.617.856 | 846.431.405 |",
                        "| Cho vay khach hang | 619.850.276 | 569.734.624 |",
                    ]
                ),
            }
        )

        chunks = chunk_document(parsed, target_tokens=64, overlap=8)
        types = {chunk.metadata.get("chunk_type") for chunk in chunks}
        row_chunk = next(chunk for chunk in chunks if chunk.metadata.get("chunk_type") == "table_row")
        window_chunk = next(chunk for chunk in chunks if chunk.metadata.get("chunk_type") == "table_row_window")
        full_chunk = next(chunk for chunk in chunks if chunk.metadata.get("chunk_type") == "table_full")

        self.assertIn("table_full", types)
        self.assertIn("table_row", types)
        self.assertIn("table_row_window", types)
        self.assertEqual(row_chunk.metadata["row_label"], "Tong tai san")
        self.assertEqual(row_chunk.metadata["row_values"]["30.6.2025 Trieu VND"], "911.617.856")
        self.assertEqual(row_chunk.metadata["ticker"], "ACB")
        self.assertEqual(row_chunk.metadata["year"], 2025)
        self.assertEqual(row_chunk.metadata["section_title"], "Bao cao tinh hinh tai chinh")
        self.assertTrue(row_chunk.metadata["retrieval_id"].startswith("financial_report_vi_"))
        self.assertEqual(window_chunk.metadata["linked_row_id"], row_chunk.metadata["retrieval_id"])
        self.assertEqual(row_chunk.metadata["parent_table_id"], full_chunk.metadata["table_id"])
        self.assertIn("source_ids", row_chunk.metadata)

    def test_chunk_ids_are_deterministic(self) -> None:
        parsed = parse_landingai_output(self._load_fixture())

        first = chunk_document(parsed, target_tokens=24, overlap=6)
        second = chunk_document(parsed, target_tokens=24, overlap=6)

        self.assertEqual([item.chunk_id for item in first], [item.chunk_id for item in second])

    def test_chunker_rejects_invalid_params(self) -> None:
        parsed = parse_landingai_output(self._load_fixture())

        with self.assertRaises(ValueError):
            chunk_document(parsed, target_tokens=0, overlap=0)
        with self.assertRaises(ValueError):
            chunk_document(parsed, target_tokens=16, overlap=16)
