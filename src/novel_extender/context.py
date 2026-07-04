from __future__ import annotations

from dataclasses import dataclass

from novel_extender.chapters import Chapter


@dataclass(frozen=True)
class RetrievedChapter:
    chapter_id: str
    title: str
    index: int
    text: str
    distance: float | None = None


@dataclass(frozen=True)
class ContinuationContext:
    prompt: str
    recent_chapter_ids: tuple[str, ...]
    retrieved_chapter_ids: tuple[str, ...]
    truncated: bool = False


def build_continuation_context(
    *,
    user_request: str,
    chapters: list[Chapter],
    retrieved: list[RetrievedChapter],
    recent_count: int = 3,
    mode: str = "continuation",
    prompt_char_budget: int | None = None,
) -> ContinuationContext:
    _VALID_MODES = {"analysis", "rewrite", "continuation"}
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown mode {mode!r}, expected one of {sorted(_VALID_MODES)}")
    recent = chapters[-recent_count:] if recent_count > 0 else []
    recent_ids = {chapter.chapter_id for chapter in recent}
    retrieved = _dedupe_retrieved(retrieved, excluded_ids=recent_ids)
    request_label = {
        "analysis": "分析要求",
        "rewrite": "改写要求",
        "continuation": "续写要求",
    }[mode]
    generation_steps = {
        "analysis": (
            "【分析流程】\n"
            "1. 先列出与任务最相关的已有事实、人物关系、地点、伏笔和时间线。\n"
            "2. 再指出潜在矛盾、缺口、可延展线索和后续写作注意事项。\n"
            "3. 不生成新剧情正文，除非任务明确要求。"
        ),
        "rewrite": (
            "【改写流程】\n"
            "1. 先提取需要保留的事实、人物关系、时间线、伏笔和场景功能。\n"
            "2. 再给出改写方案，说明要增强、删减或调整的部分。\n"
            "3. 最后生成改写后的章节正文，避免改变已建立事实。"
        ),
        "continuation": (
            "【生成流程】\n"
            "1. 先给出下一章大纲，列出每个场景的目的、冲突、信息增量和结尾钩子。\n"
            "2. 再根据大纲生成正文。\n"
            "3. 不改写既有人物关系，不提前揭示未揭示伏笔。"
        ),
    }[mode]
    prompt, truncated = _build_prompt(
        mode=mode,
        request_label=request_label,
        user_request=user_request,
        recent=recent,
        retrieved=retrieved,
        generation_steps=generation_steps,
        prompt_char_budget=prompt_char_budget,
    )
    return ContinuationContext(
        prompt=prompt,
        recent_chapter_ids=tuple(chapter.chapter_id for chapter in recent),
        retrieved_chapter_ids=tuple(chapter.chapter_id for chapter in retrieved),
        truncated=truncated,
    )


def _dedupe_retrieved(retrieved: list[RetrievedChapter], *, excluded_ids: set[str]) -> list[RetrievedChapter]:
    seen = set(excluded_ids)
    deduped = []
    for chapter in retrieved:
        if chapter.chapter_id in seen:
            continue
        seen.add(chapter.chapter_id)
        deduped.append(chapter)
    return deduped


def _build_prompt(
    *,
    mode: str,
    request_label: str,
    user_request: str,
    recent: list[Chapter],
    retrieved: list[RetrievedChapter],
    generation_steps: str,
    prompt_char_budget: int | None,
) -> tuple[str, bool]:
    mode_section = f"【模式】\n{mode}"
    request_section = f"【{request_label}】\n{user_request}"

    full_prompt = _join_prompt_sections(
        mode_section,
        request_section,
        "【最近章节】\n" + _format_chapters(recent),
        "【相关检索章节】\n" + _format_retrieved(retrieved),
        generation_steps,
    )
    if prompt_char_budget is None or len(full_prompt) <= prompt_char_budget:
        return full_prompt, False

    empty_prompt = _join_prompt_sections(
        mode_section,
        request_section,
        "【最近章节】\n",
        "【相关检索章节】\n",
        generation_steps,
    )
    content_budget = max(0, prompt_char_budget - len(empty_prompt))
    recent_budget, retrieved_budget = _split_content_budget(
        content_budget,
        has_recent=bool(recent),
        has_retrieved=bool(retrieved),
    )
    prompt = _join_prompt_sections(
        mode_section,
        request_section,
        "【最近章节】\n" + _format_chapters(recent, char_budget=recent_budget),
        "【相关检索章节】\n" + _format_retrieved(retrieved, char_budget=retrieved_budget),
        generation_steps,
    )
    if len(prompt) > prompt_char_budget:
        prompt = _truncate_to_chars(prompt, prompt_char_budget)
    return prompt, True


def _join_prompt_sections(*sections: str) -> str:
    return "\n\n".join(sections)


def _split_content_budget(content_budget: int, *, has_recent: bool, has_retrieved: bool) -> tuple[int | None, int | None]:
    if not has_recent and not has_retrieved:
        return None, None
    if not has_recent:
        return None, content_budget
    if not has_retrieved:
        return content_budget, None
    recent_budget = int(content_budget * 0.65)
    return recent_budget, content_budget - recent_budget


def _format_chapters(chapters: list[Chapter], *, char_budget: int | None = None) -> str:
    if not chapters:
        return "(none)"
    blocks = [(chapter.title, _without_leading_title(chapter.text, chapter.title)) for chapter in chapters]
    return _format_blocks(blocks, char_budget=char_budget)


def _format_retrieved(chapters: list[RetrievedChapter], *, char_budget: int | None = None) -> str:
    if not chapters:
        return "(none)"
    blocks = [
        (f"{chapter.title} [distance={chapter.distance}]", _without_leading_title(chapter.text, chapter.title))
        for chapter in chapters
    ]
    return _format_blocks(blocks, char_budget=char_budget)


def _format_blocks(blocks: list[tuple[str, str]], *, char_budget: int | None) -> str:
    if char_budget is None:
        return "\n\n".join(f"{heading}\n{body}" for heading, body in blocks)
    if char_budget <= 0:
        return "[omitted to fit prompt budget]"

    separator_budget = len("\n\n") * max(0, len(blocks) - 1)
    body_budget = max(0, char_budget - separator_budget)
    per_block_budget = body_budget // len(blocks)
    remainder = body_budget % len(blocks)
    parts = []
    for index, (heading, body) in enumerate(blocks):
        block_budget = per_block_budget + (1 if index < remainder else 0)
        parts.append(_format_block(heading, body, char_budget=block_budget))
    return "\n\n".join(part for part in parts if part)


def _format_block(heading: str, body: str, *, char_budget: int) -> str:
    if char_budget <= 0:
        return ""
    prefix = f"{heading}\n"
    if len(prefix) >= char_budget:
        return _truncate_to_chars(heading, char_budget)
    return prefix + _truncate_to_chars(body, char_budget - len(prefix))


def _truncate_to_chars(text: str, char_budget: int) -> str:
    if len(text) <= char_budget:
        return text
    marker = "\n...[truncated]"
    if char_budget <= len(marker):
        return text[:char_budget]
    return text[: char_budget - len(marker)].rstrip() + marker


def _without_leading_title(text: str, title: str) -> str:
    stripped = text.strip()
    if stripped.startswith(title):
        return stripped[len(title) :].lstrip()
    return stripped
