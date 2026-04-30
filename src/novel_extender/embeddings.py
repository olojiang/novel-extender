from __future__ import annotations

from openai import OpenAI

from novel_extender.openai_validator import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
    ensure_local_base_url,
)


class OpenAIEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = DEFAULT_API_KEY,
        model: str = DEFAULT_EMBEDDING_MODEL,
        timeout: float = 60.0,
        batch_size: int = 32,
    ):
        self.model = model
        self.batch_size = batch_size
        self.client = OpenAI(api_key=api_key, base_url=ensure_local_base_url(base_url), timeout=timeout)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        batch_size = self.batch_size
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = self.client.embeddings.create(model=self.model, input=batch)
            if len(response.data) != len(batch):
                raise ValueError(
                    f"embedding API returned {len(response.data)} vectors "
                    f"for {len(batch)} inputs"
                )
            embeddings.extend(item.embedding for item in response.data)
        return embeddings
