"""Search ingestion job queue (Phase 6.1): a durable DB queue decoupled from
the consultation lifecycle, mirroring app/consultation/jobs.py's shape
(lease/claim/finish/retry) without the IN_PROGRESS+consent guard, since
ingestion fires at booking time, emergency intake, signing and report
upload -- none of which is "an open, consented consultation".
"""
from __future__ import annotations

import asyncio
import logging

from app import storage
from app.book_appointment.db import _client as _admin
from app.config import settings
from app.search import chunking
from app.search.indexer import index_chunks

logger = logging.getLogger(__name__)


class SearchJobError(RuntimeError):
    pass


def client():
    admin = _admin()
    if admin is None:
        raise SearchJobError("Search ingestion database is unavailable.")
    return admin


def enqueue(kind: str, source_id: str, payload: dict | None = None) -> None:
    """Fire-and-forget: never raises. A no-op until OpenSearch is configured,
    so jobs don't pile up uselessly before setup; run the backfill script
    afterward to catch up on anything booked/signed/uploaded in the meantime.
    """
    if not settings.opensearch_configured:
        logger.info("search: ingestion not configured, skipping enqueue (kind=%s source=%s)", kind, source_id)
        return
    try:
        client().rpc("enqueue_search_job", {"p_kind": kind, "p_source_id": source_id, "p_payload": payload or {}}).execute()
        logger.info("search: job kind=%s source=%s queued", kind, source_id)
    except Exception:
        logger.warning("search: could not queue ingestion job kind=%s source=%s", kind, source_id)


def _fetch_appointment(appointment_id):
    from app.consultation import service
    return service.get_consultation(appointment_id)


def _build_chunks(job):
    kind, source_id = job["kind"], job["source_id"]
    if kind == "APPOINTMENT":
        visit = _fetch_appointment(source_id)
        if not visit:
            return []
        return chunking.chunks_for_appointment(visit)
    if kind == "EMERGENCY_INTAKE":
        rows = client().table("emergency_intakes").select(
            "id,patient_id,symptoms,deidentified_text").eq("id", source_id).limit(1).execute().data
        if not rows:
            return []
        return chunking.chunks_for_emergency_intake(rows[0])
    if kind == "CONSULTATION_SIGNED":
        from app.consultation.finalization import signed_record
        visit = _fetch_appointment(source_id)
        if not visit or not visit.get("finalised_record_key"):
            return []
        record = signed_record(visit)
        if not record:
            return []
        return chunking.chunks_for_signed_consultation(visit, record)
    if kind == "REPORT":
        rows = client().table("consultation_reports").select(
            "id,appointment_id,object_key,content_type").eq("id", source_id).limit(1).execute().data
        if not rows:
            return []
        report = rows[0]
        visit = _fetch_appointment(report["appointment_id"])
        if not visit:
            return []
        data = storage.get_bytes(report["object_key"], strict=True)
        if not data:
            return []
        from app.search.reports_text import extract_text
        text = extract_text(data, report["content_type"])
        return chunking.chunks_for_report(report, visit, text)
    raise SearchJobError(f"Unknown search job kind: {kind}")


def publish(job, chunk_count):
    return client().rpc("finish_search_job", {
        "p_job": job["id"], "p_token": job["lease_token"], "p_chunk_count": chunk_count,
    }).execute().data


def fail(job, message):
    logger.warning("search: job=%s kind=%s source=%s failed: %s", job["id"], job["kind"], job["source_id"], message)
    client().table("search_ingestion_jobs").update({"state": "FAILED", "error": message, "lease_until": None}) \
        .eq("id", job["id"]).eq("lease_token", job["lease_token"]).eq("state", "RUNNING").execute()


def update_lease(job):
    from datetime import datetime, timedelta, timezone
    rows = client().table("search_ingestion_jobs").update({
        "lease_until": (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat(),
    }).eq("id", job["id"]).eq("lease_token", job["lease_token"]).eq("state", "RUNNING").execute().data
    return bool(rows)


async def heartbeat(job):
    while True:
        await asyncio.sleep(15)
        try:
            if not await asyncio.to_thread(update_lease, job):
                return
        except Exception:
            logger.warning("search: heartbeat unavailable for job=%s", job["id"])


async def process(job):
    logger.info("search: job=%s kind=%s source=%s processing started", job["id"], job["kind"], job["source_id"])
    pulse = asyncio.create_task(heartbeat(job))
    try:
        chunks = await asyncio.to_thread(_build_chunks, job)
        logger.info("search: job=%s built %d chunk(s)", job["id"], len(chunks))
        count = await asyncio.to_thread(index_chunks, chunks)
        await asyncio.to_thread(publish, job, count)
        logger.info("search: job=%s indexed %d chunk(s)", job["id"], count)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await asyncio.to_thread(fail, job, f"{type(exc).__name__}: could not finish ingestion.")
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)


async def worker():
    while True:
        try:
            job = await asyncio.to_thread(lambda: client().rpc("claim_search_job", {}).execute().data)
            if job:
                logger.info("search: job=%s kind=%s source=%s claimed", job["id"], job["kind"], job["source_id"])
                await process(job)
            else:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("search: ingestion job queue unavailable (%s); retrying", type(exc).__name__)
            await asyncio.sleep(10)
