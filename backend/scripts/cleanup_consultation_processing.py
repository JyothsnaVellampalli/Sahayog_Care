"""Purge stale consultation processing state (Phase 5 TTL).

Scope: only process/draft state older than CONSULTATION_PROCESSING_TTL_DAYS
(default 15) -- terminal consultation_jobs rows and orphaned per-edit
transcript/SOAP draft snapshots for closed consultations. Never touches
signed records, signatures, or recorded audio (recordings/...), which have
no TTL and are kept indefinitely.

Run from backend with the project venv:
    python scripts/cleanup_consultation_processing.py [--apply]

Without --apply, only prints what would be deleted (dry run).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import storage
from app.config import settings
from app.consultation.jobs import client

TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "NO_SHOW")


def purge_job_rows(apply: bool) -> int:
    if not apply:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.consultation_processing_ttl_days)).isoformat()
        rows = (client().table('consultation_jobs').select('id')
                .in_('state', ['SUCCEEDED', 'FAILED']).lt('updated_at', cutoff).execute().data or [])
        print(f"Would purge {len(rows)} consultation_jobs rows older than {settings.consultation_processing_ttl_days} days.")
        return 0
    deleted = client().rpc('purge_stale_consultation_jobs', {
        'p_ttl_days': settings.consultation_processing_ttl_days,
    }).execute().data or []
    for row in deleted:
        for key in (row.get('result_key'), row.get('audio_key')):
            if key:
                storage.delete(key)
    print(f"Purged {len(deleted)} stale consultation_jobs rows and their result/audio objects.")
    return len(deleted)


def sweep_draft_orphans(apply: bool) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.consultation_processing_ttl_days)
    appointments = (client().table('appointments')
                    .select('id,status,transcript_key,soap_draft_key,finalised_record_key,created_at,completed_at')
                    .in_('status', TERMINAL_STATUSES).execute().data or [])
    removed = 0
    for visit in appointments:
        closed_at = visit.get('completed_at') or visit.get('created_at')
        if not closed_at or datetime.fromisoformat(closed_at) >= cutoff:
            continue
        kept = {visit.get('transcript_key'), visit.get('soap_draft_key'), visit.get('finalised_record_key')}
        for prefix in (f"transcript_edits/{visit['id']}/", f"soap_results/{visit['id']}/"):
            for key in storage.list_keys(prefix):
                if key in kept:
                    continue
                removed += 1
                if apply:
                    storage.delete(key)
                else:
                    print(f"Would delete: {key}")
    print(f"{'Deleted' if apply else 'Would delete'} {removed} orphaned draft objects for closed consultations.")
    return removed


def main() -> int:
    apply = '--apply' in sys.argv[1:]
    if not apply:
        print("Dry run (pass --apply to actually delete). TTL:", settings.consultation_processing_ttl_days, "days")
    purge_job_rows(apply)
    sweep_draft_orphans(apply)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
