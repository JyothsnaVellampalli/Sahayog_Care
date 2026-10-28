"""Sarvam contracts; no network, credentials, or patient audio."""
import asyncio
import json

import httpx
import pytest

from app.config import settings
from app.consultation.sarvam import SarvamClient, SarvamError
from app.consultation.transcription import normalize_result


def test_multilingual_turns_keep_scripts_and_stable_neutral_speakers():
    entries = [
        dict(transcript=text, speaker_id=speaker, start_time_seconds=start,
             end_time_seconds=start + 1)
        for text, speaker, start in [
            ("ముక్కు running nose", "b", 4),
            ("कब से symptoms हैं?", "a", 0),
            ("Two days", "b", 2),
            ("I am accompanying them", "c", 6),
        ]
    ]
    turns = normalize_result({"diarized_transcript": {"entries": entries}}, "recording", 2)
    assert [t["speaker"] for t in turns] == ["Person 1", "Person 2", "Person 2", "Person 3"]
    assert turns[2]["text"] == "ముక్కు running nose"
    assert all(t["recording_id"] == "recording" and t["session"] == 2 for t in turns)


@pytest.mark.parametrize("result", [
    {}, {"transcript": "Speech without speaker turns"},
    {"diarized_transcript": {"entries": [{"transcript": "x", "start_time_seconds": 3,
                                          "end_time_seconds": 1}]}},
])
def test_invalid_results_are_not_saved_as_success(result):
    with pytest.raises(SarvamError):
        normalize_result(result, "recording", 1)


def test_silence_is_empty():
    assert normalize_result({"transcript": "", "diarized_transcript": {"entries": []}}, "r", 1) == []


def test_job_contract_and_signed_upload_keep_key_on_api_only(monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "storage.example":
            assert "api-subscription-key" not in request.headers
            assert request.headers["x-ms-blob-type"] == "BlockBlob"
            assert request.content == b"fake-audio"
            return httpx.Response(201)
        assert request.headers["api-subscription-key"] == "test-key"
        if request.url.path.endswith("upload-files"):
            return httpx.Response(200, json={"storage_container_type": "Azure_V1",
                "upload_urls": {"recording.webm": {"file_url": "https://storage.example/audio"}}})
        params = json.loads(request.content)["job_parameters"]
        assert params["mode"] == "codemix"
        assert params["language_code"] == "unknown"
        assert params["with_diarization"] is True
        assert "num_speakers" not in params
        return httpx.Response(200, json={"job_id": "test-job"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SarvamClient(http)
            job = await client.create()
            await client.upload(job, b"fake-audio", "recording.webm", "audio/webm")

    asyncio.run(run())
    assert len(seen) == 3
