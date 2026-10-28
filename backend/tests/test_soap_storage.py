"""SOAP endpoint persistence checks without model or AWS calls."""
import pytest
from fastapi import HTTPException

from app import storage
from app.consultation import router, soap


@pytest.fixture
def generation(monkeypatch):
    draft = soap.SoapDraft(subjective=["No fever."], objective=[], assessment=[], plan=[])
    monkeypatch.setattr(router.service, "get_consultation", lambda _: {"id": "visit"})
    monkeypatch.setattr(router.transcription, "load_transcript", lambda _: [{"text": "No fever."}])
    monkeypatch.setattr(soap, "generate_draft", lambda _: draft)
    return draft


def test_generated_summary_is_saved_as_json(monkeypatch, tmp_path, generation):
    from types import SimpleNamespace

    monkeypatch.setattr(storage, "settings", SimpleNamespace(
        s3_configured=False, local_storage_dir=str(tmp_path)))
    assert router.generate_soap("visit") == generation
    assert storage.get_json("soap/visit.json") == generation.model_dump()
    generation.subjective = ["Updated summary"]
    router.generate_soap("visit")
    assert storage.get_json("soap/visit.json")["subjective"] == ["Updated summary"]


@pytest.mark.parametrize("error", [storage.StorageError("private provider details"), OSError("disk full")])
def test_save_failure_is_reported(monkeypatch, generation, error):
    def fail(*args):
        raise error

    monkeypatch.setattr(storage, "put_json", fail)
    with pytest.raises(HTTPException) as caught:
        router.generate_soap("visit")
    assert caught.value.status_code == 503
    assert caught.value.detail == "Could not save the SOAP draft. Please try again."


def test_invalid_generation_does_not_save(monkeypatch, generation):
    writes = []

    def fail(_):
        raise soap.SoapError("Invalid draft")

    monkeypatch.setattr(soap, "generate_draft", fail)
    monkeypatch.setattr(storage, "put_json", lambda *args: writes.append(args))
    with pytest.raises(HTTPException) as caught:
        router.generate_soap("visit")
    assert caught.value.status_code == 422
    assert writes == []


def test_s3_receives_four_fields_as_utf8_json(monkeypatch, generation):
    import json
    from types import SimpleNamespace

    writes = []
    monkeypatch.setattr(storage, "settings", SimpleNamespace(
        s3_configured=True, s3_bucket="test-bucket", s3_prefix="test"))
    monkeypatch.setattr(storage, "_s3_client", lambda: SimpleNamespace(
        put_object=lambda **kwargs: writes.append(kwargs)))
    assert router.generate_soap("visit") == generation
    assert writes[0]["Bucket"] == "test-bucket"
    assert writes[0]["Key"] == "test/soap/visit.json"
    assert writes[0]["ContentType"] == "application/json"
    assert json.loads(writes[0]["Body"].decode("utf-8")) == generation.model_dump()


def test_s3_timeout_returns_retryable_error(monkeypatch, generation):
    from types import SimpleNamespace
    from botocore.exceptions import ReadTimeoutError

    def timeout(**kwargs):
        raise ReadTimeoutError(endpoint_url="https://s3.example.test")

    monkeypatch.setattr(storage, "settings", SimpleNamespace(
        s3_configured=True, s3_bucket="test-bucket", s3_prefix=""))
    monkeypatch.setattr(storage, "_s3_client", lambda: SimpleNamespace(put_object=timeout))
    with pytest.raises(HTTPException) as caught:
        router.generate_soap("visit")
    assert caught.value.status_code == 503


def test_s3_uses_path_addressing_for_root_soap_prefix(monkeypatch):
    import boto3
    from types import SimpleNamespace

    captured = {}
    def client(service, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(boto3, "client", client)
    monkeypatch.setattr(storage, "settings", SimpleNamespace(
        aws_access_key_id="test", aws_secret_access_key="test",
        aws_region="ap-south-2", s3_prefix=""))
    storage._s3_client()
    assert captured["config"].s3["addressing_style"] == "path"
    assert storage._s3_key("soap/visit.json") == "soap/visit.json"
