from types import SimpleNamespace

import pytest

from novel_extender.generation import _extract_message_text


def test_extract_message_text_accepts_openai_style_objects():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="  生成正文。\n"),
            )
        ]
    )

    assert _extract_message_text(response) == "生成正文。"


def test_extract_message_text_accepts_dict_responses():
    response = {"choices": [{"message": {"content": "改写正文。"}}]}

    assert _extract_message_text(response) == "改写正文。"


def test_extract_message_text_rejects_empty_choices():
    with pytest.raises(ValueError, match="no choices"):
        _extract_message_text({"choices": []})
