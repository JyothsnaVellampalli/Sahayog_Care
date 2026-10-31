from copy import deepcopy

import pytest
from postgrest.exceptions import APIError
from app.consultation import prescription_store as store, service


def test_database_record_does_not_read_legacy_s3(monkeypatch):
    saved = {'items': [{'brand_id': 'BR001', 'medicine_id': 'M001', 'quantity': 5}]}
    monkeypatch.setattr(store, 'read', lambda _: saved)
    monkeypatch.setattr(store.storage, 'get_json', lambda *a, **kw: pytest.fail('Unexpected S3 read'))
    assert store.load('visit') == saved


def test_legacy_signed_prescription_import_retains_original(monkeypatch):
    original = {'prescription': [{'brand_id': 'BR001', 'quantity': 5}],
                'signed_by': 'doctor', 'signed_at': '2026-10-30T00:00:00Z'}
    database = {}
    monkeypatch.setattr(store, 'read', lambda _: database.get('record'))
    monkeypatch.setattr(service, 'get_consultation', lambda _: {'finalised_record_key': 'signed'})
    monkeypatch.setattr(store.storage, 'get_json', lambda *a, **kw: deepcopy(original))
    def write(visit, record, **options):
        assert options == {'workspace': False, 'importing': True}
        database['record'] = record
    monkeypatch.setattr(store, 'write', write)
    assert store.load('visit')['items'] == original['prescription']
    assert original['prescription'][0]['quantity'] == 5


def test_prescription_database_failure_never_silently_uses_stale_objects(monkeypatch):
    class Broken:
        def rpc(self, *args): return self
        def execute(self): raise APIError({'code': 'PGRST202', 'message': 'missing'})
    monkeypatch.setattr(store, 'client', Broken)
    monkeypatch.setattr(store.storage, 'get_json', lambda *a, **kw: pytest.fail('Stale fallback'))
    with pytest.raises(service.ConsultationServiceUnavailable):
        store.load('visit')
