from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import pytest

from benchmark_ingest import download_file


def test_download_file_handles_urlerror_and_removes_partial(monkeypatch, tmp_path: Path) -> None:
    destination = tmp_path / "source.bin"
    partial = tmp_path / "source.bin.part"
    partial.write_bytes(b"incomplete")

    def fail(_url: str):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    with pytest.raises(RuntimeError, match=r"BLOCKER: download failed.*offline"):
        download_file("https://example.invalid/source.bin", destination)
    assert not partial.exists()
    assert not destination.exists()
