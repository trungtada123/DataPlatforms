"""Market/SSI settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from .base import load_environment
from .llm import get_llm_settings


DEFAULT_SYMBOLS = [
    "ACB",
    "BCM",
    "BID",
    "BVH",
    "CTG",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "MBB",
    "MSN",
    "MWG",
    "PLX",
    "POW",
    "SAB",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
    "VND",
    "VIX",
    "PVS",
    "PVD",
    "NLG",
    "KDH",
    "DXG",
    "DIG",
    "KBC",
    "DCM",
    "DPM",
    "REE",
    "GEX",
    "EIB",
    "OCB",
    "LPB",
    "SCS",
    "CTR",
    "BSR",
    "IDC",
]


def split_symbol_csv(raw: str | None, fallback: list[str]) -> list[str]:
    """Split ticker CSV with uppercase normalization."""

    if not raw:
        return fallback
    values = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return values or fallback


@dataclass(slots=True)
class MarketSettings:
    """SSI + market ingestion settings."""

    ssi_consumer_id: str
    ssi_consumer_secret: str
    ssi_base_url: str
    ssi_stream_url: str
    tracked_symbols: list[str]
    bootstrap_start_date: date
    request_delay_seconds: float
    max_retries: int
    news_summarizer_model: str


def get_market_settings() -> MarketSettings:
    """Build market settings from environment variables."""

    load_environment()
    llm = get_llm_settings()
    settings = MarketSettings(
        ssi_consumer_id=os.getenv("SSI_CONSUMER_ID", "").strip(),
        ssi_consumer_secret=os.getenv("SSI_CONSUMER_SECRET", "").strip(),
        ssi_base_url=os.getenv("SSI_BASE_URL", "https://fc-data.ssi.com.vn").rstrip("/"),
        ssi_stream_url=os.getenv("SSI_STREAM_URL", "https://fc-datahub.ssi.com.vn").rstrip("/"),
        tracked_symbols=split_symbol_csv(os.getenv("TRACKED_SYMBOLS"), DEFAULT_SYMBOLS),
        bootstrap_start_date=date.fromisoformat(os.getenv("BOOTSTRAP_START_DATE", "2022-01-01")),
        request_delay_seconds=float(os.getenv("REQUEST_DELAY_SECONDS", "1.05")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        news_summarizer_model=os.getenv("NEWS_SUMMARIZER_MODEL", llm.groq_model).strip(),
    )

    if settings.request_delay_seconds < 0:
        raise ValueError("REQUEST_DELAY_SECONDS must be non-negative.")
    if settings.max_retries < 0:
        raise ValueError("MAX_RETRIES must be non-negative.")
    return settings

