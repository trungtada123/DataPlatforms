"""Tests for text normalization helpers."""

from __future__ import annotations

from unittest import TestCase

from src.utils.text import dedupe_limitations


class TextUtilsTests(TestCase):
    def test_dedupe_limitations_prefers_vietnamese(self) -> None:
        items = [
            "Da loai 4 bai it lien quan khoi phan tong hop cuoi.",
            "Đã loại 4 bài ít liên quan khỏi phần tổng hợp cuối.",
        ]
        result = dedupe_limitations(items)
        self.assertEqual(len(result), 1)
        self.assertIn("Đã loại", result[0])
