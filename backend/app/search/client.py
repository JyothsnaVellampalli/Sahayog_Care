"""AWS OpenSearch client for the search-ingestion pipeline (Phase 6.1).

Signs requests via SigV4 using OPENSEARCH_AWS_* if set, otherwise falls back
to the existing S3 credentials (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) --
see settings.opensearch_access_key/opensearch_secret_key in app/config.py.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from urllib.parse import urlparse

from app.config import settings

logger = logging.getLogger(__name__)


class SearchServiceUnavailable(RuntimeError):
    """Raised when OpenSearch is not configured or unreachable."""


@lru_cache(maxsize=1)
def get_client():
    if not settings.opensearch_configured:
        raise SearchServiceUnavailable("OpenSearch is not configured.")
    import boto3
    from opensearchpy import OpenSearch, AWSV4SignerAuth, RequestsHttpConnection

    session = boto3.Session(
        aws_access_key_id=settings.opensearch_access_key,
        aws_secret_access_key=settings.opensearch_secret_key,
        region_name=settings.aws_region,
    )
    auth = AWSV4SignerAuth(session.get_credentials(), settings.aws_region, "es")
    parsed = urlparse(settings.opensearch_endpoint)
    return OpenSearch(
        hosts=[{"host": parsed.hostname, "port": parsed.port or 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=15,
    )


def index_name() -> str:
    return settings.opensearch_index
