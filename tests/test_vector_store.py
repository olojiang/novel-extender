from novel_extender.chapters import Chapter
from novel_extender.vector_store import ChromaNovelStore


def test_chroma_store_upserts_and_queries_chapters(tmp_path):
    store = ChromaNovelStore(db_path=tmp_path / "chroma", collection="test_chapters")
    chapters = [
        Chapter("safe-ch001", 1, "第1章 开端", "主角进入校园。", "safe.txt"),
        Chapter("safe-ch002", 2, "第2章 线索", "主角发现旧日线索。", "safe.txt"),
    ]

    store.upsert_chapters(chapters, [[1.0, 0.0], [0.0, 1.0]])

    retrieved = store.query(query_embedding=[0.0, 1.0], top_k=1)

    assert len(retrieved) == 1
    assert retrieved[0].chapter_id == "safe-ch002"
    assert retrieved[0].title == "第2章 线索"


def test_chroma_store_can_filter_queries_by_source_path(tmp_path):
    store = ChromaNovelStore(db_path=tmp_path / "chroma", collection="test_chapters")
    chapters = [
        Chapter("safe-ch001", 1, "第1章 开端", "主角发现旧徽章。", "safe.txt"),
        Chapter("other-ch001", 1, "第1章 无关", "无关小说也提到旧徽章。", "other.txt"),
    ]

    store.upsert_chapters(chapters, [[1.0, 0.0], [0.0, 1.0]])

    retrieved = store.query(query_embedding=[0.0, 1.0], top_k=2, source_path="safe.txt")

    assert [item.chapter_id for item in retrieved] == ["safe-ch001"]
