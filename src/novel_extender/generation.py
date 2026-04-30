from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from novel_extender.openai_validator import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_CHAT_MODEL,
    ensure_local_base_url,
)
from novel_extender.utils import get_attr as _get_attr


@dataclass(frozen=True)
class ChatGenerationResult:
    text: str
    model: str


class OpenAIChatClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = DEFAULT_API_KEY,
        model: str = DEFAULT_CHAT_MODEL,
        timeout: float = 120.0,
    ):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=ensure_local_base_url(base_url), timeout=timeout)

    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ChatGenerationResult:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是长篇小说处理助手，需要保持剧情、人物、设定、时间线和伏笔一致。",
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = _extract_message_text(response)
        return ChatGenerationResult(text=text, model=self.model)


def _extract_message_text(response: Any) -> str:
    choices = _get_attr(response, "choices", [])
    if not choices:
        raise ValueError("chat completion returned no choices")

    message = _get_attr(choices[0], "message", None)
    content = _get_attr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("chat completion returned an empty message")
    return content.strip()


