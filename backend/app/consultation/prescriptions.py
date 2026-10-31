"""Doctor-reviewed prescriptions and bounded catalogue matches, never dosing advice."""
import hashlib
import json
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app import storage
from app.consultation import service, soap, prescription_store
from app.doctor import service as doctors

SPECIALTIES = {'CARD': 'cardiology', 'ORTH': 'orthopedics', 'DERM': 'dermatology', 'GAST': 'gastroenterology'}


class PrescriptionItem(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    brand_id: str = Field(pattern=r'^BR\d{3}$')
    strength_form: str = Field(min_length=1, max_length=150)
    dose: str = Field(min_length=1, max_length=150)
    frequency: str = Field(min_length=1, max_length=150)
    duration: str = Field(min_length=1, max_length=150)
    quantity: int = Field(ge=1, le=1000000)
    instructions: str = Field(default='', max_length=500)

    @field_validator('strength_form', 'dose', 'frequency', 'duration')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('Prescription instructions cannot be blank')
        return value.strip()


class PrescriptionDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    soap_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    items: list[PrescriptionItem] = Field(max_length=30)

    @model_validator(mode='after')
    def unique_brands(self):
        if len({item.brand_id for item in self.items}) != len(self.items):
            raise ValueError('Each brand may only appear once')
        return self


def revision(draft):
    data = draft.model_dump() if isinstance(draft, soap.SoapDraft) else draft
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def catalogue(doctor_id):
    doctor = doctors.get_doctor_by_id(doctor_id)
    if not doctor:
        raise service.ConsultationError('Doctor not found.')
    client = service._admin()
    if client is None:
        raise service.ConsultationServiceUnavailable('Medicine catalogue is unavailable.')
    default_specialty = ''
    if doctor.get('specialty_id'):
        rows = client.table('specialties').select('code').eq('id', doctor['specialty_id']).limit(1).execute().data or []
        default_specialty = SPECIALTIES.get(rows[0]['code'], '') if rows else ''
    items = []
    offset = 0
    while True:
        rows = (client.table('pharmacy_brands').select(
            'brand_id,brand,variant,manufacturer,stock_quantity,locked_quantity,stock_is_demo,source_status,'
            'pharmacy_medicines!inner(generic_name,composition,specialty,source_details)')
            .order('brand_id').range(offset, offset + 499).execute().data or [])
        for row in rows:
            medicine = row.pop('pharmacy_medicines')
            source = medicine.pop('source_details') or {}
            items.append({**row, **medicine, 'forms': source.get('dosage_forms', []),
                          'available_quantity': max(0, row['stock_quantity'] - row['locked_quantity']) if row['stock_quantity'] is not None else None,
                          'prescription_status': source.get('prescription_status', '')})
        if len(rows) < 500:
            break
        offset += 500
    return {'items': items, 'default_specialty': default_specialty,
            'specialties': sorted(set(SPECIALTIES.values()))}


def suggest(draft, medicines):
    """Surface explicit medicine mentions for review; do not infer a treatment."""
    text = ' '.join(draft.assessment + draft.plan).casefold()
    results = []
    for row in medicines:
        names = [row['brand'], row['generic_name']]
        matched = next((name for name in names if re.search(r'(?<!\w)' + re.escape(name.casefold()) + r'(?!\w)', text)), None)
        if matched:
            results.append({**row, 'reason': f'{matched} is mentioned in the saved assessment or plan. Review the context before adding.'})
    return results  # These are mentions, including negations, not recommendations.


def load(consultation_id, draft, visit=None):
    saved = prescription_store.load(consultation_id)
    current_revision = revision(draft) if draft else None
    suggestions = {}
    if visit and visit.get('soap_draft_key'):
        result = storage.get_json(visit['soap_draft_key'], strict=True) or {}
        suggestions = {'items': result.get('suggestions', []), 'soap_revision': current_revision}
    elif draft:
        suggestions = storage.get_json(f'prescription_suggestions/{consultation_id}.json', strict=True) or {}
    workspace = saved
    return {'items': workspace.get('items', []) if workspace.get('active') else saved.get('items', []),
            'workspace_updated_at': workspace.get('updated_at'), 'soap_revision': current_revision,
            'reviewed': bool(not workspace.get('active') and saved.get('reviewed_at') and saved.get('soap_revision') == current_revision
                             and all(isinstance(item.get('quantity'), int) and item['quantity'] > 0 for item in saved.get('items', []))),
            'suggestions': suggestions.get('items', []) if suggestions.get('soap_revision') == current_revision else []}


def save(consultation_id, doctor_id, request, medicines):
    visit = service.get_consultation(consultation_id)
    draft = soap.load_for_visit(visit)
    if draft is None or request.soap_revision != revision(draft):
        raise service.ConsultationError('The SOAP summary changed. Reload and review the prescription again.')
    by_id = {row['brand_id']: row for row in medicines}
    items = []
    for item in request.items:
        row = by_id.get(item.brand_id)
        if row is None:
            raise service.ConsultationError('A selected medicine is no longer in the catalogue.')
        items.append({**item.model_dump(), **{key: row.get(key) for key in
                     ('brand', 'generic_name', 'composition', 'variant', 'manufacturer')}})
    record = {'items': items, 'soap_revision': request.soap_revision, 'doctor_id': doctor_id,
              'reviewed_at': datetime.now(timezone.utc).isoformat(), 'soap_draft_key': visit.get('soap_draft_key')}
    return prescription_store.write(consultation_id, record)


def for_signing(consultation_id, doctor_id, draft):
    saved_soap = soap.load_for_visit(service.get_consultation(consultation_id))
    saved = prescription_store.load(consultation_id)
    workspace = saved
    if (workspace.get('active') or saved_soap is None or revision(saved_soap) != revision(draft) or not saved
            or not saved.get('reviewed_at') or saved.get('doctor_id') != doctor_id
            or saved.get('soap_revision') != revision(draft)):
        raise service.ConsultationError('Save and review the prescription for the current SOAP summary before signing (an empty prescription is allowed).')
    if any(type(item.get('quantity')) is not int or not 1 <= item['quantity'] <= 1000000 for item in saved['items']):
        raise service.ConsultationError('Enter and save the stock quantity for every prescribed medicine before signing.')
    return saved['items']


class WorkspaceItem(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    brand_id: str = Field(pattern=r'^BR\d{3}$')
    brand: str = Field(default='', max_length=200)
    variant: str = Field(default='', max_length=500)
    strength_form: str = Field(default='', max_length=150)
    dose: str = Field(default='', max_length=150)
    frequency: str = Field(default='', max_length=150)
    duration: str = Field(default='', max_length=150)
    instructions: str = Field(default='', max_length=500)
    quantity: int | None = Field(default=None, ge=1, le=1000000)


class PrescriptionWorkspace(BaseModel):
    items: list[WorkspaceItem] = Field(max_length=30)


def save_workspace(consultation_id, request):
    data = {'active': True, 'items': [item.model_dump() for item in request.items],
            'updated_at': datetime.now(timezone.utc).isoformat()}
    saved = prescription_store.write(consultation_id, data, workspace=True)
    return {'updated_at': saved['updated_at']}
