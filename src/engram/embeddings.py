"""Pluggable embedding system for vector search.

Supports local (sentence-transformers) and API-based (OpenAI, Voyage)
embedding backends.  The ``create_embedder`` factory reads from
``EmbeddingConfig`` and returns the appropriate backend -- or ``None``
if embeddings are disabled or dependencies are missing.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

import numpy as np

from engram.config import EmbeddingConfig

logger = logging.getLogger(__name__)


class Embedder(ABC):
    """Base class for all embedding backends."""

    @abstractmethod
    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts into embedding vectors.

        Returns
        -------
        np.ndarray
            Array of shape ``(n, dim)`` with L2-normalised vectors.
        """
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the embedding vectors."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model identifier."""
        ...


class LocalEmbedder(Embedder):
    """sentence-transformers based local embedding."""

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model_name = model
        self._st = SentenceTransformer(model)
        self._dim: int = self._st.get_sentence_embedding_dimension() or 384

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._st.encode(texts, normalize_embeddings=True)

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name


class OpenAIEmbedder(Embedder):
    """OpenAI / Voyage API-based embedding."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str = "",
        base_url: str | None = None,
    ) -> None:
        import openai

        self._model_name = model
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        # Probe dimension with a throwaway request
        resp = self._client.embeddings.create(input=["test"], model=model)
        self._dim = len(resp.data[0].embedding)

    def encode(self, texts: list[str]) -> np.ndarray:
        resp = self._client.embeddings.create(input=texts, model=self._model_name)
        vectors = [d.embedding for d in resp.data]
        arr = np.array(vectors, dtype=np.float32)
        # L2-normalize
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name


def create_embedder(config: EmbeddingConfig) -> Embedder | None:
    """Factory: build an embedder from config.

    Returns ``None`` if embeddings are disabled or required dependencies
    are not installed.
    """
    if not config.enabled:
        return None

    if config.provider == "none":
        return None

    if config.provider == "local":
        try:
            return LocalEmbedder(config.model)
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Run: pip install obsidian-engram[embeddings]"
            )
            return None

    if config.provider in ("openai", "voyage"):
        api_key = config.api_key or os.environ.get("ENGRAM_EMBEDDING_API_KEY", "")
        if not api_key:
            logger.warning(
                "No API key for %s embeddings. Set ENGRAM_EMBEDDING_API_KEY.",
                config.provider,
            )
            return None
        base_url = (
            "https://api.voyageai.com/v1" if config.provider == "voyage" else None
        )
        try:
            return OpenAIEmbedder(config.model, api_key, base_url)
        except ImportError:
            logger.warning(
                "openai package not installed. "
                "Run: pip install obsidian-engram[openai]"
            )
            return None

    logger.warning("Unknown embedding provider: %s", config.provider)
    return None
