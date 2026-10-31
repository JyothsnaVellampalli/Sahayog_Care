"""Relational prescription persistence; legacy objects are imported once on read."""
from app import storage
from app.consultation import service
from postgrest.exceptions import APIError


def client():
    db = service._admin()
    if db is None:
        raise service.ConsultationServiceUnavailable('Prescription database is unavailable.')
    return db


def read(appointment_id):
    try:
        return client().rpc('read_consultation_prescription', {'p_visit': appointment_id}).execute().data
    except APIError:
        raise service.ConsultationServiceUnavailable('Could not load the prescription database. Please retry.') from None


def write(appointment_id, record, *, workspace=False, importing=False):
    try:
        return client().rpc('write_consultation_prescription', {
            'p_visit': appointment_id, 'p_record': record,
            'p_workspace': workspace, 'p_import': importing,
        }).execute().data
    except APIError as error:
        if error.code == 'P0001':
            raise service.ConsultationError(error.message) from None
        raise service.ConsultationServiceUnavailable('Could not save the prescription database. Please retry.') from None


def load(appointment_id):
    saved = read(appointment_id)
    if saved is not None:
        return saved
    visit = service.get_consultation(appointment_id)
    if visit and visit.get('finalised_record_key'):
        signed = storage.get_json(visit['finalised_record_key'], strict=True) or {}
        legacy = {'items': signed.get('prescription', []), 'doctor_id': signed.get('signed_by'),
                  'reviewed_at': signed.get('signed_at')}
    else:
        legacy = storage.get_json(f'prescriptions/{appointment_id}.json', strict=True) or {}
        workspace = storage.get_json(f'prescription_workspaces/{appointment_id}.json', strict=True) or {}
        if workspace.get('active'):
            legacy = {**workspace, 'active': True}
    if legacy:
        # Import is insert-only, so it cannot replace a concurrent browser save.
        write(appointment_id, legacy, workspace=bool(legacy.get('active')), importing=True)
        return read(appointment_id) or {}
    return {}
