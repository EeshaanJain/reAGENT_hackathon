"""Small filesystem and hashing helpers shared by agent drivers.

These mirror the helpers proven in ``scripts/paperclip_postsearch.py`` so that a
second driver does not have to reinvent atomic writes or timestamp formatting.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def utc_now() -> str:
    """Return a second-resolution UTC timestamp in ISO-8601 form."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def utc_stamp() -> str:
    """Return a filesystem-safe UTC timestamp usable as a run-directory name."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """Hash a file without reading it entirely into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
