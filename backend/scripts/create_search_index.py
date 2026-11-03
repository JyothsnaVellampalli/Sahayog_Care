"""Create the OpenSearch index for search ingestion (Phase 6.1).

Run once, after the AWS OpenSearch domain is active and backend/.env has
OPENSEARCH_ENDPOINT / OPENSEARCH_AWS_ACCESS_KEY_ID /
OPENSEARCH_AWS_SECRET_ACCESS_KEY / EMBEDDING_DIM filled in. See
docs/Progress/Phase6.md for the full AWS setup steps.

Run from backend with the project venv:
    python scripts/create_search_index.py [--recreate]

--recreate deletes and rebuilds the index -- use this after changing
OPENROUTER_EMBEDDINGS_MODEL/EMBEDDING_DIM (the knn_vector dimension is fixed
at creation time). Only safe when nothing in the index is worth keeping;
re-run scripts/backfill_search_index.py afterward to repopulate it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.search.client import get_client, index_name


def main() -> int:
    if not settings.opensearch_configured:
        print("OpenSearch is not configured; fill in OPENSEARCH_* and "
              "OPENROUTER_EMBEDDINGS_MODEL in backend/.env first.", file=sys.stderr)
        return 1
    client = get_client()
    index = index_name()
    recreate = "--recreate" in sys.argv[1:]
    if client.indices.exists(index=index):
        if not recreate:
            print(f"Index '{index}' already exists; nothing to do. Pass --recreate to rebuild it.")
            return 0
        client.indices.delete(index=index)
        print(f"Deleted existing index '{index}'.")
    body = {
        "settings": {"index": {"knn": True}},
        "mappings": {"properties": {
            "patient_id": {"type": "keyword"},
            "doctor_id": {"type": "keyword"},
            "appointment_id": {"type": "keyword"},
            "chunk_type": {"type": "keyword"},
            "section": {"type": "keyword"},
            "text": {"type": "text"},
            "embedding": {"type": "knn_vector", "dimension": settings.embedding_dim},
            "created_at": {"type": "date"},
        }},
    }
    client.indices.create(index=index, body=body)
    print(f"Created index '{index}' (embedding dimension {settings.embedding_dim}).")
    health = client.cluster.health()
    print(f"Cluster status: {health.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
