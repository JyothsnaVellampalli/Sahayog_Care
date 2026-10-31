from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError
from pydantic import ValidationError
from app.consultation import finalization, service as consultations
from app.consultation.prescriptions import PrescriptionItem
from app.pharmacy import service, router
from test_signed_consultation import visit, draft
from test_prescriptions import item


@pytest.mark.parametrize('quantity', [0, -1, 1.5, True, '3', 1000001])
def test_invalid_stock_quantities(quantity):
    with pytest.raises(ValidationError):
        PrescriptionItem(**item(quantity=quantity))


@pytest.mark.parametrize('hours,can_unlock', [(23.99, False), (24.01, True), (48, True)])
def test_release_flag_uses_signing_time(hours, can_unlock):
    row = {'completed_at': (datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat(),
           'pharmacy_reservations': [{'brand_id':'BR001','quantity':5,'status':'LOCKED'}]}
    assert service.reservation_status(row)['can_unlock'] is can_unlock
    row['pharmacy_reservations'][0]['status'] = 'DISPENSED'
    assert service.reservation_status(row)['can_unlock'] is False


def test_old_signed_visits_do_not_gain_reservations():
    result = service.reservation_status({'completed_at': '2020-01-01T00:00:00Z'})
    assert result['reservation_status'] == 'NONE'
    assert result['can_unlock'] is False


def test_stock_shortage_keeps_visit_open(visit, monkeypatch):
    class Client:
        def rpc(self, name, params):
            assert name == 'finalize_consultation_with_stock'
            return self
        def execute(self):
            raise APIError({'code':'P0001','message':'Insufficient available stock for Brand A.'})
    monkeypatch.setattr(consultations, '_admin', lambda: Client())
    with pytest.raises(consultations.ConsultationError, match='Insufficient'):
        finalization.close('visit','doctor',draft())
    assert visit[0]['status'] == 'IN_PROGRESS'
    assert not visit[0].get('finalised_record_key')


@pytest.mark.parametrize('code', ['23514','P0001'])
def test_stock_conflicts_report_409(code):
    def fail():
        raise APIError({'code':code,'message':'Stock can only be unlocked 24 hours after signing.'})
    with pytest.raises(HTTPException) as error:
        router.run(fail)
    assert error.value.status_code == 409


def test_resolution_uses_transactional_rpc(monkeypatch):
    calls = []
    class Client:
        def rpc(self, name, params):
            calls.append((name,params))
            return self
        def execute(self): return SimpleNamespace(data={'status':'RELEASED'})
    monkeypatch.setattr(service, '_admin', lambda: Client())
    assert service.resolve_reservation('visit','pharmacist','release')['status']=='RELEASED'
    assert calls == [('resolve_pharmacy_reservation', {'p_appointment_id':'visit','p_pharmacist_id':'pharmacist','p_action':'release'})]
