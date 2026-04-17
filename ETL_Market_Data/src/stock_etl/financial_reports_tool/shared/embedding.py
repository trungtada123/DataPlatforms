"""Embedding helper cho financial reports runtime."""

from __future__ import annotations

import logging


LOGGER = logging.getLogger(__name__)


class FinancialReportsEmbedder:
    """Wrapper lazy-load SentenceTransformer cho query-time embedding."""

    def __init__(self, model_name: str, *, device: str | None = None) -> None:
        self.model_name = model_name
        self.device = device
        self._model = None

    @property
    def model(self):  # type: ignore[no-untyped-def]
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            target_device = self.device or "cpu"
            try:
                LOGGER.info("Loading financial reports embedding model %s on %s", self.model_name, target_device)
                self._model = SentenceTransformer(self.model_name, device=target_device)
                self.device = target_device
            except RuntimeError as exc:
                if target_device == "cpu" or not self._should_retry_on_cpu(exc):
                    raise
                LOGGER.warning(
                    "Embedding model %s failed on %s, retrying on cpu: %s",
                    self.model_name,
                    target_device,
                    exc,
                )
                self.device = "cpu"
                self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        """Encode nhiều query/context text thành normalized vectors."""

        if not texts:
            return []
        try:
            vectors = self.model.encode(
                texts,
                batch_size=16,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
        except RuntimeError as exc:
            if self.device == "cpu" or not self._should_retry_on_cpu(exc):
                raise
            LOGGER.warning("Embedding encode failed on %s, retrying on cpu: %s", self.device, exc)
            self.device = "cpu"
            self._model = None
            vectors = self.model.encode(
                texts,
                batch_size=16,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
        return vectors.tolist()

    @staticmethod
    def _should_retry_on_cpu(exc: RuntimeError) -> bool:
        message = str(exc).lower()
        return any(
            token in message
            for token in (
                "cuda",
                "out of memory",
                "meta tensor",
                "device-side assert",
                "not enough memory",
            )
        )
