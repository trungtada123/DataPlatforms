"""Tests for HTML table metric extraction."""

from __future__ import annotations

from unittest import TestCase

from agents.financial_agent.table_html import extract_row_values_from_html


INCOME_TABLE_HTML = """
<table><thead><tr><th></th><th></th><th>Thuyết minh</th><th colspan="2">Ký sáu tháng kết thúc ngày</th></tr>
<tr><th></th><th></th><th></th><th>30.6.2025 Triệu VND</th><th>30.6.2024 Triệu VND</th></tr></thead>
<tbody><tr><td>XIII</td><td>Lợi nhuận sau thuế</td><td></td><td>8.080.817</td><td>8.004.714</td></tr></tbody></table>
"""


class TableHtmlExtractionTests(TestCase):
    def test_extract_loi_nhuan_sau_thue_from_html_table(self) -> None:
        row_values = extract_row_values_from_html(INCOME_TABLE_HTML, "loi nhuan sau thue")
        self.assertIsNotNone(row_values)
        assert row_values is not None
        self.assertIn("30.6.2025 Triệu VND", row_values)
        self.assertEqual(row_values["30.6.2025 Triệu VND"], "8.080.817")
