"""Small, failure-safe helpers for source-file downloads."""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from pathlib import Path


def download_file(url: str, destination: str | Path, *, chunk_size: int = 8 * 1024 * 1024) -> Path:
    """Download to a partial file and atomically publish a complete response."""
    output = Path(destination)
    partial = output.with_suffix(output.suffix + ".part")
    try:
        with urllib.request.urlopen(url) as response, partial.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=chunk_size)
        partial.replace(output)
    except urllib.error.URLError as error:
        partial.unlink(missing_ok=True)
        reason = getattr(error, "reason", error)
        raise RuntimeError(f"BLOCKER: download failed for {url}: {reason}") from error
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return output
