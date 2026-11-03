"""Backfill search ingestion jobs for existing data (Phase 6.1).

Enqueues one job per existing appointment (symptom intake), emergency
intake, completed/signed consultation, and uploaded report. Idempotent: the
(kind, source_id) unique constraint means rerunning this does not duplicate
jobs -- it's safe to run again after adding more data or recovering from an
earlier partial run.

Run from backend with the project venv, after create_search_index.py:
    python scripts/backfill_search_index.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.search import jobs as search_jobs

PAGE = 200


def _paginate(table, select):
    offset = 0
    while True:
        rows = (search_jobs.client().table(table).select(select)
                .range(offset, offset + PAGE - 1).execute().data or [])
        yield from rows
        if len(rows) < PAGE:
            return
        offset += PAGE


def main() -> int:
    if not settings.opensearch_configured:
        print("OpenSearch is not configured; fill in OPENSEARCH_* and "
              "OPENROUTER_EMBEDDINGS_MODEL in backend/.env first.", file=sys.stderr)
        return 1

    counts = {"APPOINTMENT": 0, "CONSULTATION_SIGNED": 0, "EMERGENCY_INTAKE": 0, "REPORT": 0}

    for row in _paginate("appointments", "id,status,symptom_text,finalised_record_key"):
        if row.get("symptom_text"):
            search_jobs.enqueue("APPOINTMENT", row["id"])
            counts["APPOINTMENT"] += 1
        if row.get("status") == "COMPLETED" and row.get("finalised_record_key"):
            search_jobs.enqueue("CONSULTATION_SIGNED", row["id"])
            counts["CONSULTATION_SIGNED"] += 1

    for row in _paginate("emergency_intakes", "id"):
        search_jobs.enqueue("EMERGENCY_INTAKE", row["id"])
        counts["EMERGENCY_INTAKE"] += 1

    for row in _paginate("consultation_reports", "id"):
        search_jobs.enqueue("REPORT", row["id"])
        counts["REPORT"] += 1

    print("Queued ingestion jobs:", counts)
    print("The running search worker (see app/main.py) will process the "
          "queue in the background. Check progress in Supabase with:\n"
          "  select state, count(*) from search_ingestion_jobs group by state;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
