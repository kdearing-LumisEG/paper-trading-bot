"""Tests for exclusive runtime process locking."""

from pathlib import Path

import pytest

from trading_bot.runtime.process_lock import (
    FileProcessLock,
    ProcessLockError,
)


def test_lock_is_exclusive_and_released(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.lock"
    first = FileProcessLock(path)
    second = FileProcessLock(path)

    with first:
        assert first.status()["active"] is True

        with pytest.raises(
            ProcessLockError,
            match="already be active",
        ):
            second.acquire()

    assert first.status()["active"] is False


def test_lock_is_released_after_exception(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.lock"

    with pytest.raises(
        RuntimeError,
        match="boom",
    ):
        with FileProcessLock(path):
            raise RuntimeError("boom")

    assert not path.exists()


def test_explicit_clear_removes_lock(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.lock"
    path.write_text(
        "{}",
        encoding="utf-8",
    )

    lock = FileProcessLock(path)

    assert lock.clear() is True
    assert lock.clear() is False
    assert lock.status()["active"] is False
