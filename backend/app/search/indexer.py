"""Embed and bulk-upsert chunks into OpenSearch (Phase 6.1)."""
from __future__ import annotations

import logging

from app.search import embeddings
from app.search.client import get_client, index_name

logger = logging.getLogger(__name__)


def index_chunks(chunks) -> int:
    """Embed and upsert each chunk by chunk_id. Returns the count indexed.

    An empty list is a no-op (not an error) -- a source row with nothing
    chunk-worthy (e.g. an unsigned/empty SOAP section) is a normal outcome.
    """
    if not chunks:
        return 0
    from opensearchpy import helpers

    client = get_client()
    index = index_name()
    actions = []
    for chunk in chunks:
        vector = embeddings.embed_text(chunk.text)
        actions.append({
            "_op_type": "index", "_index": index, "_id": chunk.chunk_id,
            "_source": {
                "patient_id": chunk.patient_id, "doctor_id": chunk.doctor_id,
                "appointment_id": chunk.appointment_id, "chunk_type": chunk.chunk_type,
                "section": chunk.section, "text": chunk.text,
                "embedding": vector,
            },
        })
    success, errors = helpers.bulk(client, actions, raise_on_error=False)
    if errors:
        logger.warning("search: %d of %d chunks failed to index", len(errors), len(actions))
        raise RuntimeError(f"{len(errors)} chunk(s) failed to index.")
    return success
