"""Embedding calls via OpenRouter (Phase 6.1), mirroring the adapter pattern
in app/book_appointment/model_adapter.py -- same client construction, same
typed-error/type-only-logging convention.
"""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when the embedding model is unconfigured or the call fails."""


def embed_text(text: str) -> list[float]:
    if not settings.embeddings_configured:
        raise EmbeddingError("OPENROUTER_EMBEDDINGS_MODEL is not configured.")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guaranteed
        raise EmbeddingError("The 'openai' package is not installed.") from exc

    client = OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.openrouter_timeout_seconds,
    )
    try:
        response = client.embeddings.create(
            model=settings.openrouter_embeddings_model,
            input=text,
            extra_headers={"HTTP-Referer": "https://sahayog.care", "X-Title": "Sahayog Care"},
        )
    except Exception as exc:
        # Log only the exception type: provider SDK error messages can echo
        # back request/response bodies (same convention as soap_graph._call).
        logger.warning("search: embedding call failed (%s)", type(exc).__name__)
        raise EmbeddingError(f"Embedding call failed: {type(exc).__name__}") from None

    if not response.data or not response.data[0].embedding:
        raise EmbeddingError("Embedding model returned no vector.")
    vector = response.data[0].embedding
    if len(vector) != settings.embedding_dim:
        raise EmbeddingError(
            f"Embedding dimension {len(vector)} does not match configured EMBEDDING_DIM={settings.embedding_dim}."
        )
    return vector
