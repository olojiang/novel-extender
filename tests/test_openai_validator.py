from types import SimpleNamespace

import pytest

from novel_extender.openai_validator import is_local_base_url, validate_openai_compat


class FakeModels:
    def __init__(self, model_ids):
        self._model_ids = model_ids

    def list(self):
        return SimpleNamespace(data=[SimpleNamespace(id=model_id) for model_id in self._model_ids])


class FakeChatCompletions:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])


class FakeEmbeddings:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])


class FakeClient:
    def __init__(self, model_ids, chat_error=None, embedding_error=None):
        self.models = FakeModels(model_ids)
        self.chat = SimpleNamespace(completions=FakeChatCompletions(chat_error))
        self.embeddings = FakeEmbeddings(embedding_error)


def test_reports_both_models_available_when_listed_and_probe_calls_succeed():
    client = FakeClient(["chat-model", "embedding-model"])

    report = validate_openai_compat(
        base_url="http://127.0.0.1:1234/v1",
        chat_model="chat-model",
        embedding_model="embedding-model",
        client=client,
    )

    assert report.ok is True
    assert report.chat.ok is True
    assert report.embedding.ok is True
    assert client.chat.completions.calls[0]["model"] == "chat-model"
    assert client.embeddings.calls[0]["model"] == "embedding-model"


def test_reports_missing_models_without_running_probe_calls():
    client = FakeClient(["other-model"])

    report = validate_openai_compat(
        base_url="http://127.0.0.1:1234/v1",
        chat_model="chat-model",
        embedding_model="embedding-model",
        client=client,
    )

    assert report.ok is False
    assert report.chat.reason == "model not found in /models response"
    assert report.embedding.reason == "model not found in /models response"
    assert client.chat.completions.calls == []
    assert client.embeddings.calls == []


def test_reports_probe_failure_for_listed_chat_model():
    client = FakeClient(["chat-model", "embedding-model"], chat_error=RuntimeError("chat failed"))

    report = validate_openai_compat(
        base_url="http://127.0.0.1:1234/v1",
        chat_model="chat-model",
        embedding_model="embedding-model",
        client=client,
    )

    assert report.ok is False
    assert report.chat.ok is False
    assert report.chat.reason == "probe failed: chat failed"
    assert report.embedding.ok is True


def test_rejects_public_model_endpoint_even_with_fake_client():
    client = FakeClient(["chat-model", "embedding-model"])

    with pytest.raises(ValueError, match="local or private-network"):
        validate_openai_compat(
            base_url="https://api.openai.com/v1",
            chat_model="chat-model",
            embedding_model="embedding-model",
            client=client,
        )


def test_identifies_local_and_private_model_endpoints():
    assert is_local_base_url("127.0.0.1:1234")
    assert is_local_base_url("http://localhost:1234/v1")
    assert is_local_base_url("http://192.168.1.10:1234/v1")
    assert is_local_base_url("http://modelbox.local:1234/v1")
    assert not is_local_base_url("https://api.openai.com/v1")
