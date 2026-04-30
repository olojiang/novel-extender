from __future__ import annotations

import argparse
import sys
from pathlib import Path

from novel_extender.chapters import split_chapters
from novel_extender.context import build_continuation_context
from novel_extender.embeddings import OpenAIEmbeddingClient
from novel_extender.generation import OpenAIChatClient
from novel_extender.openai_validator import (
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="novel-extender")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate-openai",
        help="Validate OpenAI-compatible chat and embedding models.",
    )
    validate_parser.add_argument("--base-url", default=DEFAULT_BASE_URL, type=ensure_local_base_url)
    validate_parser.add_argument("--api-key", default="not-needed")
    validate_parser.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    validate_parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    validate_parser.add_argument("--timeout", type=float, default=30.0)

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Split by chapter, embed, and store a novel in Chroma.",
    )
    ingest_parser.add_argument("novel_path")
    ingest_parser.add_argument("--base-url", default=DEFAULT_BASE_URL, type=ensure_local_base_url)
    ingest_parser.add_argument("--api-key", default="not-needed")
    ingest_parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    ingest_parser.add_argument("--db-path", default=".novel_extender/chroma")
    ingest_parser.add_argument("--collection", default="novel_chapters")
    ingest_parser.add_argument("--log-dir", default="logs")
    ingest_parser.add_argument("--timeout", type=float, default=60.0)

    retrieve_parser = subparsers.add_parser(
        "retrieve",
        help="Retrieve relevant chapters from the local Chroma store.",
    )
    retrieve_parser.add_argument("query")
    retrieve_parser.add_argument("--base-url", default=DEFAULT_BASE_URL, type=ensure_local_base_url)
    retrieve_parser.add_argument("--api-key", default="not-needed")
    retrieve_parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    retrieve_parser.add_argument("--db-path", default=".novel_extender/chroma")
    retrieve_parser.add_argument("--collection", default="novel_chapters")
    retrieve_parser.add_argument("--top-k", type=_positive_int, default=5)
    retrieve_parser.add_argument("--novel-path", default=None, help="Filter results to this novel source path.")
    retrieve_parser.add_argument("--timeout", type=float, default=60.0)

    context_parser = subparsers.add_parser(
        "build-context",
        help="Assemble a continuation prompt from recent chapters and Chroma retrieval.",
    )
    context_parser.add_argument("novel_path")
    context_parser.add_argument("request")
    context_parser.add_argument("--base-url", default=DEFAULT_BASE_URL, type=ensure_local_base_url)
    context_parser.add_argument("--api-key", default="not-needed")
    context_parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    context_parser.add_argument("--db-path", default=".novel_extender/chroma")
    context_parser.add_argument("--collection", default="novel_chapters")
    context_parser.add_argument("--top-k", type=_positive_int, default=5)
    context_parser.add_argument("--recent-count", type=_non_negative_int, default=3)
    context_parser.add_argument(
        "--prompt-char-budget",
        type=_positive_int,
        default=None,
        help="Optional max prompt size in characters; defaults to no client-side truncation.",
    )
    context_parser.add_argument(
        "--mode",
        choices=("analysis", "continuation", "rewrite"),
        default="continuation",
        help="Prompt type to assemble.",
    )
    context_parser.add_argument("--timeout", type=float, default=60.0)

    generate_parser = subparsers.add_parser(
        "generate",
        help="Retrieve context, call a chat model, and generate analysis, continuation, or rewrite text.",
    )
    generate_parser.add_argument("novel_path")
    generate_parser.add_argument("request")
    generate_parser.add_argument("--base-url", default=DEFAULT_BASE_URL, type=ensure_local_base_url)
    generate_parser.add_argument("--api-key", default="not-needed")
    generate_parser.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    generate_parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    generate_parser.add_argument("--db-path", default=".novel_extender/chroma")
    generate_parser.add_argument("--collection", default="novel_chapters")
    generate_parser.add_argument("--top-k", type=_positive_int, default=5)
    generate_parser.add_argument("--recent-count", type=_non_negative_int, default=3)
    generate_parser.add_argument(
        "--prompt-char-budget",
        type=_positive_int,
        default=None,
        help="Optional max prompt size in characters; defaults to no client-side truncation.",
    )
    generate_parser.add_argument(
        "--mode",
        choices=("analysis", "continuation", "rewrite"),
        default="continuation",
        help="Generation type to run.",
    )
    generate_parser.add_argument("--temperature", type=_temperature, default=0.7)
    generate_parser.add_argument("--max-tokens", type=_positive_int, default=4096)
    generate_parser.add_argument("--timeout", type=float, default=120.0)
    generate_parser.add_argument("--log-dir", default="logs")
    generate_parser.add_argument("--output", help="Write generated text to this file instead of stdout.")
    generate_parser.add_argument("--prompt-output", help="Also write the assembled prompt to this file.")
    generate_parser.add_argument(
        "--update-memory",
        action="store_true",
        help="Store the generated chapter back into the selected Chroma collection after post-checks pass.",
    )

    args = parser.parse_args(argv)

    if args.command == "validate-openai":
        report = validate_openai_compat(
            base_url=args.base_url,
            api_key=args.api_key,
            chat_model=args.chat_model,
            embedding_model=args.embedding_model,
            timeout=args.timeout,
        )
        _print_report(report)
        return 0 if report.ok else 1

    if args.command == "ingest":
        logger = JsonlRunLogger(log_dir=args.log_dir)
        embedding_client = OpenAIEmbeddingClient(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.embedding_model,
            timeout=args.timeout,
        )
        store = ChromaNovelStore(db_path=args.db_path, collection=args.collection)
        result = ingest_novel(Path(args.novel_path), embedding_client, store, logger)
        print(f"Ingested {result.chapter_count} chapters into Chroma.")
        print(f"Log: {logger.path}")
        return 0

    if args.command == "retrieve":
        embedding_client = OpenAIEmbeddingClient(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.embedding_model,
            timeout=args.timeout,
        )
        store = ChromaNovelStore(db_path=args.db_path, collection=args.collection)
        query_embedding = embedding_client.embed_texts([args.query])[0]
        source_path = str(Path(args.novel_path).resolve()) if args.novel_path else None
        for item in store.query(query_embedding=query_embedding, top_k=args.top_k, source_path=source_path):
            print(f"{item.chapter_id}\t{item.title}\tdistance={item.distance}")
        return 0

    if args.command == "build-context":
        path = Path(args.novel_path)
        text = path.read_text(encoding="utf-8")
        chapters = split_chapters(text, source_path=str(path))
        embedding_client = OpenAIEmbeddingClient(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.embedding_model,
            timeout=args.timeout,
        )
        store = ChromaNovelStore(db_path=args.db_path, collection=args.collection)
        query_embedding = embedding_client.embed_texts([args.request])[0]
        retrieved = store.query(query_embedding=query_embedding, top_k=args.top_k, source_path=str(path))
        context = build_continuation_context(
            user_request=args.request,
            chapters=chapters,
            retrieved=retrieved,
            recent_count=args.recent_count,
            mode=args.mode,
            prompt_char_budget=args.prompt_char_budget,
        )
        print(context.prompt)
        return 0

    if args.command == "generate":
        logger = JsonlRunLogger(log_dir=args.log_dir)
        embedding_client = OpenAIEmbeddingClient(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.embedding_model,
            timeout=args.timeout,
        )
        store = ChromaNovelStore(db_path=args.db_path, collection=args.collection)
        chat_client = OpenAIChatClient(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.chat_model,
            timeout=args.timeout,
        )
        result = generate_from_novel(
            Path(args.novel_path),
            args.request,
            mode=args.mode,
            embeddings=embedding_client,
            store=store,
            chat=chat_client,
            logger=logger,
            top_k=args.top_k,
            recent_count=args.recent_count,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            prompt_char_budget=args.prompt_char_budget,
            update_memory=args.update_memory,
        )
        if args.prompt_output:
            _write_text(Path(args.prompt_output), result.prompt)
        if args.output:
            _write_text(Path(args.output), result.text)
            print(f"Wrote generated text: {args.output}")
            print(f"Log: {logger.path}")
        else:
            print(result.text)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _print_report(report: object) -> None:
    print(f"Base URL: {report.base_url}")
    print("Available models:")
    for model in report.available_models:
        print(f"  - {model}")
    print()
    print(f"Chat model: {report.chat.model}")
    print(f"  Status: {'OK' if report.chat.ok else 'FAILED'}")
    print(f"  Reason: {report.chat.reason}")
    print(f"Embedding model: {report.embedding.model}")
    print(f"  Status: {'OK' if report.embedding.ok else 'FAILED'}")
    print(f"  Reason: {report.embedding.reason}")


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return number


def _temperature(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 2:
        raise argparse.ArgumentTypeError("must be between 0 and 2")
    return number


if __name__ == "__main__":
    sys.exit(main())
