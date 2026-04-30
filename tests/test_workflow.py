import pytest
from conftest import FakeChatClient, FakeEmbeddingClient, FakeLogger, FakeStore

from novel_extender.generation import ChatGenerationResult
from novel_extender.workflow import generate_from_novel, ingest_novel


class ContextFailOnceChatClient:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, *, temperature=0.7, max_tokens=4096):
        self.calls.append({"prompt": prompt, "temperature": temperature, "max_tokens": max_tokens})
        if len(self.calls) == 1:
            raise RuntimeError("The number of tokens to keep from the initial prompt is greater than the context length")
        return ChatGenerationResult(text="重试后生成正文。" + "额外内容" * 5, model="chat-model")


def test_ingest_splits_embeds_and_upserts_chapters(tmp_path):
    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("第1章 开端\n正文。\n\n第2章 线索\n更多正文。", encoding="utf-8")
    store = FakeStore()
    logger = FakeLogger()

    result = ingest_novel(novel_path, FakeEmbeddingClient(), store, logger)

    assert result.chapter_count == 2
    assert result.stored_count >= 2
    chapters, embeddings = store.upserted[0]
    assert len(chapters) == len(embeddings)
    assert logger.events[-1].event == "completed"


def test_ingest_with_chunking_stores_more_than_chapter_count(tmp_path):
    novel_path = tmp_path / "novel.txt"
    body = "\n\n".join(f"段落{i}。" + "填充文字" * 100 for i in range(10))
    novel_path.write_text(f"第1章 开端\n{body}", encoding="utf-8")
    store = FakeStore()
    logger = FakeLogger()

    result = ingest_novel(novel_path, FakeEmbeddingClient(), store, logger, max_chunk_chars=500, overlap_chars=50)

    assert result.chapter_count == 1
    assert result.stored_count > 1
    chunks, embeddings = store.upserted[0]
    assert len(chunks) == result.stored_count
    assert len(embeddings) == result.stored_count


def test_generate_from_novel_calls_chat_model_with_context_prompt(tmp_path):
    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("第1章 开端\n第一章正文。\n\n第2章 线索\n第二章正文。", encoding="utf-8")
    store = FakeStore()
    logger = FakeLogger()
    chat = FakeChatClient()

    result = generate_from_novel(
        novel_path,
        "续写下一章，重点写新线索。",
        mode="continuation",
        embeddings=FakeEmbeddingClient(),
        store=store,
        chat=chat,
        logger=logger,
        top_k=1,
        recent_count=1,
        temperature=0.2,
        max_tokens=512,
    )

    assert "第3章 新线索" in result.text
    assert result.mode == "continuation"
    assert result.recent_chapter_ids == ("novel-ch002",)
    assert result.retrieved_chapter_ids == ("novel-ch001",)
    assert store.queries == [{"query_embedding": [0.0, 0.1], "top_k": 1, "source_path": str(novel_path)}]
    assert chat.calls[0]["temperature"] == 0.2
    assert chat.calls[0]["max_tokens"] == 512
    assert "【续写要求】" in chat.calls[0]["prompt"]
    assert "续写下一章" in chat.calls[0]["prompt"]
    assert logger.events[-1].stage == "generate"
    assert logger.events[-1].event == "completed"


def test_generate_from_novel_retries_with_shorter_prompt_on_context_length_error(tmp_path):
    novel_path = tmp_path / "novel.txt"
    novel_path.write_text(
        "第1章 开端\n" + ("第一章正文。" * 300) + "\n\n第2章 线索\n" + ("第二章正文。" * 300),
        encoding="utf-8",
    )
    store = FakeStore()
    logger = FakeLogger()
    chat = ContextFailOnceChatClient()

    result = generate_from_novel(
        novel_path,
        "续写下一章，重点写新线索。",
        mode="continuation",
        embeddings=FakeEmbeddingClient(),
        store=store,
        chat=chat,
        logger=logger,
        top_k=1,
        recent_count=2,
        max_tokens=512,
    )

    assert "重试后生成正文。" in result.text
    assert len(chat.calls) == 2
    assert len(chat.calls[1]["prompt"]) < len(chat.calls[0]["prompt"])
    assert any(event.event == "prompt_retry" for event in logger.events)


def test_generate_from_novel_rejects_invalid_generation_parameters(tmp_path):
    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("第1章 开端\n正文。", encoding="utf-8")

    with pytest.raises(ValueError, match="top_k"):
        generate_from_novel(
            novel_path,
            "续写下一章。",
            mode="continuation",
            embeddings=FakeEmbeddingClient(),
            store=FakeStore(),
            chat=FakeChatClient(),
            logger=FakeLogger(),
            top_k=0,
        )


def test_generate_from_novel_validates_generated_text_and_stores_memory_update(tmp_path):
    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("第1章 开端\n第一章正文。\n\n第2章 线索\n第二章正文。", encoding="utf-8")
    store = FakeStore()
    logger = FakeLogger()

    result = generate_from_novel(
        novel_path,
        "续写下一章。",
        mode="continuation",
        embeddings=FakeEmbeddingClient(),
        store=store,
        chat=FakeChatClient(),
        logger=logger,
        top_k=1,
        update_memory=True,
    )

    assert result.post_check.ok is True
    assert result.memory_updated is True
    generated_chapters, generated_embeddings = store.upserted[-1]
    assert generated_chapters[0].chapter_id == "novel-generated-ch003"
    assert generated_chapters[0].title == "第3章 新线索"
    assert generated_embeddings == [[0.0, 0.1]]
    assert any(event.event == "memory_updated" for event in logger.events)


def test_generate_from_novel_rejects_empty_generated_text(tmp_path):
    class EmptyChatClient:
        def generate(self, prompt, *, temperature=0.7, max_tokens=4096):
            return ChatGenerationResult(text=" ", model="chat-model")

    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("第1章 开端\n正文。", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        generate_from_novel(
            novel_path,
            "续写下一章。",
            mode="continuation",
            embeddings=FakeEmbeddingClient(),
            store=FakeStore(),
            chat=EmptyChatClient(),
            logger=FakeLogger(),
        )
