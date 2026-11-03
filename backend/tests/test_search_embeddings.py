"""Embedding call tests; the OpenAI SDK client is mocked, no network."""
from types import SimpleNamespace

import pytest

from app.config import settings
from app.search import embeddings


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_embeddings_model", "test/embed-model")
    monkeypatch.setattr(settings, "embedding_dim", 3)


def test_unconfigured_raises_without_calling_model(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_embeddings_model", None)
    with pytest.raises(embeddings.EmbeddingError):
        embeddings.embed_text("knee pain")


def test_successful_call_returns_vector(configured, monkeypatch):
    class FakeEmbeddings:
        def create(self, **kwargs):
            assert kwargs["model"] == "test/embed-model"
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

    class FakeClient:
        def __init__(self, **kwargs):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr("openai.OpenAI", FakeClient)
    assert embeddings.embed_text("knee pain") == [0.1, 0.2, 0.3]


def test_dimension_mismatch_raises(configured, monkeypatch):
    class FakeEmbeddings:
        def create(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])

    class FakeClient:
        def __init__(self, **kwargs):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr("openai.OpenAI", FakeClient)
    with pytest.raises(embeddings.EmbeddingError, match="dimension"):
        embeddings.embed_text("knee pain")


def test_upstream_error_does_not_expose_message(configured, monkeypatch):
    class FakeEmbeddings:
        def create(self, **kwargs):
            raise RuntimeError("sensitive upstream payload")

    class FakeClient:
        def __init__(self, **kwargs):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr("openai.OpenAI", FakeClient)
    with pytest.raises(embeddings.EmbeddingError) as error:
        embeddings.embed_text("knee pain")
    assert "sensitive" not in str(error.value)
