"""Background SOAP results are immutable and published separately from generation."""
import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app import storage
from app.consultation import jobs, router, soap

JOB = {'id': 'job', 'appointment_id': 'visit', 'lease_token': 'token', 'payload': {}}


@pytest.fixture
def generation(monkeypatch):
    draft = soap.SoapDraft(subjective=['No fever.'], objective=[], assessment=[], plan=[])
    monkeypatch.setattr(jobs.service, 'get_consultation', lambda _: {'id': 'visit', 'doctor_id': 'doctor', 'status': 'IN_PROGRESS'})
    monkeypatch.setattr(jobs, 'load_transcript', lambda _: [{'text': 'No fever.'}])
    monkeypatch.setattr(jobs.prescriptions, 'catalogue', lambda _: {'items': [], 'default_specialty': ''})
    monkeypatch.setattr(soap, 'generate_draft', lambda _, **kwargs: draft)
    class Query:
        def __getattr__(self, name): return lambda *a, **kw: self
        def execute(self): return SimpleNamespace(data=[])
    monkeypatch.setattr(jobs, 'client', Query)
    return draft


def test_generation_saves_versioned_result_without_publishing(monkeypatch, tmp_path, generation):
    monkeypatch.setattr(storage, 'settings', SimpleNamespace(s3_configured=False, local_storage_dir=str(tmp_path)))
    key, digest, baseline = jobs.prepare_soap(JOB)
    assert storage.get_json(key)['soap'] == generation.model_dump()
    assert len(digest) == 64 and baseline is None
    assert storage.get_json('soap/visit.json') is None


def test_enqueue_returns_without_waiting_for_model(monkeypatch, generation):
    monkeypatch.setattr(jobs, 'enqueue', lambda *a: {'id': 'job', 'kind': 'SOAP', 'state': 'QUEUED'})
    monkeypatch.setattr(soap, 'generate_draft', lambda *a, **kw: pytest.fail('Request must not wait for the LLM'))
    assert router.generate_soap('visit')['job']['state'] == 'QUEUED'


def test_empty_transcript_cannot_enqueue(monkeypatch, generation):
    monkeypatch.setattr(jobs, 'load_transcript', lambda _: [])
    with pytest.raises(HTTPException) as error:
        router.generate_soap('visit')
    assert error.value.status_code == 422


@pytest.mark.parametrize('error', [storage.StorageError('private details'), OSError('disk full')])
def test_storage_failure_never_publishes_result(monkeypatch, generation, error):
    def fail(*a): raise error
    monkeypatch.setattr(storage, 'put_json', fail)
    with pytest.raises(type(error)):
        jobs.prepare_soap(JOB)


def test_s3_result_contains_soap_and_suggestions(monkeypatch, generation):
    writes = []
    monkeypatch.setattr(storage, 'settings', SimpleNamespace(s3_configured=True, s3_bucket='test', s3_prefix='test'))
    monkeypatch.setattr(storage, '_s3_client', lambda: SimpleNamespace(put_object=lambda **kw: writes.append(kw)))
    jobs.prepare_soap(JOB)
    assert json.loads(writes[0]['Body'])['soap'] == generation.model_dump()
    assert writes[0]['Key'] == 'test/soap_results/visit/job/token.json'


def test_invalid_generation_does_not_write(monkeypatch, generation):
    def fail(*a, **kw): raise soap.SoapError('Invalid draft')
    monkeypatch.setattr(soap, 'generate_draft', fail)
    monkeypatch.setattr(storage, 'put_json', lambda *a: pytest.fail('Invalid results must not be stored'))
    with pytest.raises(soap.SoapError): jobs.prepare_soap(JOB)


def test_s3_uses_path_addressing_for_root_soap_prefix(monkeypatch):
    import boto3
    captured = {}
    def client(service, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace()
    monkeypatch.setattr(boto3, 'client', client)
    monkeypatch.setattr(storage, 'settings', SimpleNamespace(aws_access_key_id='test', aws_secret_access_key='test', aws_region='ap-south-2', s3_prefix=''))
    storage._s3_client()
    assert captured['config'].s3['addressing_style'] == 'path'
