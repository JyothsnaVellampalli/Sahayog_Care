"""Phase 6 read-only helpdesk consultations and shared report attachments.

Staff identification follows the existing development phone-only portals.
Patient report access always requires a verified Supabase session and ownership.
"""
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from app import storage
from app.patient.service import _require_admin
from app.patient.router import _verify_patient
from app.consultation import service, soap, prescription_store

router = APIRouter(prefix='/api', tags=['care-records'])


def helpdesk(staff_id):
    rows = _require_admin().table('helpdesk_staff').select('id,full_name,phone').eq(
        'id', str(staff_id)).eq('is_active', True).limit(1).execute().data
    if not rows:
        raise HTTPException(403, 'Helpdesk profile is not available.')
    return rows[0]


class Identify(BaseModel):
    phone: str = Field(min_length=5, max_length=20)


@router.post('/helpdesk/identify')
def identify(request: Identify):
    rows = _require_admin().table('helpdesk_staff').select('id,full_name,phone').eq(
        'phone', request.phone).eq('is_active', True).limit(1).execute().data
    if not rows:
        raise HTTPException(404, 'Helpdesk profile not found.')
    return {'profile': rows[0]}


@router.get('/helpdesk/{staff_id}/filters')
def filters(staff_id: UUID):
    helpdesk(staff_id)
    db = _require_admin()
    return {'doctors': db.table('doctors').select('id,full_name,specialty_id').order('full_name').execute().data,
            'specialties': db.table('specialties').select('id,name').order('name').execute().data}


@router.get('/helpdesk/{staff_id}/consultations')
def consultations(staff_id: UUID, date_from: datetime, date_to: datetime,
                  doctor_id: UUID | None = None, specialty_id: UUID | None = None,
                  page: int = Query(default=0, ge=0)):
    helpdesk(staff_id)
    if not date_from.tzinfo or not date_to.tzinfo or date_from >= date_to:
        raise HTTPException(422, 'Choose a valid day and time range.')
    q = _require_admin().table('appointments').select(
        'id,status,reason,linked_appointment_id,patients(full_name),specialties(name),'
        'slots!inner(starts_at,doctor_id,doctors(full_name))', count='exact')
    q = q.gte('slots.starts_at', date_from.isoformat()).lte('slots.starts_at', date_to.isoformat())
    if doctor_id:
        q = q.eq('slots.doctor_id', str(doctor_id))
    if specialty_id:
        q = q.eq('specialty_id', str(specialty_id))
    result = q.order('created_at', desc=True).order('id').range(page*50, page*50+49).execute()
    return {'consultations': result.data, 'count': result.count, 'page': page}


@router.get('/helpdesk/{staff_id}/consultations/{appointment_id}')
def consultation(staff_id: UUID, appointment_id: UUID):
    helpdesk(staff_id)
    visit = service.get_consultation(str(appointment_id))
    if not visit:
        raise HTTPException(404, 'Consultation not found.')
    try:
        if visit.get('finalised_record_key'):
            record = storage.get_json(visit['finalised_record_key'], strict=True)
            if not isinstance(record, dict):
                raise storage.StorageError('Signed record unavailable.')
            rx = prescription_store.read(visit['id'])
            record['prescription'] = rx.get('items', []) if rx else record.get('prescription', [])
        else:
            draft = soap.load_for_visit(visit)
            # Read only: unlike the legacy loader, do not import prescription data.
            rx = prescription_store.read(visit['id']) or {}
            record = {'soap': draft.model_dump() if draft else None, 'prescription': rx.get('items', [])}
    except (storage.StorageError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Clinical records are temporarily unavailable.') from None
    return {**{k: v for k, v in visit.items() if not k.endswith('_key')},
            **{k: record.get(k) for k in ('soap', 'prescription', 'signed_at', 'doctor_name', 'signature')}}


def report_access(appointment_id: UUID, authorization: str | None = Header(default=None),
                  x_patient_id: UUID | None = Header(default=None),
                  x_doctor_id: UUID | None = Header(default=None),
                  x_helpdesk_id: UUID | None = Header(default=None)):
    visit = service.get_consultation(str(appointment_id))
    if not visit:
        raise HTTPException(404, 'Record not found.')
    if x_patient_id:
        _verify_patient(str(x_patient_id), authorization)
        if visit['patient_id'] != str(x_patient_id):
            raise HTTPException(403, 'This appointment is not available.')
        return ('patient', str(x_patient_id))
    if x_helpdesk_id:
        helpdesk(x_helpdesk_id)
        return ('helpdesk', str(x_helpdesk_id))
    if x_doctor_id:
        from app.doctor.service import get_doctor_by_id
        if get_doctor_by_id(str(x_doctor_id)):
            # Staff may read related consultations across doctors; uploads belong to the assigned doctor.
            return ('doctor' if visit['doctor_id'] == str(x_doctor_id) else 'reader', str(x_doctor_id))
    raise HTTPException(401, 'Please sign in to view reports.')


REPORT_COLS = 'id,title,report_type,reported_at,content_type,size_bytes,is_synthetic,findings'
MAX_REPORT = 10 * 1024 * 1024


@router.get('/records/{appointment_id}/reports')
def reports(appointment_id: UUID, actor=Depends(report_access)):
    rows = _require_admin().table('consultation_reports').select(REPORT_COLS).eq(
        'appointment_id', str(appointment_id)).order('reported_at').order('id').execute().data
    return {'reports': rows}


def report_type(data):
    if data.startswith(b'%PDF-') and b'%%EOF' in data[-1024:]:
        return 'application/pdf', 'pdf'
    if data.startswith(b'\x89PNG\r\n\x1a\n') and data.endswith(b'IEND\xaeB`\x82'):
        return 'image/png', 'png'
    if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        return 'image/jpeg', 'jpg'
    raise HTTPException(422, 'Upload a PDF, PNG or JPEG file.')


@router.post('/records/{appointment_id}/reports', status_code=201)
async def upload_report(appointment_id: UUID, file: UploadFile = File(...),
                        title: str = Form(min_length=1, max_length=160), actor=Depends(report_access)):
    if actor[0] not in ('doctor', 'helpdesk'):
        raise HTTPException(403, 'Only the assigned doctor or helpdesk can add reports.')
    data = await file.read(MAX_REPORT + 1)
    await file.close()
    if not data or len(data) > MAX_REPORT:
        raise HTTPException(413, 'Choose a non-empty report up to 10 MB.')
    if not title.strip():
        raise HTTPException(422, 'Enter a report title.')
    mime, extension = report_type(data)
    report_id = str(uuid4())
    key = f'reports/{appointment_id}/{report_id}.{extension}'
    try:
        storage.put_bytes(key, data, mime)
        rows = _require_admin().table('consultation_reports').insert({
            'id': report_id, 'appointment_id': str(appointment_id), 'title': title.strip(),
            'report_type': 'DOCUMENT', 'findings': {}, 'object_key': key, 'content_type': mime,
            'size_bytes': len(data), 'uploaded_by': actor[1], 'uploaded_role': actor[0],
        }).execute().data
    except Exception:
        # Keep the object on ambiguous DB timeout: a committed row must never lose its file.
        raise HTTPException(503, 'Could not confirm the upload. Refresh reports before retrying.') from None
    from app.search import jobs as search_jobs
    search_jobs.enqueue('REPORT', report_id)
    return {k: rows[0].get(k) for k in REPORT_COLS.split(',')}


@router.get('/records/{appointment_id}/reports/{report_id}/file')
def report_file(appointment_id: UUID, report_id: UUID, actor=Depends(report_access)):
    rows = _require_admin().table('consultation_reports').select('object_key,content_type').eq(
        'appointment_id', str(appointment_id)).eq('id', str(report_id)).limit(1).execute().data
    if not rows:
        raise HTTPException(404, 'Report not found.')
    mime = rows[0]['content_type']
    if mime not in ('application/pdf', 'image/png', 'image/jpeg'):
        raise HTTPException(404, 'This report contains findings only.')
    try:
        data = storage.get_bytes(rows[0]['object_key'], strict=True)
    except storage.StorageError:
        raise HTTPException(503, 'Report storage is temporarily unavailable.') from None
    if data is None:
        raise HTTPException(404, 'Report file is unavailable.')
    return Response(data, media_type=mime, headers={'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'Content-Disposition': f'inline; filename="report-{report_id}"'})
