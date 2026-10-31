"""Prescription review, trusted catalogue data, versioning and signing boundaries."""
from copy import deepcopy
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app import storage
from app.consultation import prescriptions as rx, soap, router, finalization, service
from test_signed_consultation import visit, draft


MEDICINE = {'brand_id': 'BR001', 'brand': 'Brand A', 'generic_name': 'Generic A',
            'composition': 'Composition A', 'variant': '5 or 10 mg tablets', 'manufacturer': None}


def item(**kwargs):
    return {'brand_id': 'BR001', 'strength_form': '5 mg tablet', 'dose': '1 tablet',
            'frequency': 'Once daily', 'duration': '5 days', 'instructions': '', 'quantity': 5, **kwargs}


def test_suggestions_only_match_explicit_whole_names_without_dosing():
    summary = soap.SoapDraft(subjective=['Brand A'], objective=[], assessment=['Generic AB'], plan=[])
    assert rx.suggest(summary, [MEDICINE]) == []
    summary.plan = ['Review Generic A.']
    results = rx.suggest(summary, [MEDICINE])
    assert results[0]['brand_id'] == 'BR001'
    assert not {'dose', 'frequency', 'duration'} & results[0].keys()


@pytest.mark.parametrize('change', [{'dose': '  '}, {'brand_id': 'invented'}, {'duration': ''}, {'extra': 'bad'}])
def test_invalid_instructions_rejected(change):
    with pytest.raises(ValidationError):
        rx.PrescriptionItem(**item(**change))


def test_duplicate_brands_rejected():
    with pytest.raises(ValidationError):
        rx.PrescriptionDraft(soap_revision=rx.revision(draft()), items=[item(), item()])


def test_save_canonicalizes_brand_and_preserves_exact_doctor_instructions(visit):
    request = rx.PrescriptionDraft(soap_revision=rx.revision(draft()), items=[item()])
    record = rx.save('visit', 'doctor', request, [MEDICINE])
    assert record['items'][0]['brand'] == 'Brand A'
    assert record['items'][0]['strength_form'] == '5 mg tablet'
    assert rx.load('visit', draft())['reviewed'] is True
    finalization.close('visit', 'doctor', draft())
    frozen = deepcopy(record['items'])
    assert 'prescription' not in visit[1][visit[0]['finalised_record_key']]
    visit[1]['prescriptions/visit.json']['items'] = [item(dose='changed later')]
    assert router.get_soap('visit')['prescription'] == frozen


def test_soap_edit_invalidates_prescription_and_blocks_signing(visit):
    newer = draft().model_copy(update={'plan': ['Changed plan']})
    visit[1]['soap/visit.json'] = newer.model_dump()
    assert rx.load('visit', newer)['reviewed'] is False
    with pytest.raises(service.ConsultationError, match='review'):
        finalization.close('visit', 'doctor', newer)
    assert visit[0]['status'] == 'IN_PROGRESS'


def test_stale_save_and_unknown_brand_rejected(visit):
    request = rx.PrescriptionDraft(soap_revision='a' * 64, items=[])
    with pytest.raises(service.ConsultationError, match='changed'):
        rx.save('visit', 'doctor', request, [])
    request = rx.PrescriptionDraft(soap_revision=rx.revision(draft()), items=[item()])
    with pytest.raises(service.ConsultationError, match='catalogue'):
        rx.save('visit', 'doctor', request, [])


def test_missing_review_blocks_sign_but_reviewed_empty_allowed(visit):
    del visit[1]['database']['visit']
    with pytest.raises(service.ConsultationError):
        finalization.close('visit', 'doctor', draft())
    rx.save('visit', 'doctor', rx.PrescriptionDraft(soap_revision=rx.revision(draft()), items=[]), [])
    finalization.close('visit', 'doctor', draft())
    assert router.get_soap('visit')['prescription'] == []


def test_closed_and_wrong_doctor_prescription_requests_rejected(visit):
    request = rx.PrescriptionDraft(soap_revision=rx.revision(draft()), items=[])
    with pytest.raises(HTTPException) as error:
        router.save_prescription('visit', uuid4(), request)
    assert error.value.status_code == 403
    visit[0]['status'] = 'COMPLETED'
    with pytest.raises(HTTPException) as error:
        router.save_prescription('visit', 'doctor', request)
    assert error.value.status_code == 409


def test_graph_prescription_node_delivers_matches_outside_traced_state():
    from app.consultation import soap_graph
    results = []
    payload = soap_graph.Payload([], None, draft=draft().model_copy(update={'plan': ['Brand A']}),
                                 medicines=[MEDICINE], on_prescription=results.extend)
    token = soap_graph._PAYLOAD.set(payload)
    try:
        state = soap_graph._prescription({})
    finally:
        soap_graph._PAYLOAD.reset(token)
    assert state == {'stage': 'prescription_review_ready', 'medicine_count': 1}
    assert results[0]['brand_id'] == 'BR001'
