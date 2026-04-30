from __future__ import annotations

from types import SimpleNamespace

from novel_extender.context import RetrievedChapter
from novel_extender.generation import ChatGenerationResult


class FakeEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(index), 0.1] for index, _ in enumerate(texts)]


class FakeStore:
    def __init__(self) -> None:
        self.upserted: list[tuple] = []
        self.queries: list[dict] = []

    def upsert_chapters(self, chapters, embeddings):
        self.upserted.append((chapters, embeddings))

    def query(self, *, query_embedding, top_k, source_path=None):
        self.queries.append({"query_embedding": query_embedding, "top_k": top_k, "source_path": source_path})
        return [
            RetrievedChapter("novel-ch001", "第1章 开端", 1, "第一章正文", 0.1),
        ]


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[SimpleNamespace] = []

    def event(self, stage: str, event: str, **fields) -> None:
        self.events.append(SimpleNamespace(stage=stage, event=event, fields=fields))


class FakeChatClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, prompt: str, *, temperature: float = 0.7, max_tokens: int = 4096) -> ChatGenerationResult:
        self.calls.append({"prompt": prompt, "temperature": temperature, "max_tokens": max_tokens})
        return ChatGenerationResult(text="第3章 新线索\n生成正文。" + "额外内容" * 5, model="chat-model")
