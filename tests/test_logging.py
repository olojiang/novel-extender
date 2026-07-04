import json

from novel_extender.run_logging import JsonlRunLogger


def test_jsonl_logger_writes_structured_events(tmp_path):
    logger = JsonlRunLogger(log_dir=tmp_path, run_id="run-1")

    logger.event("ingest", "started", source_path="novel.txt", chapter_count=3)

    lines = (tmp_path / "run-1.jsonl").read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    assert event["run_id"] == "run-1"
    assert event["stage"] == "ingest"
    assert event["event"] == "started"
    assert event["source_path"] == "novel.txt"
    assert event["chapter_count"] == 3
    assert "timestamp" in event
    assert "+" in event["timestamp"] or "-" in event["timestamp"], "timestamp should contain TZ offset"


def test_jsonl_logger_handles_non_serializable_fields(tmp_path):
    logger = JsonlRunLogger(log_dir=tmp_path, run_id="run-2")
    logger.event("test", "non_serializable", data=object())
    lines = (tmp_path / "run-2.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["stage"] == "test"

