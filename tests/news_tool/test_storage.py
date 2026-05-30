"""Tests cho utility canonicalize URL của news tool."""

from __future__ import annotations

from unittest import TestCase

from src.agents.news_agent.storage import canonicalize_url


class NewsStorageUrlTests(TestCase):
    def test_canonicalize_url_removes_tracking_params(self) -> None:
        raw_url = (
            "https://cafef.vn/fpt-cap-nhat-188260528170618458.chn"
            "?utm_source=facebook&fbclid=abc123&id=42&gclid=zzz&utm_campaign=spring"
        )

        canonical = canonicalize_url(raw_url)

        self.assertEqual(
            canonical,
            "https://cafef.vn/fpt-cap-nhat-188260528170618458.chn?id=42",
        )

