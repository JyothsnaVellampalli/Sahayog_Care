"""Plain text-layer extraction from PDF reports (Phase 6.1).

No OCR: a scanned (image-only) PDF or a PNG/JPEG report has no text layer to
extract and is skipped, not an error -- real document understanding (OCR,
table-structure extraction) is out of scope for this phase. See
docs/Progress/Phase6.md for the limitation and the follow-up note.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

MAX_PAGES = 50


def extract_text(data: bytes, mime: str) -> str | None:
    if mime != "application/pdf":
        logger.info("search: report mime=%s has no text layer to extract, skipping", mime)
        return None
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = reader.pages[:MAX_PAGES]
        text = "\n".join(page.extract_text() or "" for page in pages).strip()
    except Exception as exc:
        logger.warning("search: PDF text extraction failed (%s)", type(exc).__name__)
        return None
    if not text:
        logger.info("search: PDF has no extractable text layer (likely scanned), skipping")
        return None
    return text
