from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from novel_extender.chapters import (
    CHAPTER_HEADING_RE,
    Chapter,
    safe_source_stem,
    split_chapters,
)
from novel_extender.context import build_continuation_context
from novel_extender.embeddings import OpenAIEmbeddingClient
from novel_extender.generation import OpenAIChatClient
from novel_extender.openai_validator import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    ensure_local_base_url,
    validate_openai_compat,
)
from novel_extender.run_logging import JsonlRunLogger
from novel_extender.utils import write_text as _write_text
from novel_extender.vector_store import ChromaNovelStore
from novel_extender.workflow import generate_from_novel, ingest_novel

logger = logging.getLogger(__name__)


def _resolve_project_root() -> Path:
    return Path.cwd()


PROJECT_ROOT = _resolve_project_root()
WEB_INPUT_DIR = PROJECT_ROOT / ".novel_extender" / "web_inputs"
WEB_OUTPUT_DIR = PROJECT_ROOT / ".novel_extender" / "web_outputs"

MAX_UPLOAD_CHARS = 5_000_000

_append_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class PrepareFileRequest(_CamelModel):
    filename: str
    text: str
    novel_id: str | None = Field(default=None, alias="novelId")


class ValidateRequest(_CamelModel):
    base_url: str = Field(default=DEFAULT_BASE_URL, alias="baseUrl")
    api_key: str = Field(default=DEFAULT_API_KEY, alias="apiKey")
    chat_model: str = Field(default=DEFAULT_CHAT_MODEL, alias="chatModel")
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL, alias="embeddingModel")
    timeout: float = 30.0


class IngestRequest(_CamelModel):
    base_url: str = Field(default=DEFAULT_BASE_URL, alias="baseUrl")
    api_key: str = Field(default=DEFAULT_API_KEY, alias="apiKey")
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL, alias="embeddingModel")
    novel_path: str = Field(alias="novelPath")
    db_path: str = Field(default="", alias="dbPath")
    collection: str = "novel_chapters"
    log_dir: str = Field(default="", alias="logDir")
    timeout: float = 60.0


class RetrieveRequest(_CamelModel):
    base_url: str = Field(default=DEFAULT_BASE_URL, alias="baseUrl")
    api_key: str = Field(default=DEFAULT_API_KEY, alias="apiKey")
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL, alias="embeddingModel")
    db_path: str = Field(default="", alias="dbPath")
    collection: str = "novel_chapters"
    query: str
    top_k: int = Field(default=5, alias="topK", gt=0)
    novel_path: str = Field(default="", alias="novelPath")
    timeout: float = 60.0


VALID_MODES = Literal["analysis", "continuation", "rewrite"]


class BuildContextRequest(_CamelModel):
    base_url: str = Field(default=DEFAULT_BASE_URL, alias="baseUrl")
    api_key: str = Field(default=DEFAULT_API_KEY, alias="apiKey")
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL, alias="embeddingModel")
    db_path: str = Field(default="", alias="dbPath")
    collection: str = "novel_chapters"
    novel_path: str = Field(alias="novelPath")
    request: str
    top_k: int = Field(default=5, alias="topK", gt=0)
    recent_count: int = Field(default=3, alias="recentCount", ge=0)
    mode: VALID_MODES = "continuation"
    prompt_char_budget: int | None = Field(default=None, alias="promptCharBudget", gt=0)
    timeout: float = 60.0


class GenerateRequest(_CamelModel):
    base_url: str = Field(default=DEFAULT_BASE_URL, alias="baseUrl")
    api_key: str = Field(default=DEFAULT_API_KEY, alias="apiKey")
    chat_model: str = Field(default=DEFAULT_CHAT_MODEL, alias="chatModel")
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL, alias="embeddingModel")
    db_path: str = Field(default="", alias="dbPath")
    collection: str = "novel_chapters"
    novel_path: str = Field(alias="novelPath")
    request: str
    top_k: int = Field(default=5, alias="topK", gt=0)
    recent_count: int = Field(default=3, alias="recentCount", ge=0)
    mode: VALID_MODES = "continuation"
    prompt_char_budget: int | None = Field(default=None, alias="promptCharBudget", gt=0)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, alias="maxTokens", gt=0)
    timeout: float = 120.0
    update_memory: bool = Field(default=False, alias="updateMemory")
    output_path: str = Field(default="", alias="outputPath")
    prompt_output_path: str = Field(default="", alias="promptOutputPath")
    log_dir: str = Field(default="", alias="logDir")
    output_dir: str = Field(default="", alias="outputDir")


class AppendOutputRequest(_CamelModel):
    base_url: str = Field(default=DEFAULT_BASE_URL, alias="baseUrl")
    api_key: str = Field(default=DEFAULT_API_KEY, alias="apiKey")
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL, alias="embeddingModel")
    db_path: str = Field(default="", alias="dbPath")
    collection: str = "novel_chapters"
    novel_path: str = Field(alias="novelPath")
    text: str
    mode: VALID_MODES = "continuation"
    update_memory: bool = Field(default=False, alias="updateMemory")
    log_dir: str = Field(default="", alias="logDir")
    timeout: float = 60.0


class GenerateSeriesRequest(GenerateRequest):
    chapter_batch_size: int = Field(default=2, alias="chapterBatchSize", gt=0, le=20)
    append_to_novel: bool = Field(default=True, alias="appendToNovel")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="novel-extender", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
    )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": str(exc)},
        )

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(_request: Request, exc: FileNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": str(exc)},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(_request: Request, exc: Exception):
        logger.exception("Unhandled error in request handler")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Internal server error"},
        )

    # ----- GET endpoints (no blocking I/O → async is fine) -----

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/defaults")
    async def defaults():
        return {"ok": True, **_defaults()}

    # ----- POST endpoints (blocking I/O → plain def so FastAPI runs them in a threadpool) -----

    @app.post("/api/prepare-file")
    def prepare_file(body: PrepareFileRequest):
        payload = _prepare_file(body)
        return {"ok": True, **payload}

    @app.post("/api/validate-openai")
    def validate_openai(body: ValidateRequest):
        payload = _validate(body)
        return {"ok": True, **payload}

    @app.post("/api/ingest")
    def ingest(body: IngestRequest):
        payload = _ingest(body)
        return {"ok": True, **payload}

    @app.post("/api/retrieve")
    def retrieve(body: RetrieveRequest):
        payload = _retrieve(body)
        return {"ok": True, **payload}

    @app.post("/api/build-context")
    def build_context(body: BuildContextRequest):
        payload = _build_context(body)
        return {"ok": True, **payload}

    @app.post("/api/generate")
    def generate(body: GenerateRequest):
        payload = _generate(body)
        return {"ok": True, **payload}

    @app.post("/api/append-output")
    def append_output(body: AppendOutputRequest):
        payload = _append_output(body)
        return {"ok": True, **payload}

    @app.post("/api/generate-series")
    def generate_series(body: GenerateSeriesRequest):
        payload = _generate_series(body)
        return {"ok": True, **payload}

    # ----- SPA static fallback -----

    resolved_static = static_dir or (PROJECT_ROOT / "web" / "dist")
    if resolved_static.exists():
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            candidate = (resolved_static / full_path).resolve()
            static_root = resolved_static.resolve()
            if candidate.is_relative_to(static_root) and candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            index = resolved_static / "index.html"
            if index.exists():
                return FileResponse(index)
            raise HTTPException(status_code=404, detail="frontend build not found")
    else:
        @app.get("/{full_path:path}")
        async def no_static(full_path: str):
            raise HTTPException(
                status_code=404,
                detail="frontend build not found; run `pnpm --dir web build` or use the Vite dev server",
            )

    return app


# ---------------------------------------------------------------------------
# Handler implementations (kept synchronous for simplicity)
# ---------------------------------------------------------------------------

def _defaults() -> dict[str, Any]:
    return {
        "baseUrl": DEFAULT_BASE_URL,
        "apiKey": DEFAULT_API_KEY,
        "chatModel": DEFAULT_CHAT_MODEL,
        "embeddingModel": DEFAULT_EMBEDDING_MODEL,
        "novelPath": str(PROJECT_ROOT / "examples" / "novel.txt"),
        "dbPath": str(PROJECT_ROOT / ".novel_extender" / "tutorial_chroma"),
        "collection": "tutorial_chapters",
        "outputDir": str(WEB_OUTPUT_DIR),
        "logDir": str(WEB_OUTPUT_DIR / "logs"),
        "topK": 5,
        "recentCount": 3,
        "promptCharBudget": 12000,
        "temperature": 0.7,
        "maxTokens": 4096,
        "chapterBatchSize": 2,
    }


def _prepare_file(body: PrepareFileRequest) -> dict[str, Any]:
    if len(body.text) > MAX_UPLOAD_CHARS:
        raise ValueError(
            f"uploaded text exceeds the {MAX_UPLOAD_CHARS:,} character limit "
            f"({len(body.text):,} chars)"
        )
    display_id = safe_source_stem(str(body.novel_id or body.filename))
    storage_id = _ascii_slug(display_id, fallback_prefix="novel")
    WEB_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = WEB_INPUT_DIR / f"{storage_id}.txt"
    path.write_text(body.text, encoding="utf-8")
    chapters = split_chapters(body.text, source_path=str(path))
    return {
        "novelPath": str(path),
        "dbPath": str(PROJECT_ROOT / ".novel_extender" / f"{storage_id}_chroma"),
        "collection": _collection_name(f"{storage_id}_chapters"),
        "outputDir": str(WEB_OUTPUT_DIR / storage_id),
        "logDir": str(WEB_OUTPUT_DIR / storage_id / "logs"),
        "chapterCount": len(chapters),
        "chapters": [
            {"id": ch.chapter_id, "title": ch.title, "chars": ch.char_count}
            for ch in chapters
        ],
    }


def _validate(body: ValidateRequest) -> dict[str, Any]:
    report = validate_openai_compat(
        base_url=_ensure_local(body.base_url),
        api_key=body.api_key,
        chat_model=body.chat_model,
        embedding_model=body.embedding_model,
        timeout=body.timeout,
    )
    return {
        "valid": report.ok,
        "baseUrl": report.base_url,
        "availableModels": list(report.available_models),
        "chat": report.chat.__dict__,
        "embedding": report.embedding.__dict__,
    }


def _ingest(body: IngestRequest) -> dict[str, Any]:
    clients = _embedding_and_store_from(body.base_url, body.api_key, body.embedding_model, body.db_path, body.collection, body.timeout)
    log_dir = Path(body.log_dir or str(WEB_OUTPUT_DIR / "logs"))
    run_logger = JsonlRunLogger(log_dir=log_dir)
    result = ingest_novel(body.novel_path, clients["embedding"], clients["store"], run_logger)
    return {
        "chapterCount": result.chapter_count,
        "storedCount": result.stored_count,
        "sourcePath": result.source_path,
        "logPath": str(run_logger.path),
    }


def _retrieve(body: RetrieveRequest) -> dict[str, Any]:
    clients = _embedding_and_store_from(body.base_url, body.api_key, body.embedding_model, body.db_path, body.collection, body.timeout)
    query_embedding = clients["embedding"].embed_texts([body.query])[0]
    source_path = body.novel_path or None
    retrieved = clients["store"].query(query_embedding=query_embedding, top_k=body.top_k, source_path=source_path)
    return {"items": [_retrieved_json(item) for item in retrieved]}


def _build_context(body: BuildContextRequest) -> dict[str, Any]:
    clients = _embedding_and_store_from(body.base_url, body.api_key, body.embedding_model, body.db_path, body.collection, body.timeout)
    path = Path(body.novel_path)
    text = path.read_text(encoding="utf-8")
    chapters = split_chapters(text, source_path=str(path))
    query_embedding = clients["embedding"].embed_texts([body.request])[0]
    retrieved = clients["store"].query(
        query_embedding=query_embedding,
        top_k=body.top_k,
        source_path=str(path),
    )
    context = build_continuation_context(
        user_request=body.request,
        chapters=chapters,
        retrieved=retrieved,
        recent_count=body.recent_count,
        mode=body.mode,
        prompt_char_budget=body.prompt_char_budget,
    )
    return {
        "prompt": context.prompt,
        "recentChapterIds": list(context.recent_chapter_ids),
        "retrievedChapterIds": list(context.retrieved_chapter_ids),
        "truncated": context.truncated,
    }


def _generate(body: GenerateRequest) -> dict[str, Any]:
    clients = _embedding_and_store_from(body.base_url, body.api_key, body.embedding_model, body.db_path, body.collection, body.timeout)
    chat = OpenAIChatClient(
        base_url=_ensure_local(body.base_url),
        api_key=body.api_key,
        model=body.chat_model,
        timeout=body.timeout,
    )
    log_dir = Path(body.log_dir or str(WEB_OUTPUT_DIR / "logs"))
    run_logger = JsonlRunLogger(log_dir=log_dir)
    result = generate_from_novel(
        body.novel_path,
        body.request,
        mode=body.mode,
        embeddings=clients["embedding"],
        store=clients["store"],
        chat=chat,
        logger=run_logger,
        top_k=body.top_k,
        recent_count=body.recent_count,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        prompt_char_budget=body.prompt_char_budget,
        update_memory=body.update_memory,
    )
    output_path = body.output_path
    prompt_output_path = body.prompt_output_path
    if output_path:
        _write_text(Path(output_path), result.text)
    if prompt_output_path:
        _write_text(Path(prompt_output_path), result.prompt)
    return {
        "text": result.text,
        "prompt": result.prompt,
        "recentChapterIds": list(result.recent_chapter_ids),
        "retrievedChapterIds": list(result.retrieved_chapter_ids),
        "postCheck": {"ok": result.post_check.ok, "issues": list(result.post_check.issues)},
        "memoryUpdated": result.memory_updated,
        "outputPath": output_path,
        "promptOutputPath": prompt_output_path,
        "logPath": str(run_logger.path),
    }


def _append_output(body: AppendOutputRequest) -> dict[str, Any]:
    clients = _embedding_and_store_from(body.base_url, body.api_key, body.embedding_model, body.db_path, body.collection, body.timeout)
    log_dir = Path(body.log_dir or str(WEB_OUTPUT_DIR / "logs"))
    run_logger = JsonlRunLogger(log_dir=log_dir)
    result = _append_generated_chapter(
        novel_path=Path(body.novel_path),
        text=body.text,
        mode=body.mode,
        embeddings=clients["embedding"],
        store=clients["store"],
        run_logger=run_logger,
        update_memory=body.update_memory,
    )
    return {**result, "logPath": str(run_logger.path)}


def _generate_series(body: GenerateSeriesRequest) -> dict[str, Any]:
    count = min(body.chapter_batch_size, 20)
    clients = _embedding_and_store_from(body.base_url, body.api_key, body.embedding_model, body.db_path, body.collection, body.timeout)
    chat = OpenAIChatClient(
        base_url=_ensure_local(body.base_url),
        api_key=body.api_key,
        model=body.chat_model,
        timeout=body.timeout,
    )
    log_dir = Path(body.log_dir or str(WEB_OUTPUT_DIR / "logs"))
    run_logger = JsonlRunLogger(log_dir=log_dir)
    base_request = body.request
    mode = body.mode
    append_to_novel = body.append_to_novel
    update_memory = body.update_memory
    generated_items: list[dict[str, Any]] = []

    for index in range(1, count + 1):
        request = _series_request(base_request, index=index, count=count, mode=mode)
        result = generate_from_novel(
            body.novel_path,
            request,
            mode=mode,
            embeddings=clients["embedding"],
            store=clients["store"],
            chat=chat,
            logger=run_logger,
            top_k=body.top_k,
            recent_count=body.recent_count,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            prompt_char_budget=body.prompt_char_budget,
            update_memory=update_memory and not append_to_novel,
        )
        append_result = None
        if append_to_novel:
            append_result = _append_generated_chapter(
                novel_path=Path(body.novel_path),
                text=result.text,
                mode=mode,
                embeddings=clients["embedding"],
                store=clients["store"],
                run_logger=run_logger,
                update_memory=update_memory,
            )
        generated_items.append(
            {
                "index": index,
                "text": result.text,
                "prompt": result.prompt,
                "recentChapterIds": list(result.recent_chapter_ids),
                "retrievedChapterIds": list(result.retrieved_chapter_ids),
                "postCheck": {"ok": result.post_check.ok, "issues": list(result.post_check.issues)},
                "memoryUpdated": result.memory_updated or bool(append_result and append_result["memoryUpdated"]),
                "append": append_result,
            }
        )

    output_path = body.output_path
    prompt_output_path = body.prompt_output_path
    combined_text = "\n\n".join(item["text"].strip() for item in generated_items)
    combined_prompt = "\n\n".join(
        f"===== chapter {item['index']} prompt =====\n{item['prompt'].strip()}" for item in generated_items
    )
    if output_path:
        _write_text(Path(output_path), combined_text)
    if prompt_output_path:
        _write_text(Path(prompt_output_path), combined_prompt)

    last = generated_items[-1]
    all_ok = all(item["postCheck"]["ok"] for item in generated_items)
    all_issues: list[str] = []
    for item in generated_items:
        all_issues.extend(item["postCheck"]["issues"])
    return {
        "text": combined_text,
        "prompt": combined_prompt,
        "recentChapterIds": last["recentChapterIds"],
        "retrievedChapterIds": last["retrievedChapterIds"],
        "postCheck": {"ok": all_ok, "issues": all_issues},
        "memoryUpdated": any(item["memoryUpdated"] for item in generated_items),
        "outputPath": output_path,
        "promptOutputPath": prompt_output_path,
        "logPath": str(run_logger.path),
        "chapters": generated_items,
        "appendedCount": sum(1 for item in generated_items if item["append"]),
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _append_generated_chapter(
    *,
    novel_path: Path,
    text: str,
    mode: str,
    embeddings: Any,
    store: Any,
    run_logger: JsonlRunLogger,
    update_memory: bool,
) -> dict[str, Any]:
    with _append_lock:
        before_text = novel_path.read_text(encoding="utf-8") if novel_path.exists() else ""
        before_chapters = split_chapters(before_text, source_path=str(novel_path))
        append_text = _chapter_text_for_append(text, mode=mode, previous_chapters=before_chapters)
        suffix = "\n\n" if before_text.strip() else ""
        combined = f"{before_text.rstrip()}{suffix}{append_text.strip()}\n"
        novel_path.parent.mkdir(parents=True, exist_ok=True)
        novel_path.write_text(combined, encoding="utf-8")

        after_chapters = split_chapters(combined, source_path=str(novel_path))
        if not after_chapters:
            raise ValueError("append did not produce a readable chapter")
        appended = after_chapters[-1]
        memory_updated = False
        if update_memory:
            store.upsert_chapters([appended], embeddings.embed_texts([appended.text]))
            memory_updated = True
    run_logger.event(
        "append",
        "completed",
        source_path=str(novel_path),
        chapter_id=appended.chapter_id,
        title=appended.title,
        chapter_count=len(after_chapters),
        memory_updated=memory_updated,
    )
    return {
        "novelPath": str(novel_path),
        "chapterCount": len(after_chapters),
        "appendedChapter": _chapter_json(appended),
        "memoryUpdated": memory_updated,
    }


def _chapter_text_for_append(text: str, *, mode: str, previous_chapters: list[Chapter]) -> str:
    stripped = text.strip()
    if mode != "continuation" or _has_chapter_heading(stripped):
        return stripped
    next_index = max((chapter.index for chapter in previous_chapters), default=0) + 1
    return f"第{next_index}章 续写\n{stripped}"


def _has_chapter_heading(text: str) -> bool:
    return any(CHAPTER_HEADING_RE.finditer(text))


def _chapter_json(chapter: Chapter) -> dict[str, Any]:
    return {
        "id": chapter.chapter_id,
        "index": chapter.index,
        "title": chapter.title,
        "chars": chapter.char_count,
    }


def _series_request(request: str, *, index: int, count: int, mode: str) -> str:
    if mode != "continuation":
        return request
    return (
        f"{request}\n\n"
        f"连续续写任务：本次是第 {index}/{count} 次生成。"
        "请只生成紧接当前最后一章的一章完整正文，不要一次生成多章；"
        "下一次生成会在这一章保存后继续。"
    )


@lru_cache(maxsize=16)
def _get_chroma_store(db_path: str, collection: str) -> ChromaNovelStore:
    return ChromaNovelStore(db_path=db_path, collection=collection)


def _embedding_and_store_from(
    base_url: str, api_key: str, embedding_model: str,
    db_path: str, collection: str, timeout: float,
) -> dict[str, Any]:
    validated_url = _ensure_local(base_url)
    embedding = OpenAIEmbeddingClient(
        base_url=validated_url,
        api_key=api_key,
        model=embedding_model,
        timeout=timeout,
    )
    resolved_db_path = db_path or str(PROJECT_ROOT / ".novel_extender" / "chroma")
    resolved_collection = _collection_name(collection or "novel_chapters")
    store = _get_chroma_store(resolved_db_path, resolved_collection)
    return {"embedding": embedding, "store": store}


def _ensure_local(base_url: str) -> str:
    return ensure_local_base_url(base_url or DEFAULT_BASE_URL)


def _collection_name(value: str) -> str:
    slug = _ascii_slug(value, fallback_prefix="novel")
    if not slug.endswith("_chapters"):
        slug = f"{slug}_chapters"
    return slug[:512].strip("._-") or "novel_chapters"


def _ascii_slug(value: str, *, fallback_prefix: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("._-")
    if not slug:
        slug = f"{fallback_prefix}-{digest}"
    elif len(slug) < 3:
        slug = f"{slug}-{digest}"
    if not slug[0].isalnum():
        slug = f"{fallback_prefix}-{slug}"
    if not slug[-1].isalnum():
        slug = f"{slug}-{digest}"
    return slug


def _retrieved_json(item: Any) -> dict[str, Any]:
    return {
        "chapterId": item.chapter_id,
        "title": item.title,
        "index": item.index,
        "text": item.text,
        "distance": item.distance,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="novel-extender-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--static-dir", default=str(PROJECT_ROOT / "web" / "dist"))
    args = parser.parse_args(argv)

    app = create_app(static_dir=Path(args.static_dir))
    print(f"novel-extender web API listening on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
