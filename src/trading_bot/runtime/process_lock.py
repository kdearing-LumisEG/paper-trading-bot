"""Single-process lock for signal-driven paper-trading commands."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4


class ProcessLockError(RuntimeError):
    """Raised when another runtime process already owns the lock."""


class FileProcessLock:
    """Use an exclusive marker file to prevent overlapping runtimes."""

    def __init__(
        self,
        path: Path,
    ) -> None:
        self._path = path
        self._token: str | None = None

    @property
    def path(self) -> Path:
        """Return the configured lock-file path."""

        return self._path

    def status(self) -> dict[str, object]:
        """Return current lock metadata without modifying the file."""

        if not self._path.exists():
            return {
                "active": False,
                "path": str(self._path),
                "metadata": None,
            }

        try:
            metadata = json.loads(
                self._path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            metadata = {
                "unreadable": True,
            }

        return {
            "active": True,
            "path": str(self._path),
            "metadata": metadata,
        }

    def acquire(self) -> None:
        """Acquire the lock or fail without replacing an existing lock."""

        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        token = uuid4().hex
        metadata = {
            "version": 1,
            "pid": os.getpid(),
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "token": token,
        }

        flags = (
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
        )

        try:
            descriptor = os.open(
                self._path,
                flags,
            )
        except FileExistsError as exc:
            status = self.status()
            raise ProcessLockError(
                "Another signal runtime may already be active. "
                f"Lock status: {status}"
            ) from exc

        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    metadata,
                    handle,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
        except Exception:
            self._path.unlink(
                missing_ok=True
            )
            raise

        self._token = token

    def release(self) -> None:
        """Release the lock only when this instance still owns it."""

        if self._token is None:
            return

        try:
            metadata = json.loads(
                self._path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            FileNotFoundError,
            OSError,
            json.JSONDecodeError,
        ):
            self._token = None
            return

        if (
            isinstance(metadata, dict)
            and metadata.get("token")
            == self._token
        ):
            self._path.unlink(
                missing_ok=True
            )

        self._token = None

    def clear(self) -> bool:
        """Explicitly remove an existing lock file."""

        existed = self._path.exists()
        self._path.unlink(
            missing_ok=True
        )
        return existed

    def __enter__(
        self,
    ) -> "FileProcessLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        del (
            exc_type,
            exc_value,
            traceback,
        )
        self.release()
