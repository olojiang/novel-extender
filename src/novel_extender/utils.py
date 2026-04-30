from __future__ import annotations

from pathlib import Path
from typing import Any


def get_attr(value: Any, name: str, default: Any) -> Any:
    """Retrieve an attribute from an object or key from a dict."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def write_text(path: Path, text: str) -> None:
    """Write *text* to *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
