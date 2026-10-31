"""Durable DB queue; workers outlive browser requests and resume expired leases."""
import asyncio
import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app import storage
from app.consultation import service, soap, transcription, prescriptions
from app.consultation.sarvam import SarvamError

logger = logging.getLogger(__name__)


def client():
    admin = service._admin()
    if admin is None:
        raise service.ConsultationServiceUnavailable('Processing database is unavailable.')
    return admin


def enqueue(visit_id, kind, dedupe, payload=None):
    return client().rpc('enqueue_consultation_job', {
        'p_visit': visit_id, 'p_kind': kind, 'p_dedupe': dedupe, 'p_payload': payload or {},
    }).execute().data


def status(visit_id):
    rows = (client().table('consultation_jobs').select('id,kind,state,error,created_at,updated_at')
            .eq('appointment_id', visit_id).order('created_at', desc=True).limit(100).execute().data or [])
    return {'jobs': rows}


def load_transcript(visit):
    if visit.get('transcript_key'):
        base = storage.get_json(visit['transcript_key'], strict=True)
        segments = list(base.get('segments', []) if isinstance(base, dict) else base or [])
    else:
        segments = list(transcription.load_transcript(visit['id']))
    # Each recording is immutable. A lease-losing worker cannot publish a chunk.
    rows = (client().table('consultation_jobs').select('result_key,dedupe_key')
            .eq('appointment_id', visit['id']).eq('kind', 'TRANSCRIPTION').eq('state', 'SUCCEEDED')
            .order('created_at').execute().data or [])
    included = {row.get('recording_id') for row in segments}
    for row in rows:
        if row['dedupe_key'] in included:
            continue
        result = storage.get_json(row['result_key'], strict=True)
        if result is None:
            raise storage.StorageError('A saved recording result is unavailable.')
        segments.extend(result['segments'])
        included.add(row['dedupe_key'])
    return segments


def source_hash(segments):
    return hashlib.sha256(json.dumps(segments, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def publish(job, key, source=None, expected_soap=None):
    return client().rpc('finish_consultation_job', {
        'p_job': job['id'], 'p_token': job['lease_token'], 'p_key': key,
        'p_source': source, 'p_expected_soap': expected_soap,
    }).execute().data


def update_lease(job):
    rows = (client().table('consultation_jobs').update({
        'lease_until': (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }).eq('id', job['id']).eq('lease_token', job['lease_token']).eq('state', 'RUNNING').execute().data)
    return bool(rows)


def fail(job, message):
    client().table('consultation_jobs').update({
        'state': 'FAILED', 'error': message, 'lease_until': None,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }).eq('id', job['id']).eq('lease_token', job['lease_token']).eq('state', 'RUNNING').execute()


async def heartbeat(job):
    while True:
        await asyncio.sleep(15)
        try:
            if not await asyncio.to_thread(update_lease, job):
                return
        except Exception:
            logger.warning('Consultation processing heartbeat unavailable')


def prepare_soap(job):
    visit = service.get_consultation(job['appointment_id'])
    if not visit or visit['status'] != 'IN_PROGRESS':
        raise service.ConsultationError('Consultation is no longer open.')
    segments = load_transcript(visit)
    digest = source_hash(segments)
    baseline = visit.get('soap_draft_key')
    # Avoid paying for the same transcript twice after restart/repeated uploads.
    previous = (client().table('consultation_jobs').select('source_hash')
                .eq('appointment_id', visit['id']).eq('kind', 'SOAP').eq('state', 'SUCCEEDED')
                .order('updated_at', desc=True).limit(1).execute().data or [])
    if baseline and previous and previous[0]['source_hash'] == digest and not job['payload'].get('force'):
        return baseline, digest, baseline
    if not any(str(row.get('text') or '').strip() for row in segments):
        raise soap.SoapError('No speech was detected. Record audio or add a transcript note before generating SOAP.')
    medicines = []
    try:
        catalogue = prescriptions.catalogue(visit['doctor_id'])
        medicines = [row for row in catalogue['items'] if not catalogue['default_specialty'] or row['specialty'] == catalogue['default_specialty']]
    except Exception:
        # A slow/unavailable pharmacy must not discard the consultation summary.
        logger.warning('Medicine suggestions unavailable for this SOAP job')
    suggestions = []
    draft = soap.generate_draft(segments, medicines=medicines, on_prescription=suggestions.extend)
    key = f"soap_results/{visit['id']}/{job['id']}/{job['lease_token']}.json"
    storage.put_json(key, {'soap': draft.model_dump(), 'suggestions': suggestions, 'source_hash': digest})
    return key, digest, baseline


async def process(job):
    # A live heartbeat must not leave a hung model call RUNNING forever.
    try:
        await asyncio.wait_for(_process(job), timeout=240 if job['kind'] == 'SOAP' else 2100)
    except TimeoutError:
        await asyncio.to_thread(fail, job, 'Processing timed out. Your saved data is retained. Please retry.')


async def _process(job):
    pulse = asyncio.create_task(heartbeat(job))
    try:
        if job['kind'] == 'SOAP':
            key, digest, baseline = await asyncio.to_thread(prepare_soap, job)
            await asyncio.to_thread(publish, job, key, digest, baseline)
        else:
            payload = job['payload']
            audio = (base64.b64decode(payload['audio_base64']) if payload.get('audio_base64') else
                     await asyncio.to_thread(storage.get_bytes, payload['audio_key'], strict=True))
            if not audio:
                raise SarvamError('Saved audio is unavailable. Please upload the recording again.')
            await asyncio.to_thread(lambda: asyncio.run(transcription.submit_recording(
                job['appointment_id'], job['dedupe_key'], audio, payload['mime'], payload['session'])))
            for _ in range(360):
                result = await asyncio.to_thread(lambda: asyncio.run(transcription.poll_recording(
                    job['appointment_id'], job['dedupe_key'], persist=False)))
                if result['state'] == 'Completed':
                    key = f"transcription_results/{job['appointment_id']}/{job['id']}/{job['lease_token']}.json"
                    await asyncio.to_thread(storage.put_json, key, result)
                    accepted = await asyncio.to_thread(publish, job, key)
                    if accepted and payload.get('audio_key'):
                        await asyncio.to_thread(storage.delete, payload['audio_key'])
                    return
                if result['state'] == 'Failed':
                    raise SarvamError(result.get('note') or 'Audio processing failed. Please retry.')
                await asyncio.sleep(5)
            raise SarvamError('Audio is taking longer than expected. Retry processing to resume the saved recording.')
    except asyncio.CancelledError:
        # Do not mark failed: another worker can recover the expired lease.
        raise
    except (soap.SoapError, SarvamError, service.ConsultationError) as error:
        await asyncio.to_thread(fail, job, str(error))
    except Exception:
        logger.warning('Consultation processing failed; job remains recoverable')
        await asyncio.to_thread(fail, job, 'Processing could not finish. Your saved data is retained. Please retry.')
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)


async def worker():
    while True:
        try:
            job = await asyncio.to_thread(lambda: client().rpc('claim_consultation_job', {}).execute().data)
            if job:
                await process(job)
            else:
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning('Consultation job queue unavailable; retrying')
            await asyncio.sleep(10)
