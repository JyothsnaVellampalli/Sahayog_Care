"""Follow-up ownership, report permissions, file validation and helpdesk read paths."""
from types import SimpleNamespace
from uuid import UUID
import asyncio
import io
import pytest
from fastapi import HTTPException, UploadFile
from app import care_records as records
from app.book_appointment import router as booking
from app.patient import router as patients

VISIT = UUID('10000000-0000-0000-0000-000000000001')
PATIENT = UUID('20000000-0000-0000-0000-000000000001')
OTHER = UUID('30000000-0000-0000-0000-000000000001')


class Query:
    def __init__(self, rows): self.rows, self.filters = rows, []
    def table(self, name): self.name = name; return self
    def select(self, *a, **kw): return self
    def eq(self, *a): self.filters.append(a); return self
    def limit(self, *a): return self
    def execute(self): return SimpleNamespace(data=self.rows)


def test_followup_requires_owned_completed_visit(monkeypatch):
    q = Query([])
    monkeypatch.setattr(patients, '_verify_patient', lambda *a: {})
    monkeypatch.setattr(booking.patient_service, '_require_admin', lambda: q)
    with pytest.raises(HTTPException) as error:
        booking._validate_followup(str(PATIENT), str(VISIT), 'Bearer token')
    assert error.value.status_code == 422
    assert ('patient_id', str(PATIENT)) in q.filters and ('status', 'COMPLETED') in q.filters


def access(monkeypatch):
    monkeypatch.setattr(records.service, 'get_consultation', lambda _: {'patient_id': str(PATIENT), 'doctor_id': str(OTHER)})
    monkeypatch.setattr(records, '_verify_patient', lambda *a: {})


def test_patient_report_access_is_scoped(monkeypatch):
    access(monkeypatch)
    assert records.report_access(VISIT, 'Bearer t', PATIENT, None, None) == ('patient', str(PATIENT))
    with pytest.raises(HTTPException) as error:
        records.report_access(VISIT, 'Bearer t', OTHER, None, None)
    assert error.value.status_code == 403


def test_report_access_requires_identity(monkeypatch):
    access(monkeypatch)
    with pytest.raises(HTTPException) as error:
        records.report_access(VISIT, None, None, None, None)
    assert error.value.status_code == 401


@pytest.mark.parametrize('actor', [('patient', str(PATIENT)), ('reader', str(OTHER))])
def test_report_upload_denied_before_storage(actor):
    with pytest.raises(HTTPException) as error:
        asyncio.run(records.upload_report(VISIT, UploadFile(io.BytesIO(b'pdf')), 'Report', actor))
    assert error.value.status_code == 403


@pytest.mark.parametrize('data', [b'', b'<svg onload="alert(1)"></svg>', b'fake.pdf', b'%PDF-truncated', b'\xff\xd8\xff'])
def test_rejects_unsupported_or_truncated_report(data):
    with pytest.raises(HTTPException): records.report_type(data)


def test_report_download_scoped_to_visit(monkeypatch):
    q = Query([]); monkeypatch.setattr(records, '_require_admin', lambda: q)
    with pytest.raises(HTTPException) as error:
        records.report_file(VISIT, OTHER, ('patient', str(PATIENT)))
    assert error.value.status_code == 404
    assert ('appointment_id', str(VISIT)) in q.filters


def test_upload_stores_file_and_metadata_without_stock_calls(monkeypatch):
    class Insert(Query):
        def insert(self, row): self.rows = [row]; return self
    q = Insert([]); writes = []
    monkeypatch.setattr(records, '_require_admin', lambda: q)
    monkeypatch.setattr(records.storage, 'put_bytes', lambda *args: writes.append(args))
    result = asyncio.run(records.upload_report(VISIT, UploadFile(io.BytesIO(b'%PDF-1.4\n%%EOF')), ' Blood panel ', ('helpdesk', str(OTHER))))
    assert result['title'] == 'Blood panel' and result['content_type'] == 'application/pdf'
    assert q.name == 'consultation_reports' and q.rows[0]['appointment_id'] == str(VISIT)
    assert writes[0][0].startswith(f'reports/{VISIT}/')


def test_helpdesk_read_uses_stored_clinical_data_without_import(monkeypatch):
    monkeypatch.setattr(records, 'helpdesk', lambda _: {})
    monkeypatch.setattr(records.service, 'get_consultation', lambda _: {'id': str(VISIT), 'finalised_record_key': 'signed'})
    monkeypatch.setattr(records.storage, 'get_json', lambda *a, **k: {'soap': {'plan': ['Review']}, 'prescription': []})
    monkeypatch.setattr(records.prescription_store, 'read', lambda _: {'items': [{'brand': 'Demo'}]})
    result = records.consultation(OTHER, VISIT)
    assert result['prescription'] == [{'brand': 'Demo'}]
    assert 'finalised_record_key' not in result
