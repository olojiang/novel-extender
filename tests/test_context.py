import pytest

from novel_extender.chapters import Chapter
from novel_extender.context import RetrievedChapter, build_continuation_context


def test_build_continuation_context_includes_recent_and_retrieved_chapters():
    chapters = [
        Chapter("novel-ch001", 1, "第1章 开端", "第一章正文", "novel.txt"),
        Chapter("novel-ch002", 2, "第2章 线索", "第二章正文", "novel.txt"),
        Chapter("novel-ch003", 3, "第3章 转折", "第三章正文", "novel.txt"),
    ]
    retrieved = [
        RetrievedChapter("novel-ch001", "第1章 开端", 1, "第一章正文", 0.12),
    ]

    context = build_continuation_context(
        user_request="续写下一章，重点写主角发现线索。",
        chapters=chapters,
        retrieved=retrieved,
        recent_count=2,
    )

    assert "【续写要求】" in context.prompt
    assert "续写下一章" in context.prompt
    assert "【最近章节】" in context.prompt
    assert "第2章 线索" in context.prompt
    assert "第3章 转折" in context.prompt
    assert "【相关检索章节】" in context.prompt
    assert "第1章 开端" in context.prompt
    assert context.truncated is False


def test_build_continuation_context_truncates_when_prompt_budget_is_set():
    chapters = [
        Chapter("novel-ch001", 1, "第1章 开端", "第一章正文" * 200, "novel.txt"),
        Chapter("novel-ch002", 2, "第2章 线索", "第二章正文" * 200, "novel.txt"),
    ]
    retrieved = [
        RetrievedChapter("novel-ch001", "第1章 开端", 1, "第一章正文" * 200, 0.12),
    ]

    context = build_continuation_context(
        user_request="续写下一章。",
        chapters=chapters,
        retrieved=retrieved,
        recent_count=2,
        prompt_char_budget=900,
    )

    assert len(context.prompt) <= 900
    assert context.truncated is True
    assert "...[truncated]" in context.prompt


def test_build_continuation_context_deduplicates_recent_retrieved_chapters():
    chapters = [
        Chapter("novel-ch001", 1, "第1章 开端", "第一章正文", "novel.txt"),
        Chapter("novel-ch002", 2, "第2章 线索", "第二章正文", "novel.txt"),
    ]
    retrieved = [
        RetrievedChapter("novel-ch002", "第2章 线索", 2, "第二章正文", 0.01),
        RetrievedChapter("novel-ch001", "第1章 开端", 1, "第一章正文", 0.2),
    ]

    context = build_continuation_context(
        user_request="续写下一章。",
        chapters=chapters,
        retrieved=retrieved,
        recent_count=1,
    )

    assert context.recent_chapter_ids == ("novel-ch002",)
    assert context.retrieved_chapter_ids == ("novel-ch001",)
    assert context.prompt.count("第2章 线索") == 1


def test_build_continuation_context_rejects_unknown_mode():
    chapters = [Chapter("novel-ch001", 1, "第1章 开端", "正文", "novel.txt")]
    with pytest.raises(ValueError, match="Unknown mode"):
        build_continuation_context(
            user_request="续写。",
            chapters=chapters,
            retrieved=[],
            mode="invalid_mode",
        )
