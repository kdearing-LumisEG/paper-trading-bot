"""Tests for atomic autonomous-session artifacts."""

import json
from pathlib import Path

import pytest

from trading_bot.runtime.session_reporting import (
    SessionEventLogger,
    SessionReportWriter,
    SessionStatusWriter,
)


def test_status_replaces_and_events_append(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    writer = SessionStatusWriter(status_path)
    writer.write({"value": 1})
    writer.write({"value": 2})
    assert json.loads(status_path.read_text(encoding="utf-8")) == {"value": 2}
    assert not (tmp_path / ".status.json.tmp").exists()

    events = SessionEventLogger(tmp_path / "events.jsonl")
    events.log({"event_type": "first"})
    events.log({"event_type": "second"})
    assert (
        len((tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    )


def test_reports_are_historical_and_latest_is_atomic(tmp_path: Path) -> None:
    writer = SessionReportWriter(tmp_path)
    payload = {
        "session_run_id": "session-1",
        "session_date": "2026-07-22",
        "orders": [],
    }
    json_path, markdown_path = writer.write(payload)
    assert json.loads(json_path.read_text(encoding="utf-8"))["orders"] == []
    assert "Autonomous Paper Session Report" in markdown_path.read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "latest_session_report.json").exists()
    with pytest.raises(FileExistsError):
        writer.write(payload)


def test_urgent_report_name_is_unambiguous(tmp_path: Path) -> None:
    payload = {"session_run_id": "session-2", "session_date": "2026-07-22"}
    json_path, _ = SessionReportWriter(tmp_path).write(payload, urgent=True)
    assert json_path.name.startswith("URGENT_REVIEW_")
