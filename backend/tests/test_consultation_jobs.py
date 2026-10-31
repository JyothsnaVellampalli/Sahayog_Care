import asyncio
import base64
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers
from app import storage
from app.consultation import jobs, router, soap, prescriptions


@pytest.fixture
def objects(monkeypatch):
    data = {}
    monkeypatch.setattr(storage, 'put_json', lambda key, value: data.__setitem__(key, deepcopy(value)) or key)
    monkeypatch.setattr(storage, 'get_json', lambda key, **kw: deepcopy(data.get(key)))
    return data


def test_audio_is_saved_before_job_acknowledgement(monkeypatch):
    events = []
    visit, recording = uuid4(), uuid4()
    monkeypatch.setattr(router, '_editable', lambda _: {'consent_recorded': True})
    monkeypatch.setattr(storage, 'put_bytes', lambda key, audio, mime: events.append(('save', audio)))
    def enqueue(*args):
        assert events == []  # No audio object is written to S3.
        assert base64.b64decode(args[3]['audio_base64']) == b'audio'
        return {'id':'job','kind':'TRANSCRIPTION','state':'QUEUED','payload':args[3]}
    monkeypatch.setattr(jobs, 'enqueue', enqueue)
    audio = UploadFile(BytesIO(b'audio'), headers=Headers({'content-type':'audio/webm'}))
    result = asyncio.run(router.transcribe(visit, audio, recording, 1))
    assert result['job']['state'] == 'QUEUED'
    assert 'payload' not in result['job']


def test_worker_publishes_audio_result_and_only_then_removes_audio(monkeypatch, objects):
    events = []
    monkeypatch.setattr(storage, 'get_bytes', lambda *a, **kw: b'audio')
    monkeypatch.setattr(storage, 'delete', lambda key: events.append('delete'))
    async def submit(*a): return {'state':'Processing'}
    async def poll(*a, **kw):
        assert kw['persist'] is False
        return {'state':'Completed','segments':[{'recording_id':'recording','text':'Saved'}]}
    monkeypatch.setattr(jobs.transcription, 'submit_recording', submit)
    monkeypatch.setattr(jobs.transcription, 'poll_recording', poll)
    def publish(job, key):
        assert objects[key]['segments'][0]['text'] == 'Saved'
        events.append('publish')
        return True
    monkeypatch.setattr(jobs, 'publish', publish)
    asyncio.run(jobs.process({'id':'job','kind':'TRANSCRIPTION','appointment_id':'visit','dedupe_key':'recording','lease_token':'lease',
                             'payload':{'audio_key':'audio','mime':'audio/webm','session':1}}))
    assert events == ['publish','delete']


def test_failed_worker_preserves_saved_data_and_reports_safe_error(monkeypatch):
    failures = []
    monkeypatch.setattr(jobs, 'prepare_soap', lambda _: (_ for _ in ()).throw(RuntimeError('private provider body')))
    monkeypatch.setattr(jobs, 'fail', lambda job, message: failures.append(message))
    asyncio.run(jobs.process({'kind':'SOAP'}))
    assert 'private provider body' not in failures[0]
    assert 'retained' in failures[0]


def test_current_soap_reads_published_pointer_not_old_canonical(objects):
    old = {'subjective':['Old'],'objective':[],'assessment':[],'plan':[]}
    new = {**old, 'subjective':['New']}
    objects['soap/visit.json'] = old
    objects['result'] = {'soap':new}
    assert soap.load_for_visit({'id':'visit','soap_draft_key':'result'}).subjective == ['New']


def test_transcript_merge_retains_manual_edits_without_duplicate_recordings(monkeypatch, objects):
    objects['edited'] = {'segments':[{'recording_id':'r1','text':'Edited first recording'}]}
    objects['r1'] = {'segments':[{'recording_id':'r1','text':'Original'}]}
    objects['r2'] = {'segments':[{'recording_id':'r2','text':'Second'}]}
    class Query:
        def __getattr__(self, name): return lambda *a, **kw: self
        def execute(self): return SimpleNamespace(data=[{'dedupe_key':'r1','result_key':'r1'},{'dedupe_key':'r2','result_key':'r2'}])
    monkeypatch.setattr(jobs, 'client', Query)
    result = jobs.load_transcript({'id':'visit','transcript_key':'edited'})
    assert [s['text'] for s in result] == ['Edited first recording','Second']


def test_partial_prescription_is_saved_without_soap_and_requires_review(objects, monkeypatch):
    database = {}
    def write(key, value, **kwargs):
        database[key] = deepcopy(value)
        return database[key]
    monkeypatch.setattr(prescriptions.prescription_store, 'write', write)
    monkeypatch.setattr(prescriptions.prescription_store, 'load', lambda key: database.get(key, {}))
    request = prescriptions.PrescriptionWorkspace(items=[{'brand_id':'BR001','brand':'Brand A','dose':'1 tablet'}])
    prescriptions.save_workspace('visit', request)
    restored = prescriptions.load('visit', None)
    assert restored['items'][0]['dose'] == '1 tablet'
    assert restored['reviewed'] is False and restored['soap_revision'] is None
    assert not any(key.startswith('prescription_workspaces/') for key in objects)


def test_hung_soap_becomes_retryable_without_publishing(monkeypatch):
    failures = []
    async def timeout(task, **kwargs):
        task.close()
        assert kwargs['timeout'] == 240
        raise TimeoutError
    monkeypatch.setattr(jobs.asyncio, 'wait_for', timeout)
    monkeypatch.setattr(jobs, 'fail', lambda job, message: failures.append(message))
    asyncio.run(jobs.process({'kind': 'SOAP'}))
    assert 'timed out' in failures[0]
