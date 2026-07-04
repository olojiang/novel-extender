from types import SimpleNamespace

from conftest import FakeEmbeddingClient, FakeStore

from novel_extender import web_api
from novel_extender.run_logging import JsonlRunLogger
from novel_extender.web_api import (
    GenerateSeriesRequest,
    PrepareFileRequest,
    _append_generated_chapter,
    _collection_name,
    _prepare_file,
)


def test_prepare_file_uses_ascii_chroma_collection_for_chinese_filename():
    result = _prepare_file(
        PrepareFileRequest(
            filename="火影-我对开启宫不感兴趣.txt",
            text="第1章 开端\n正文。",
        )
    )

    assert result["collection"].endswith("_chapters")
    assert result["collection"].isascii()
    assert "火影" not in result["collection"]
    assert result["chapterCount"] == 1


def test_collection_name_normalizes_legacy_invalid_values():
    collection = _collection_name("火影-我对开启宫不感兴趣_chapters")

    assert collection.endswith("_chapters")
    assert collection.isascii()
    assert len(collection) >= 3


def test_append_generated_chapter_adds_output_to_novel_and_memory(tmp_path):
    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("第1章 开端\n第一章正文。\n\n第2章 线索\n第二章正文。", encoding="utf-8")
    store = FakeStore()
    run_logger = JsonlRunLogger(log_dir=tmp_path / "logs")

    result = _append_generated_chapter(
        novel_path=novel_path,
        text="第3章 新线索\n生成正文。",
        mode="continuation",
        embeddings=FakeEmbeddingClient(),
        store=store,
        run_logger=run_logger,
        update_memory=True,
    )

    assert result["chapterCount"] == 3
    assert result["appendedChapter"]["title"] == "第3章 新线索"
    assert "第3章 新线索\n生成正文。" in novel_path.read_text(encoding="utf-8")
    chapters, embeddings = store.upserted[-1]
    assert chapters[0].chapter_id == "novel-ch003"
    assert embeddings == [[0.0, 0.1]]


def test_append_generated_chapter_adds_heading_when_output_has_no_heading(tmp_path):
    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("第1章 开端\n第一章正文。", encoding="utf-8")
    run_logger = JsonlRunLogger(log_dir=tmp_path / "logs")

    result = _append_generated_chapter(
        novel_path=novel_path,
        text="生成正文。",
        mode="continuation",
        embeddings=FakeEmbeddingClient(),
        store=FakeStore(),
        run_logger=run_logger,
        update_memory=False,
    )

    assert result["chapterCount"] == 2
    assert result["appendedChapter"]["title"] == "第2章 续写"
    assert "第2章 续写\n生成正文。" in novel_path.read_text(encoding="utf-8")


def test_generate_series_returns_the_combined_prompt(monkeypatch, tmp_path):
    prompts_seen: list[str] = []

    class FakeChat:
        def __init__(self, **_kwargs):
            pass

    def fake_clients(*_args, **_kwargs):
        return {"embedding": FakeEmbeddingClient(), "store": FakeStore()}

    def fake_generate_from_novel(*_args, **_kwargs):
        index = len(prompts_seen) + 1
        prompts_seen.append(f"prompt {index}")
        return SimpleNamespace(
            text=f"第{index + 1}章 续写\n生成正文。",
            prompt=f"prompt {index}",
            recent_chapter_ids=(f"novel-ch{index:03d}",),
            retrieved_chapter_ids=("novel-ch001",),
            post_check=SimpleNamespace(ok=True, issues=()),
            memory_updated=False,
        )

    monkeypatch.setattr(web_api, "_embedding_and_store_from", fake_clients)
    monkeypatch.setattr(web_api, "OpenAIChatClient", FakeChat)
    monkeypatch.setattr(web_api, "generate_from_novel", fake_generate_from_novel)

    prompt_output_path = tmp_path / "prompts.txt"
    result = web_api._generate_series(
        GenerateSeriesRequest(
            novelPath=str(tmp_path / "novel.txt"),
            request="续写两章。",
            chapterBatchSize=2,
            appendToNovel=False,
            promptOutputPath=str(prompt_output_path),
        )
    )

    assert f"{result['prompt']}\n" == prompt_output_path.read_text(encoding="utf-8")
    assert "===== chapter 1 prompt =====\nprompt 1" in result["prompt"]
    assert "===== chapter 2 prompt =====\nprompt 2" in result["prompt"]
