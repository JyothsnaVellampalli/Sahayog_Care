"""Show search-ingestion job queue state and OpenSearch index contents
(Phase 6.1) in one place, for checking progress or debugging.

Run from backend with the project venv:
    python scripts/search_status.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.search import jobs as search_jobs
from app.search.client import get_client, index_name


def job_queue_status():
    rows = (search_jobs.client().table("search_ingestion_jobs")
            .select("state").execute().data or [])
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    print("Job queue (search_ingestion_jobs):")
    for state in ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED"):
        print(f"  {state}: {counts.get(state, 0)}")
    if not rows:
        print("  (no rows)")
    failed = (search_jobs.client().table("search_ingestion_jobs")
              .select("id,kind,source_id,error").eq("state", "FAILED").limit(10).execute().data or [])
    if failed:
        print("\nMost recent failures (up to 10):")
        for row in failed:
            print(f"  job={row['id']} kind={row['kind']} source={row['source_id']}: {row['error']}")


def opensearch_status():
    index = index_name()
    print(f"\nOpenSearch index '{index}':")
    client = get_client()
    if not client.indices.exists(index=index):
        print("  Index does not exist. Run scripts/create_search_index.py.")
        return
    total = client.count(index=index)["count"]
    print(f"  Total documents: {total}")
    if total == 0:
        return
    agg = client.search(index=index, body={
        "size": 0, "aggs": {"by_type": {"terms": {"field": "chunk_type"}}},
    })
    for bucket in agg["aggregations"]["by_type"]["buckets"]:
        print(f"  {bucket['key']}: {bucket['doc_count']}")


def main() -> int:
    job_queue_status()
    if settings.opensearch_configured:
        opensearch_status()
    else:
        print("\nOpenSearch is not configured; skipping index check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
