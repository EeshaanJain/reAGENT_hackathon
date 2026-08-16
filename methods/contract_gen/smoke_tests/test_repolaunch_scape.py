#!/usr/bin/env python3
"""RepoLaunch smoke test: verify the setup stage works on scAPE using the real, vendored
RepoLaunch CLI via LiteLLM.

Prerequisites:
- ANTHROPIC_API_KEY (or another litellm provider key) set in environment
- TAVILY_API_KEY set (RepoLaunch's own web-search tool)
- Docker daemon running
- RepoLaunch installed at ../RepoLaunch/.venv (see README.md)

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    export TAVILY_API_KEY="tvly-..."
    python smoke_tests/test_repolaunch_scape.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import paperclip_intake, repolaunch_runner  # noqa: E402

ROOT = Path(__file__).parent.parent
RESULT_PATH = ROOT / "smoke_tests" / "results" / "repolaunch_scape_result.json"


def write_result(details: dict) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(details, indent=2))


def main() -> int:
    record = json.loads((ROOT / "fixtures" / "paperclip_scape_record.json").read_text())
    instance = paperclip_intake.to_repolaunch_instance(record)
    config = json.loads((ROOT / "fixtures" / "repolaunch_config_scape.json").read_text())

    result = repolaunch_runner.run(instance, config, timeout_s=900)

    details = {
        "test_name": "repolaunch_smoke_test_scape",
        "status": result.status,
        "instance_id": result.instance_id,
        "repo": result.repo,
        "resolved_commit_sha": result.resolved_commit_sha,
        "docker_image": result.docker_image,
        "completed": result.completed,
        "exception": result.exception,
        "cost": result.cost,
        "duration_min": result.duration_min,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    write_result(details)

    print(f"[{result.status}] instance={result.instance_id} image={result.docker_image} exception={result.exception}")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
