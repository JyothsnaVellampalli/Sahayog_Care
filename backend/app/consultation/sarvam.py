"""Sarvam Batch REST adapter: mixed-language transcription and diarization.

API contract: https://docs.sarvam.ai/api-reference/speech-to-text/stt/job/initiate
No audio, API keys, signed URLs, or provider error bodies are logged.
"""
from urllib.parse import quote, urlparse

import httpx

from app.config import settings

BASE = "https://api.sarvam.ai/speech-to-text/job/v1"


class SarvamError(RuntimeError):
    """A safe-to-display provider error."""


class SarvamClient:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def _api(self, method: str, path: str = "", payload: dict | None = None) -> dict:
        if not settings.sarvam_api_key:
            raise SarvamError("Set SARVAM_API_KEY in backend/.env and restart the API.")
        try:
            response = await self.client.request(
                method, BASE + path, json=payload,
                headers={"api-subscription-key": settings.sarvam_api_key},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            return data
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                raise SarvamError("Sarvam rejected the API key or account permissions.") from None
            if code in (402, 429):
                raise SarvamError("Sarvam credits or rate limit reached. Check your account and retry.") from None
            raise SarvamError(f"Sarvam request failed (HTTP {code}). Retry or check the configured model.") from None
        except (httpx.RequestError, ValueError):
            raise SarvamError("Could not reach Sarvam or read its response. Please retry.") from None

    async def create(self) -> str:
        result = await self._api("POST", payload={"job_parameters": {
            "model": settings.sarvam_stt_model,
            "mode": "codemix",
            "language_code": "unknown",
            "with_diarization": True,
            "with_timestamps": True,
            # No num_speakers: let Sarvam detect one, two, three or more.
        }})
        job_id = result.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise SarvamError("Sarvam did not return a job identifier.")
        return job_id

    @staticmethod
    def _file_url(data: dict, field: str, filename: str) -> str:
        entry = (data.get(field) or {}).get(filename) or {}
        url = entry.get("file_url", "")
        if not isinstance(url, str) or urlparse(url).scheme != "https":
            raise SarvamError("Sarvam did not return a secure file transfer URL.")
        return url

    async def upload(self, job_id: str, audio: bytes, filename: str, mime: str) -> None:
        links = await self._api("POST", "/upload-files", {"job_id": job_id, "files": [filename]})
        url = self._file_url(links, "upload_urls", filename)
        headers = {"Content-Type": mime}
        if str(links.get("storage_container_type", "")).startswith("Azure"):
            headers["x-ms-blob-type"] = "BlockBlob"
        try:
            # Deliberately omit the Sarvam API key when calling signed storage URLs.
            response = await self.client.put(url, content=audio, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError:
            raise SarvamError("Audio upload to Sarvam failed. Your recording can be retried.") from None

    async def start(self, job_id: str) -> None:
        await self._api("POST", f"/{quote(job_id, safe='')}/start")

    async def status(self, job_id: str) -> dict:
        return await self._api("GET", f"/{quote(job_id, safe='')}/status")

    async def result(self, job_id: str, status: dict) -> dict:
        if status.get("failed_files_count", 0):
            raise SarvamError("Sarvam could not process this recording. Try a new recording.")
        files = [o.get("file_name") for d in status.get("job_details", [])
                 for o in d.get("outputs", []) if str(o.get("file_name", "")).endswith(".json")]
        if len(files) != 1:
            raise SarvamError("Sarvam returned an unexpected number of transcript files.")
        links = await self._api("POST", "/download-files", {"job_id": job_id, "files": files})
        url = self._file_url(links, "download_urls", files[0])
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            return data
        except (httpx.HTTPError, ValueError):
            raise SarvamError("Could not download the transcript from Sarvam. Please retry.") from None
