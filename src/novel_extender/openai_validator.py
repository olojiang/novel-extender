from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from novel_extender.utils import get_attr as _get_attr

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "not-needed"
DEFAULT_CHAT_MODEL = "qwen3.5-9b-uncensored-hauhaucs-aggressive-mlx"
DEFAULT_EMBEDDING_MODEL = "text-embedding-bge-large-zh-v1.5"


@dataclass(frozen=True)
class ModelCheck:
    name: str
    model: str
    ok: bool
    reason: str


@dataclass(frozen=True)
class ValidationReport:
    base_url: str
    available_models: tuple[str, ...]
    chat: ModelCheck
    embedding: ModelCheck

    @property
    def ok(self) -> bool:
        return self.chat.ok and self.embedding.ok


def normalize_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        return DEFAULT_BASE_URL
    if "://" not in value:
        value = f"http://{value}"
    if not value.endswith("/v1"):
        value = f"{value}/v1"
    return value


def ensure_local_base_url(base_url: str) -> str:
    normalized = normalize_base_url(base_url)
    if not is_local_base_url(normalized):
        raise ValueError(
            "base_url must point to a local or private-network OpenAI-compatible service, "
            f"got {normalized!r}"
        )
    return normalized


def is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(normalize_base_url(base_url))
    host = parsed.hostname
    if not host:
        return False

    lowered = host.lower()
    if lowered in {"localhost", "host.docker.internal"} or lowered.endswith(".local"):
        return True

    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False

    if address.is_link_local:
        return False
    return address.is_loopback or address.is_private


def validate_openai_compat(
    *,
    base_url: str = DEFAULT_BASE_URL,
    chat_model: str = DEFAULT_CHAT_MODEL,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    api_key: str = DEFAULT_API_KEY,
    timeout: float = 30.0,
    client: Any | None = None,
) -> ValidationReport:
    base_url = ensure_local_base_url(base_url)
    openai_client = client or OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    available_models = tuple(sorted(_extract_model_ids(openai_client.models.list())))
    available_set = set(available_models)

    chat = _check_chat_model(openai_client, chat_model, available_set)
    embedding = _check_embedding_model(openai_client, embedding_model, available_set)

    return ValidationReport(
        base_url=base_url,
        available_models=available_models,
        chat=chat,
        embedding=embedding,
    )


def _check_chat_model(client: Any, model: str, available_models: set[str]) -> ModelCheck:
    if model not in available_models:
        return ModelCheck("chat", model, False, "model not found in /models response")

    try:
        client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly: ok",
                }
            ],
            max_tokens=8,
            temperature=0,
        )
    except Exception as exc:
        return ModelCheck("chat", model, False, f"probe failed: {exc}")

    return ModelCheck("chat", model, True, "listed and chat completion probe succeeded")


def _check_embedding_model(client: Any, model: str, available_models: set[str]) -> ModelCheck:
    if model not in available_models:
        return ModelCheck("embedding", model, False, "model not found in /models response")

    try:
        response = client.embeddings.create(model=model, input="小说续写模型连通性验证")
        embeddings = _get_attr(response, "data", [])
        if not embeddings:
            return ModelCheck("embedding", model, False, "probe returned no embeddings")
        first_embedding = _get_attr(embeddings[0], "embedding", [])
        if not first_embedding:
            return ModelCheck("embedding", model, False, "probe returned an empty embedding")
    except Exception as exc:
        return ModelCheck("embedding", model, False, f"probe failed: {exc}")

    return ModelCheck("embedding", model, True, "listed and embedding probe succeeded")


def _extract_model_ids(response: Any) -> list[str]:
    models = _get_attr(response, "data", [])
    ids: list[str] = []
    for model in models:
        model_id = _get_attr(model, "id", None)
        if isinstance(model_id, str) and model_id:
            ids.append(model_id)
    return ids


