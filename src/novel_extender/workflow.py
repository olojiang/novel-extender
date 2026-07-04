from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from novel_extender.chapters import (
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_OVERLAP_CHARS,
    Chapter,
    safe_source_stem,
    split_chapters,
    split_into_chunks,
)
from novel_extender.context import ContinuationContext, RetrievedChapter, build_continuation_context
from novel_extender.generation import ChatGenerationResult


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class ChapterStore(Protocol):
    def upsert_chapters(self, chapters: list[Chapter], embeddings: list[list[float]]) -> None:
        ...


class QueryableChapterStore(ChapterStore, Protocol):
    def query(
        self,
        *,
        query_embedding: list[float],
        top_k: int,
        source_path: str | None = None,
    ) -> list[RetrievedChapter]:
        ...


class ChatClient(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ChatGenerationResult:
        ...


class RunLogger(Protocol):
    def event(self, stage: str, event: str, **fields) -> None:
        ...


@dataclass(frozen=True)
class IngestResult:
    source_path: str
    chapter_count: int
    stored_count: int


@dataclass(frozen=True)
class GenerationWorkflowResult:
    source_path: str
    mode: str
    text: str
    prompt: str
    recent_chapter_ids: tuple[str, ...]
    retrieved_chapter_ids: tuple[str, ...]
    post_check: GenerationPostCheck
    memory_updated: bool = False


@dataclass(frozen=True)
class GenerationPostCheck:
    ok: bool
    issues: tuple[str, ...] = ()


def ingest_novel(
    novel_path: str | Path,
    embeddings: EmbeddingClient,
    store: ChapterStore,
    logger: RunLogger,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> IngestResult:
    path = Path(novel_path).resolve()
    logger.event("ingest", "started", source_path=str(path))
    text = path.read_text(encoding="utf-8")

    chapters = split_chapters(text, source_path=str(path))
    chunks = split_into_chunks(chapters, max_chunk_chars=max_chunk_chars, overlap_chars=overlap_chars)
    logger.event(
        "ingest", "split_completed",
        source_path=str(path), chapter_count=len(chapters), chunk_count=len(chunks),
    )

    vectors = embeddings.embed_texts([chunk.text for chunk in chunks]) if chunks else []
    logger.event("ingest", "embedding_completed", source_path=str(path), embedding_count=len(vectors))

    store.upsert_chapters(chunks, vectors)
    logger.event(
        "ingest", "completed",
        source_path=str(path), chapter_count=len(chapters), stored_count=len(chunks),
    )
    return IngestResult(source_path=str(path), chapter_count=len(chapters), stored_count=len(chunks))


def generate_from_novel(
    novel_path: str | Path,
    request: str,
    *,
    mode: str,
    embeddings: EmbeddingClient,
    store: QueryableChapterStore,
    chat: ChatClient,
    logger: RunLogger,
    top_k: int = 5,
    recent_count: int = 3,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    prompt_char_budget: int | None = None,
    update_memory: bool = False,
) -> GenerationWorkflowResult:
    _validate_generation_options(
        mode=mode,
        top_k=top_k,
        recent_count=recent_count,
        temperature=temperature,
        max_tokens=max_tokens,
        prompt_char_budget=prompt_char_budget,
    )
    path = Path(novel_path).resolve()
    logger.event("generate", "started", source_path=str(path), mode=mode)
    text = path.read_text(encoding="utf-8")

    chapters = split_chapters(text, source_path=str(path))
    logger.event("generate", "split_completed", source_path=str(path), chapter_count=len(chapters))

    query_embedding = embeddings.embed_texts([request])[0]
    retrieved = store.query(query_embedding=query_embedding, top_k=top_k, source_path=str(path))
    logger.event("generate", "retrieval_completed", source_path=str(path), retrieved_count=len(retrieved))

    current_budget = prompt_char_budget
    context = _build_context(
        request=request,
        chapters=chapters,
        retrieved=retrieved,
        recent_count=recent_count,
        mode=mode,
        prompt_char_budget=current_budget,
    )
    _log_prompt_completed(logger, path=path, context=context, prompt_char_budget=current_budget)

    for attempt in range(4):
        try:
            generation = chat.generate(context.prompt, temperature=temperature, max_tokens=max_tokens)
            break
        except Exception as exc:
            if not _is_context_length_error(exc) or attempt == 3:
                raise
            current_budget = _next_prompt_budget(current_budget, len(context.prompt))
            context = _build_context(
                request=request,
                chapters=chapters,
                retrieved=retrieved,
                recent_count=recent_count,
                mode=mode,
                prompt_char_budget=current_budget,
            )
            logger.event(
                "generate",
                "prompt_retry",
                source_path=str(path),
                reason="context_length_error",
                prompt_char_budget=current_budget,
                prompt_chars=len(context.prompt),
                attempt=attempt + 2,
            )
    post_check = _check_generated_text(generation.text, mode=mode)
    logger.event(
        "generate",
        "post_check_completed",
        source_path=str(path),
        mode=mode,
        ok=post_check.ok,
        issues=list(post_check.issues),
    )
    if not post_check.ok:
        raise ValueError("; ".join(post_check.issues))

    memory_updated = False
    if update_memory:
        generated_chapter = _build_generated_memory_chapter(path=path, chapters=chapters, text=generation.text)
        generated_embedding = embeddings.embed_texts([generated_chapter.text])
        store.upsert_chapters([generated_chapter], generated_embedding)
        memory_updated = True
        logger.event(
            "generate",
            "memory_updated",
            source_path=str(path),
            chapter_id=generated_chapter.chapter_id,
            title=generated_chapter.title,
        )

    logger.event(
        "generate",
        "completed",
        source_path=str(path),
        mode=mode,
        output_chars=len(generation.text),
    )
    return GenerationWorkflowResult(
        source_path=str(path),
        mode=mode,
        text=generation.text,
        prompt=context.prompt,
        recent_chapter_ids=context.recent_chapter_ids,
        retrieved_chapter_ids=context.retrieved_chapter_ids,
        post_check=post_check,
        memory_updated=memory_updated,
    )


def _validate_generation_options(
    *,
    mode: str,
    top_k: int,
    recent_count: int,
    temperature: float,
    max_tokens: int,
    prompt_char_budget: int | None,
) -> None:
    if mode not in {"analysis", "continuation", "rewrite"}:
        raise ValueError("mode must be one of: analysis, continuation, rewrite")
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    if recent_count < 0:
        raise ValueError("recent_count must be greater than or equal to 0")
    if not 0 <= temperature <= 2:
        raise ValueError("temperature must be between 0 and 2")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than 0")
    if prompt_char_budget is not None and prompt_char_budget <= 0:
        raise ValueError("prompt_char_budget must be greater than 0")


_MIN_GENERATION_CHARS = 20
_AI_REFUSAL_MARKERS = (
    "as an ai",
    "as a language model",
    "i cannot",
    "i'm unable to",
    "i apologize",
    "作为一个ai",
    "作为语言模型",
)


def _check_generated_text(text: str, *, mode: str) -> GenerationPostCheck:
    issues: list[str] = []
    stripped = text.strip()
    if not stripped:
        issues.append("generated text is empty")
    elif len(stripped) < _MIN_GENERATION_CHARS:
        issues.append(f"generated text is too short ({len(stripped)} chars)")
    lowered = stripped.lower()
    if any(marker in lowered for marker in _AI_REFUSAL_MARKERS):
        issues.append("generated text contains AI refusal/roleplay markers")
    return GenerationPostCheck(ok=not issues, issues=tuple(issues))


def _build_generated_memory_chapter(*, path: Path, chapters: list[Chapter], text: str) -> Chapter:
    next_index = max((chapter.index for chapter in chapters), default=0) + 1
    source_stem = safe_source_stem(str(path))
    title = _generated_title(text, default=f"生成章节 {next_index}")
    return Chapter(
        chapter_id=f"{source_stem}-generated-ch{next_index:03d}",
        index=next_index,
        title=title,
        text=text.strip(),
        source_path=str(path),
    )


def _generated_title(text: str, *, default: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line and len(first_line) <= 80:
        return first_line
    return default


def _build_context(
    *,
    request: str,
    chapters: list[Chapter],
    retrieved: list[RetrievedChapter],
    recent_count: int,
    mode: str,
    prompt_char_budget: int | None,
) -> ContinuationContext:
    return build_continuation_context(
        user_request=request,
        chapters=chapters,
        retrieved=retrieved,
        recent_count=recent_count,
        mode=mode,
        prompt_char_budget=prompt_char_budget,
    )


def _log_prompt_completed(logger: RunLogger, *, path: Path, context, prompt_char_budget: int | None) -> None:
    logger.event(
        "generate",
        "prompt_completed",
        source_path=str(path),
        recent_chapter_ids=list(context.recent_chapter_ids),
        retrieved_chapter_ids=list(context.retrieved_chapter_ids),
        prompt_char_budget=prompt_char_budget,
        prompt_chars=len(context.prompt),
        prompt_truncated=context.truncated,
    )


_CONTEXT_LENGTH_PATTERNS = (
    "context length",
    "context_length",
    "tokens to keep",
    "max_tokens",
    "prompt is too long",
    "token limit",
    "maximum context",
    "input too long",
    "reduce the length",
    "too many tokens",
    "exceeds the model",
)


def _is_context_length_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(pattern in message for pattern in _CONTEXT_LENGTH_PATTERNS)


def _next_prompt_budget(current_budget: int | None, current_prompt_chars: int) -> int:
    if current_budget is None:
        return max(1000, current_prompt_chars // 2)
    return max(1000, current_budget // 2)
