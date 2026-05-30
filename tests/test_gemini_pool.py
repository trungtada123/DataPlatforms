"""Tests cho helper xoay vòng Gemini API key."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.core.llm_pool import GeminiKeyPool


class GeminiKeyPoolTests(TestCase):
    """Kiểm tra cơ chế failover giữa nhiều Gemini key."""

    def test_rotates_to_next_key_when_first_key_fails(self) -> None:
        state = {"api_key": None}

        def fake_configure(*, api_key: str) -> None:
            state["api_key"] = api_key

        class FakeModel:
            def __init__(self, *, model_name: str, generation_config: dict):  # type: ignore[no-untyped-def]
                self.model_name = model_name
                self.generation_config = generation_config

            def generate_content(self, prompt: str):  # type: ignore[no-untyped-def]
                if state["api_key"] == "bad-key":
                    raise RuntimeError("API_KEY_INVALID")
                return SimpleNamespace(text=f"ok:{state['api_key']}")

        settings = SimpleNamespace(
            google_api_key="bad-key",
            google_api_keys=["bad-key", "good-key"],
            gemini_model="gemini-test",
            gemini_max_retries=0,
            gemini_retry_delay_seconds=0.0,
        )

        with patch("src.core.llm_pool.genai.configure", side_effect=fake_configure), patch(
            "src.core.llm_pool.genai.GenerativeModel",
            side_effect=FakeModel,
        ):
            output = GeminiKeyPool(settings, generation_config={"temperature": 0.0}).generate_text("hello")

        self.assertEqual(output, "ok:good-key")

    def test_raises_when_no_keys_are_available(self) -> None:
        settings = SimpleNamespace(
            google_api_key="",
            google_api_keys=[],
            gemini_model="gemini-test",
            gemini_max_retries=0,
            gemini_retry_delay_seconds=0.0,
        )

        with self.assertRaises(ValueError):
            GeminiKeyPool(settings).generate_text("hello")

