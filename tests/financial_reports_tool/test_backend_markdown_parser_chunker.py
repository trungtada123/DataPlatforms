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
            any(chunk.metadata.get("chunk_type") in {"table", "table_fragment"} for chunk in chunks)
        )
        self.assertTrue(any(chunk.metadata.get("chunk_type") == "text" for chunk in chunks))

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
