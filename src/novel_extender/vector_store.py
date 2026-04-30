from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from novel_extender.chapters import Chapter
from novel_extender.context import RetrievedChapter


class ChromaNovelStore:
    def __init__(self, *, db_path: str | Path = ".novel_extender/chroma", collection: str = "novel_chapters"):
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.db_path),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(name=collection)

    def upsert_chapters(self, chapters: list[Chapter], embeddings: list[list[float]]) -> None:
        if not chapters:
            return
        if len(chapters) != len(embeddings):
            raise ValueError("chapters and embeddings must have the same length")

        self.collection.upsert(
            ids=[chapter.chapter_id for chapter in chapters],
            documents=[chapter.text for chapter in chapters],
            embeddings=embeddings,
            metadatas=[
                {
                    "title": chapter.title,
                    "index": chapter.index,
                    "source_path": chapter.source_path,
                    "char_count": chapter.char_count,
                }
                for chapter in chapters
            ],
        )

    def query(
        self,
        *,
        query_embedding: list[float],
        top_k: int = 5,
        source_path: str | None = None,
    ) -> list[RetrievedChapter]:
        if top_k <= 0:
            raise ValueError("top_k must be greater than 0")
        query_args: dict[str, Any] = {"query_embeddings": [query_embedding], "n_results": top_k}
        if source_path:
            query_args["where"] = {"source_path": source_path}
        result = self.collection.query(**query_args)
        return _result_to_retrieved(result)


def _result_to_retrieved(result: dict[str, Any]) -> list[RetrievedChapter]:
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    retrieved: list[RetrievedChapter] = []
    for index, chapter_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
        retrieved.append(
            RetrievedChapter(
                chapter_id=chapter_id,
                title=str(metadata.get("title", chapter_id)),
                index=int(metadata.get("index", index + 1)),
                text=documents[index] if index < len(documents) else "",
                distance=distances[index] if index < len(distances) else None,
            )
        )
    return retrieved
