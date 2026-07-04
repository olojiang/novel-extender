from novel_extender.chapters import _split_sentences, split_chapters, split_into_chunks


def test_split_chapters_uses_chinese_chapter_headings():
    text = """
序言
第1章 初入星城
第一章正文。

第2章 风雨将至
第二章正文。
""".strip()

    chapters = split_chapters(text, source_path="sample.txt")

    assert [chapter.title for chapter in chapters] == ["序言", "第1章 初入星城", "第2章 风雨将至"]
    assert chapters[0].chapter_id == "sample-ch000"
    assert chapters[0].index == 0
    assert chapters[0].text == "序言"
    assert "第一章正文" in chapters[1].text
    assert chapters[2].index == 2


def test_split_chapters_falls_back_to_single_chapter_when_no_heading():
    chapters = split_chapters("只有一段正文。", source_path="single.txt")

    assert len(chapters) == 1
    assert chapters[0].title == "single"
    assert chapters[0].chapter_id == "single-ch001"


def test_split_chapters_uses_markdown_numbered_chapter_headings():
    text = """
# 小说标题

## 1. 第1章 道友，请照顾吾妻
第一章正文。

## 2. 第2章 陈兄，你误我啊
第二章正文。
""".strip()

    chapters = split_chapters(text, source_path="toutiao.md")

    assert [chapter.title for chapter in chapters] == [
        "第1章 道友，请照顾吾妻",
        "第2章 陈兄，你误我啊",
    ]
    assert "第一章正文" in chapters[0].text


def test_split_chapters_keeps_preface_before_first_heading():
    text = """
楔子
父亲留下旧徽章。

第1章 初入星城
第一章正文。
""".strip()

    chapters = split_chapters(text, source_path="sample.txt")

    assert [chapter.title for chapter in chapters] == ["楔子", "第1章 初入星城"]
    assert chapters[0].chapter_id == "sample-ch000"
    assert chapters[0].index == 0
    assert "旧徽章" in chapters[0].text


# ---- split_into_chunks tests ----

def test_split_into_chunks_passes_through_short_chapters():
    chapters = split_chapters("第1章 开端\n短正文。", source_path="s.txt")
    chunks = split_into_chunks(chapters, max_chunk_chars=5000)

    assert len(chunks) == len(chapters)
    assert chunks[0].chapter_id == chapters[0].chapter_id


def test_split_into_chunks_splits_long_chapter_at_paragraph_boundaries():
    body = "\n\n".join(f"段落{i}。" + "填充" * 100 for i in range(10))
    text = f"第1章 长章节\n{body}"
    chapters = split_chapters(text, source_path="long.txt")
    assert len(chapters) == 1

    chunks = split_into_chunks(chapters, max_chunk_chars=500, overlap_chars=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.source_path == "long.txt"
        assert chunk.index == 1
    assert chunks[0].chapter_id.endswith("-p001")


def test_split_into_chunks_preserves_overlap_content():
    para_a = "第一段正文内容。" * 50
    para_b = "第二段正文内容。" * 50
    para_c = "第三段正文内容。" * 50
    body = f"{para_a}\n\n{para_b}\n\n{para_c}"
    text = f"第1章 开端\n{body}"
    chapters = split_chapters(text, source_path="overlap.txt")
    chunks = split_into_chunks(chapters, max_chunk_chars=600, overlap_chars=200)

    if len(chunks) >= 2:
        last_para_of_first = chunks[0].text.split("\n\n")[-1]
        assert last_para_of_first in chunks[1].text


def test_split_into_chunks_keeps_original_for_single_chunk():
    chapters = split_chapters("第1章 短\n正文不长。", source_path="s.txt")
    chunks = split_into_chunks(chapters, max_chunk_chars=5000)

    assert len(chunks) == 1
    assert chunks[0].chapter_id == chapters[0].chapter_id
    assert chunks[0].title == chapters[0].title


def test_split_sentences_handles_chinese_and_english():
    text = "第一句话。第二句话！第三句话？"
    sentences = _split_sentences(text)
    assert len(sentences) >= 3
    assert sentences[0] == "第一句话。"


def test_split_into_chunks_falls_back_to_sentence_split_for_single_paragraph():
    long_para = "这是一句话。" * 500
    text = f"第1章 超长单段落\n{long_para}"
    chapters = split_chapters(text, source_path="mono.txt")
    assert len(chapters) == 1

    chunks = split_into_chunks(chapters, max_chunk_chars=500, overlap_chars=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.source_path == "mono.txt"


def test_split_into_chunks_passes_through_when_max_chars_zero_or_negative():
    chapters = split_chapters("第1章 短章\n一句话。", source_path="test.txt")
    assert split_into_chunks(chapters, max_chunk_chars=0, overlap_chars=0) == chapters
    assert split_into_chunks(chapters, max_chunk_chars=-1, overlap_chars=0) == chapters
