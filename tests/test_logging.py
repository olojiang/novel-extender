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

