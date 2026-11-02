"""Root logging setup so step-by-step progress logs show up in the terminal
during development and in stdout deployment logs in production.

Without this, module-level ``logging.getLogger(__name__)`` calls elsewhere in
the app have no configured handler: INFO messages are silently dropped, and
only WARNING+ reach Python's bare-bones "handler of last resort". Call
``configure_logging()`` once, as early as possible (main.py does this before
anything else), to make ``logger.info(...)`` progress logs visible.
"""
from __future__ import annotations

import logging

from app.config import settings


# Every outgoing HTTP call these libraries make (Supabase/Postgrest, S3,
# OpenRouter, Sarvam) logs its own INFO line with the full raw URL/query
# string by default. At INFO that drowns out the app's own clean step-by-step
# progress lines with request plumbing nobody asked to see. Keep them at
# WARNING so only real problems from these libraries show up.
_QUIET_LIBRARIES = (
    "httpx", "httpcore", "hpack", "h11", "supabase", "postgrest",
    "openai", "urllib3", "botocore", "boto3", "s3transfer",
)


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for name in _QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
