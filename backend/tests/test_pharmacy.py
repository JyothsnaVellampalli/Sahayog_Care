"""Pharmacy catalogue integrity, API validation and signed-visit boundaries."""
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.pharmacy import catalogue, service
from app.main import app


class Query:
    def __init__(self, rows, calls):
        self.rows, self.calls = rows, calls
    @property
    def not_(self):
        self.calls.append(('not_',))
        return self
    def __getattr__(self, method):
        def call(*args, **kwargs):
            self.calls.append((method, args, kwargs))
            return self
        return call
    def execute(self):
        return SimpleNamespace(data=self.rows, count=len(self.rows))


def database(monkeypatch, rows):
    calls = []
    monkeypatch.setattr(service, '_admin', lambda: Query(rows, calls))
    return calls


def client():
    return TestClient(app)


def test_catalogue_preserves_variants_and_unknown_manufacturers():
    medicines, brands = catalogue.load_catalogue()
    assert len(medicines) == 90 and len(brands) == 166
    assert len({b['brand_id'] for b in brands}) == 166
    assert {m['specialty'] for m in medicines} == catalogue.SPECIALTIES
    assert all(b['medicine_id'] in {m['id'] for m in medicines} for b in brands)
    assert any(b['manufacturer'] is None for b in brands)
    assert 'Combination:' in next(b['variant'] for b in brands if b['brand_id'] == 'BR002')
    assert 'stock_quantity' not in brands[0]


def test_seed_preserves_existing_stock():
    from scripts.build_pharmacy_seed import build_seed
    sql, medicines, brands = build_seed()
    assert (medicines, brands) == (90, 166)
    assert sql == build_seed()[0]
    assert 'stock_quantity' in sql
    assert 'stock_quantity=excluded' not in sql
    assert 'stock_is_demo=excluded' not in sql
    assert sql.endswith('commit;\n')


def test_invalid_duplicate_catalogue_fails_before_seed(tmp_path):
    import json
    source = json.loads(catalogue.SOURCE.read_text(encoding='utf-8'))
    source['medicines'].append(source['medicines'][0])
    path = tmp_path / 'duplicate.json'
    path.write_text(json.dumps(source), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate medicine'):
        catalogue.load_catalogue(path)


def test_identity_is_active_phone_lookup(monkeypatch):
    calls = database(monkeypatch, [{'id': 'pharmacist', 'full_name': 'Demo', 'phone': '+919800000001'}])
    response = client().post('/api/pharmacy/identify', json={'phone': ' +919800000001 '})
    assert response.status_code == 200
    assert response.json()['profile']['role'] == 'pharmacist'
    assert ('eq', ('phone', '+919800000001'), {}) in calls
    assert ('eq', ('is_active', True), {}) in calls
    database(monkeypatch, [])
    assert client().post('/api/pharmacy/identify', json={'phone': '00000'}).status_code == 404


@pytest.mark.parametrize('path', ['stock', 'filters', 'consultations'])
def test_unknown_pharmacist_cannot_read(monkeypatch, path):
    database(monkeypatch, [])
    assert client().get(f'/api/pharmacy/{uuid4()}/{path}').status_code == 404


@pytest.mark.parametrize('quantity', [-1, 1.2, True, '5', 2147483648])
def test_stock_rejects_invalid_counts(monkeypatch, quantity):
    database(monkeypatch, [{'id': 'pharmacist'}])
    response = client().patch(f'/api/pharmacy/{uuid4()}/stock/BR001', json={'quantity': quantity})
    assert response.status_code == 422


def test_stock_update_clears_demo_flag(monkeypatch):
    calls = database(monkeypatch, [{'brand_id': 'BR001'}])
    assert service.update_stock('BR001', 0)['stock_quantity'] == 0
    payload = next(call[1][0] for call in calls if call[0] == 'update')
    assert payload['stock_is_demo'] is False
    assert payload['stock_quantity'] == 0
    assert payload['stock_updated_at']


def test_combined_filters_and_pagination(monkeypatch):
    calls = database(monkeypatch, [])
    assert service.inventory('Brand', 'cardiology', 'Composition', 'low_stock', 50, 50)['total'] == 0
    for args in [('brand', 'Brand'), ('pharmacy_medicines.specialty', 'cardiology'),
                 ('pharmacy_medicines.composition', 'Composition')]:
        assert ('eq', args, {}) in calls
    assert ('gt', ('available_quantity', 0), {}) in calls
    assert ('lte', ('available_quantity', 10), {}) in calls
    assert ('range', (50, 99), {}) in calls


def test_only_completed_signed_visits_listed(monkeypatch):
    calls = database(monkeypatch, [])
    assert service.consultations()['items'] == []
    assert ('eq', ('status', 'COMPLETED'), {}) in calls
    assert ('not_',) in calls
    assert ('is_', ('finalised_record_key', 'null'), {}) in calls


def test_signed_detail_uses_frozen_record_and_omits_transcript(monkeypatch):
    database(monkeypatch, [{'id': 'visit', 'finalised_record_key': 'frozen', 'patients': {'full_name': 'Patient'}}])
    monkeypatch.setattr(service, 'signed_record', lambda visit: {
        'soap': {'plan': ['Reviewed plan']}, 'segments': ['private transcript'],
        'signature': 'signature', 'doctor_name': 'Doctor', 'signed_at': 'date'})
    result = service.consultation_detail(uuid4())
    assert result['soap']['plan'] == ['Reviewed plan']
    assert 'segments' not in result and 'finalised_record_key' not in result


def test_unsigned_or_missing_visit_returns_404(monkeypatch):
    database(monkeypatch, [])
    with pytest.raises(HTTPException) as error:
        service.consultation_detail(uuid4())
    assert error.value.status_code == 404
