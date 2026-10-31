"""Object storage for signatures, transcripts and SOAP drafts (Phase 2.1).

One interface with two backends, chosen by configuration:

* **S3** (production) when AWS credentials + a bucket are configured. Keeps
  identified data inside the account's region (default ap-south-1 / Mumbai, per
  the PRD's data-residency constraint).
* **Local filesystem** (dev fallback) under ``backend/storage/`` otherwise, so
  the app runs before AWS is set up.

Callers use logical *keys* (e.g. ``signatures/<doctor>.png``); the backend maps
them to an S3 object key or a local path. Switching to S3 later is config-only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings

_BACKEND_DIR = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Raised when a storage operation fails."""


# --- S3 backend --------------------------------------------------------------


def _s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        # A JSON save must fail promptly enough for the UI to offer a retry.
        config=Config(connect_timeout=5, read_timeout=15,
                      # /soap paths can hit S3's legacy SOAP routing on a
                      # virtual-hosted bucket. Keep keys, use /bucket/key URLs.
                      s3={"addressing_style": "path"},
                      retries={"mode": "standard", "total_max_attempts": 2}),
    )


def _s3_key(key: str) -> str:
    prefix = settings.s3_prefix.strip("/")
    return f"{prefix}/{key}" if prefix else key


# --- Local backend -----------------------------------------------------------


def _local_path(key: str) -> Path:
    base = Path(settings.local_storage_dir)
    if not base.is_absolute():
        base = _BACKEND_DIR / base
    path = base / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# --- Public API --------------------------------------------------------------


def backend_name() -> str:
    return "s3" if settings.s3_configured else "local"


def put_bytes(key: str, data: bytes, content_type: str | None = None) -> str:
    """Store raw bytes at ``key``. Returns the key."""
    if settings.s3_configured:
        extra = {"ContentType": content_type} if content_type else {}
        try:
            _s3_client().put_object(
                Bucket=settings.s3_bucket, Key=_s3_key(key), Body=data, **extra
            )
        except Exception as exc:
            response = getattr(exc, "response", None) or {}
            code = response.get("Error", {}).get("Code", type(exc).__name__)
            logger.warning("S3 object save failed: %s", code)
            raise StorageError(f"S3 put failed for {key}: {exc}") from exc
    else:
        _local_path(key).write_bytes(data)
    return key


def get_bytes(key: str, *, strict: bool = False) -> bytes | None:
    """Fetch raw bytes at ``key``, or None if missing."""
    if settings.s3_configured:
        try:
            obj = _s3_client().get_object(Bucket=settings.s3_bucket, Key=_s3_key(key))
            return obj["Body"].read()
        except Exception as exc:
            code = str((getattr(exc, "response", None) or {}).get("Error", {}).get("Code", ""))
            if strict and code not in ("NoSuchKey", "404", "NotFound"):
                raise StorageError("Could not read stored object.") from exc
            return None
    path = _local_path(key)
    return path.read_bytes() if path.exists() else None


def delete(key: str) -> None:
    """Delete the object at ``key`` (best effort)."""
    if settings.s3_configured:
        try:
            _s3_client().delete_object(Bucket=settings.s3_bucket, Key=_s3_key(key))
        except Exception:
            pass
    else:
        path = _local_path(key)
        if path.exists():
            path.unlink()


def put_json(key: str, payload: dict | list) -> str:
    """Store a JSON document (used for transcripts and SOAP drafts)."""
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return put_bytes(key, data, content_type="application/json")


def get_json(key: str, *, strict: bool = False) -> dict | list | None:
    """Fetch and decode a JSON document, or None if missing."""
    raw = get_bytes(key, strict=strict)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        if strict:
            raise StorageError("Stored JSON is invalid.") from exc
        return None
