"""Regression tests for local NL2SQL answer formatting."""

from __future__ import annotations

import unittest

from src.agents.market_agent.nl2sql import _local_answer


class LocalAnswerRegressionTest(unittest.TestCase):
    def test_percentage_change_none_returns_graceful_message(self) -> None:
        answer = _local_answer(
            "HPG có đang trên MA50 không?",
            [{"ticker": "HPG", "percentage_change": None}],
        )

        self.assertIn("HPG", answer)
        self.assertIn("chưa đủ", answer.lower())

    def test_comparison_none_returns_graceful_message(self) -> None:
        answer = _local_answer(
            "So sánh giá ACB ngày 13/01/2026 và 14/04/2026",
            [
                {
                    "ticker": "ACB",
                    "date_1": "2026-01-13",
                    "price_1": 25.0,
                    "date_2": "2026-04-14",
                    "price_2": 24.0,
                    "price_change": None,
                    "percent_change": None,
                }
            ],
        )

        self.assertIn("ACB", answer)
        self.assertIn("chưa đủ", answer.lower())

    def test_period_change_none_returns_graceful_message(self) -> None:
        answer = _local_answer(
            "Giá ACB từ đầu năm đến nay thay đổi thế nào?",
            [
                {
                    "ticker": "ACB",
                    "start_price": 20.0,
                    "end_price": 21.0,
                    "change_pct": None,
                    "base_date": "2026-01-02",
                    "current_date": "2026-04-16",
                }
            ],
        )

        self.assertIn("ACB", answer)
        self.assertIn("chưa đủ", answer.lower())

    def test_percentage_change_prefers_row_ticker_over_normalized_question(self) -> None:
        answer = _local_answer(
            "compare price of ACB on 2026-01-13 and 2026-04-14",
            [{"ticker": "ACB", "percentage_change": -3.61}],
        )

        self.assertIn("ACB", answer)
        self.assertNotIn("PRICE", answer)


if __name__ == "__main__":
    unittest.main()

