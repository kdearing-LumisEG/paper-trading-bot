"""Durable status, event, and daily report writers."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported report value: {type(value).__name__}")


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class SessionEventLogger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def log(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            payload, default=_json_default, sort_keys=True, separators=(",", ":")
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class SessionStatusWriter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, payload: dict[str, Any]) -> None:
        _atomic_write(self.path, _json_text(payload))


class SessionReportWriter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def _markdown(payload: dict[str, Any]) -> str:
        lines = ["# Autonomous Paper Session Report", ""]
        for heading, value in payload.items():
            label = heading.replace("_", " ").title()
            if isinstance(value, (dict, list)):
                rendered = json.dumps(
                    value, default=_json_default, indent=2, sort_keys=True
                )
                lines.extend([f"## {label}", "", "```json", rendered, "```", ""])
            else:
                rendered = (
                    "null"
                    if value is None
                    else str(
                        _json_default(value)
                        if isinstance(value, (Enum, date, datetime, Path))
                        else value
                    )
                )
                lines.extend([f"- {label}: {rendered}"])
        return "\n".join(lines).rstrip() + "\n"

    def write(
        self, payload: dict[str, Any], *, urgent: bool = False
    ) -> tuple[Path, Path]:
        session_id = str(payload["session_run_id"])
        day = str(payload["session_date"])
        prefix = "URGENT_REVIEW_" if urgent else ""
        stem = f"{prefix}{day}_{session_id}"
        json_path = self.directory / f"{stem}.json"
        markdown_path = self.directory / f"{stem}.md"
        if json_path.exists() or markdown_path.exists():
            raise FileExistsError(f"Historical session report already exists: {stem}")
        json_text = _json_text(payload)
        markdown_text = self._markdown(payload)
        _atomic_write(json_path, json_text)
        _atomic_write(markdown_path, markdown_text)
        _atomic_write(self.directory / "latest_session_report.json", json_text)
        _atomic_write(self.directory / "latest_session_report.md", markdown_text)
        return json_path, markdown_path
