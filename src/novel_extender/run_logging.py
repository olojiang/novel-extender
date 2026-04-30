from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class JsonlRunLogger:
    def __init__(self, *, log_dir: str | Path = "logs", run_id: str | None = None):
        self.run_id = run_id or uuid4().hex
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{self.run_id}.jsonl"
        self._lock = threading.Lock()

    def event(self, stage: str, event: str, **fields: Any) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "stage": stage,
            "event": event,
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)

