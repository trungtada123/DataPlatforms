"""Tests cho config của news tool."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from stock_etl.news_tool.config import get_news_tool_settings


class NewsToolConfigTests(TestCase):
    """Kiểm tra default config cho news tool."""

    def test_defaults_artifact_root_to_news_artifacts_folder(self) -> None:
        settings_like = SimpleNamespace(
            google_api_key="",
            google_api_keys=[],
            gemini_model="gemini-test",
            gemini_max_retries=0,
            gemini_retry_delay_seconds=0.0,
            groq_api_key="",
            groq_api_keys=[],
            groq_model="groq-test",
            groq_timeout_seconds=60,
            groq_max_retries=0,
            groq_retry_delay_seconds=0.0,
            groq_base_url="https://api.groq.com/openai/v1",
            timezone="Asia/Ho_Chi_Minh",
        )

        with patch.dict("os.environ", {"NEWS_ARTIFACT_ROOT": ""}, clear=False):
            settings = get_news_tool_settings(settings_like)

        self.assertEqual(settings.artifact_root.name, "news_artifacts")
