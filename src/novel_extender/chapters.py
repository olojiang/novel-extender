from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d+\.\s*)?(?P<title>(?:第\s*[0-9零一二三四五六七八九十百千万两]+\s*[章节回卷部篇].*)|(?:【[^】]+】.*?[0-9零一二三四五六七八九十百千万两]+(?:[—\-：: ].*)?))\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Chapter:
    chapter_id: str
    index: int
    title: str
    text: str
    source_path: str

    @property
    def char_count(self) -> int:
        return len(self.text)


def split_chapters(text: str, *, source_path: str) -> list[Chapter]:
    source_stem = safe_source_stem(source_path)
    matches = [match for match in CHAPTER_HEADING_RE.finditer(text) if _looks_like_heading(match.group("title"))]
    if not matches:
        stripped = text.strip()
        return [
            Chapter(
                chapter_id=f"{source_stem}-ch001",
                index=1,
                title=source_stem,
                text=stripped,
                source_path=source_path,
            )
        ] if stripped else []

    chapters: list[Chapter] = []
    preface = text[: matches[0].start()].strip()
    if preface and not _is_document_title_preface(preface):
        chapters.append(
            Chapter(
                chapter_id=f"{source_stem}-ch000",
                index=0,
                title=_preface_title(preface),
                text=preface,
                source_path=source_path,
            )
        )
    for offset, match in enumerate(matches, start=1):
        start = match.start()
        end = matches[offset].start() if offset < len(matches) else len(text)
        chapter_text = text[start:end].strip()
        title = match.group("title").strip()
        chapters.append(
            Chapter(
                chapter_id=f"{source_stem}-ch{offset:03d}",
                index=offset,
                title=title,
                text=chapter_text,
                source_path=source_path,
            )
        )
    if chapters:
        last = chapters[-1]
        cleaned_text = _strip_trailing_spam(last.text)
        if cleaned_text != last.text:
            chapters[-1] = Chapter(
                chapter_id=last.chapter_id,
                index=last.index,
                title=last.title,
                text=cleaned_text,
                source_path=last.source_path,
            )
    return chapters


def safe_source_stem(source_path: str) -> str:
    stem = Path(source_path).stem or "novel"
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", stem).strip("-")
    return safe or "novel"


def _preface_title(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if 0 < len(first_line) <= 30 and "。" not in first_line:
        return first_line
    return "序言"


def _is_document_title_preface(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) == 1 and lines[0].startswith("#")


def _looks_like_heading(title: str) -> bool:
    compact = title.strip()
    if len(compact) > 80:
        return False
    if "。" in compact:
        return False
    if re.match(r'^第\s*[0-9零一二三四五六七八九十百千万两]+(?:\.\d+)?\s*[章节回卷部篇]', compact):
        return True
    return bool(re.match(r'^【[^】]+】', compact))


DEFAULT_MAX_CHUNK_CHARS = 2000
DEFAULT_OVERLAP_CHARS = 200


def split_into_chunks(
    chapters: list[Chapter],
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chapter]:
    """Split long chapters into smaller chunks at paragraph boundaries.

    Chapters shorter than *max_chunk_chars* pass through unchanged.  Longer ones
    are broken at double-newline paragraph boundaries with *overlap_chars*
    characters carried over to the next chunk for retrieval continuity.
    """
    if max_chunk_chars <= 0:
        return list(chapters)
    result: list[Chapter] = []
    for chapter in chapters:
        if chapter.char_count <= max_chunk_chars:
            result.append(chapter)
            continue
        result.extend(_chunk_long_chapter(chapter, max_chunk_chars, overlap_chars))
    return result


def _chunk_long_chapter(chapter: Chapter, max_chars: int, overlap: int) -> list[Chapter]:
    paragraphs = _split_paragraphs(chapter.text, max_segment_chars=max_chars)
    chunks: list[Chapter] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current and current_len + para_len > max_chars:
            chunks.append(_make_chunk(chapter, current, len(chunks) + 1))
            current, current_len = _carry_overlap(current, overlap)
        current.append(para)
        current_len += para_len

    if current:
        chunks.append(_make_chunk(chapter, current, len(chunks) + 1))

    if len(chunks) <= 1:
        return [chapter]
    return chunks


def _split_paragraphs(text: str, *, max_segment_chars: int = 0) -> list[str]:
    """Split on blank lines; if *max_segment_chars* > 0, further split
    oversized paragraphs at sentence boundaries."""
    parts = re.split(r"\n\s*\n", text)
    segments: list[str] = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        if max_segment_chars > 0 and len(stripped) > max_segment_chars:
            segments.extend(_split_sentences(stripped))
        else:
            segments.append(stripped)
    return segments


_SENTENCE_RE = re.compile(
    r'(?<=[。！？!?\n])\s*'
    r'|(?<=\.)\s+(?=[A-Z\u4e00-\u9fff])'
    r'|(?<=[」』）】"])\s*(?=[^\s])'
)


def _split_sentences(text: str) -> list[str]:
    """Best-effort sentence splitting for Chinese and English text."""
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _carry_overlap(parts: list[str], overlap_chars: int) -> tuple[list[str], int]:
    """Return the tail of *parts* that fits within *overlap_chars*."""
    if overlap_chars <= 0:
        return [], 0
    carried: list[str] = []
    total = 0
    for part in reversed(parts):
        if total + len(part) > overlap_chars and carried:
            break
        carried.insert(0, part)
        total += len(part)
    return carried, total


def _make_chunk(parent: Chapter, parts: list[str], chunk_num: int) -> Chapter:
    return Chapter(
        chapter_id=f"{parent.chapter_id}-p{chunk_num:03d}",
        index=parent.index,
        title=f"{parent.title} ({chunk_num})",
        text="\n\n".join(parts),
        source_path=parent.source_path,
    )


def _strip_trailing_spam(text: str) -> str:
    spam_markers = [
        "声明:本书由",
        "声明：本书由",
        "------【",
        "【全网最大",
    ]
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if any(marker in line for marker in spam_markers):
            return "\n".join(lines[:i]).strip()
    return text.strip()
