"""Real RepoLaunch invocation, generalized from Cecilia's original scAPE-only smoke test
(smoke_tests/test_repolaunch_scape.py) into something any method_id can call.

RepoLaunch is vendored as a pinned git submodule at ../RepoLaunch (microsoft/RepoLaunch,
verified: requires-python >= 3.12, so it lives in its own .venv -- see ../RepoLaunch/.venv,
created with `uv venv --python 3.12` + `uv pip install -e .`). It is NOT on PyPI (confirmed 404
during earlier tool-availability research), which is why it's vendored rather than pip-installed
into the shared `reagent` env.

RepoLaunch is itself an LLM agent (uses LiteLLM internally to explore how to build an unfamiliar
repo) -- every real run here costs API budget and wall-clock, separate from any cost incurred by
Sei's lane (mini-swe-agent, in benchmark_adapt/). Needs ANTHROPIC_API_KEY (or another litellm
provider key) and TAVILY_API_KEY (RepoLaunch's own web-search tool) in the environment, plus a
running Docker daemon.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CONTRACT_GEN_ROOT = Path(__file__).parent.parent
REPOLAUNCH_ROOT = CONTRACT_GEN_ROOT / "RepoLaunch"
REPOLAUNCH_BIN = REPOLAUNCH_ROOT / ".venv" / "bin" / "launch"


class RepoLaunchNotAvailable(Exception):
    pass


class RepoLaunchPrerequisiteError(Exception):
    """A prerequisite (Docker, credentials, the vendored binary) is missing -- distinct from a
    RepoLaunch *run* failing, which is a normal, expected outcome for a hard repo, not an error
    in this wrapper.
    """


@dataclass
class RepoLaunchResult:
    status: str  # "PASS" | "FAIL" | "BLOCKED"
    instance_id: str
    repo: str
    resolved_commit_sha: str | None
    docker_image: str | None
    docker_image_layers: dict | None
    setup_commands: list | None
    completed: bool | None
    exception: str | None
    cost: dict | None
    duration_min: float | None
    raw_result_path: str | None


def check_prerequisites() -> tuple[bool, str | None]:
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        return False, "no ANTHROPIC_API_KEY or OPENAI_API_KEY set -- RepoLaunch's own agent needs an LLM provider key"
    if not os.environ.get("TAVILY_API_KEY"):
        return False, "TAVILY_API_KEY not set -- RepoLaunch uses Tavily for its web-search tool (per docs/Development.md)"
    if not REPOLAUNCH_BIN.exists():
        return False, f"vendored launch binary not found at {REPOLAUNCH_BIN} -- run the install steps in README.md first"
    docker_check = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
    if docker_check.returncode != 0:
        return False, "docker daemon not reachable (`docker info` failed)"
    return True, None


def _resolve_base_commit(repo: str, base_commit: str) -> str:
    if base_commit != "RESOLVED_AT_RUNTIME":
        return base_commit
    result = subprocess.run(
        ["git", "ls-remote", f"https://github.com/{repo}", "HEAD"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return result.stdout.split()[0]


def run(
    instance: dict,
    config_template: dict,
    *,
    workdir: Path | None = None,
    timeout_s: int = 1800,
) -> RepoLaunchResult:
    """Run RepoLaunch's setup stage on a single instance. Blocking; can take many minutes -- the
    exploration/build-command-discovery step is genuinely open-ended (that's RepoLaunch's whole
    value proposition), not a fixed-cost operation.
    """
    ok, reason = check_prerequisites()
    if not ok:
        return RepoLaunchResult(
            status="BLOCKED", instance_id=instance.get("instance_id", "unknown"), repo=instance.get("repo", "unknown"),
            resolved_commit_sha=None, docker_image=None, docker_image_layers=None, setup_commands=None,
            completed=None, exception=reason, cost=None, duration_min=None, raw_result_path=None,
        )

    instance = dict(instance)
    instance["base_commit"] = _resolve_base_commit(instance["repo"], instance["base_commit"])

    workdir = workdir or (CONTRACT_GEN_ROOT / "work" / instance["instance_id"])
    workdir.mkdir(parents=True, exist_ok=True)

    dataset_path = workdir / "dataset.jsonl"
    dataset_path.write_text(json.dumps(instance) + "\n")

    config = dict(config_template)
    config["workspace_root"] = str(workdir) + "/"
    config["dataset"] = str(dataset_path)
    config_path = workdir / "config.json"
    config_path.write_text(json.dumps(config, indent=2))

    result_path = workdir / "playground" / instance["instance_id"] / "result.json"

    print(f"[repolaunch_runner] invoking {REPOLAUNCH_BIN} {config_path} (timeout={timeout_s}s)", flush=True)
    try:
        proc = subprocess.run(
            [str(REPOLAUNCH_BIN), str(config_path)],
            cwd=CONTRACT_GEN_ROOT,
            env=os.environ.copy(),
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        return RepoLaunchResult(
            status="FAIL", instance_id=instance["instance_id"], repo=instance["repo"],
            resolved_commit_sha=instance["base_commit"], docker_image=None, docker_image_layers=None,
            setup_commands=None, completed=False, exception=f"timed out after {timeout_s}s",
            cost=None, duration_min=timeout_s / 60, raw_result_path=None,
        )

    if proc.returncode != 0:
        return RepoLaunchResult(
            status="FAIL", instance_id=instance["instance_id"], repo=instance["repo"],
            resolved_commit_sha=instance["base_commit"], docker_image=None, docker_image_layers=None,
            setup_commands=None, completed=False,
            exception=f"launch exited {proc.returncode}: {proc.stderr[-2000:]}",
            cost=None, duration_min=None, raw_result_path=None,
        )

    if not result_path.exists():
        return RepoLaunchResult(
            status="FAIL", instance_id=instance["instance_id"], repo=instance["repo"],
            resolved_commit_sha=instance["base_commit"], docker_image=None, docker_image_layers=None,
            setup_commands=None, completed=False, exception=f"launch exited 0 but {result_path} was not written",
            cost=None, duration_min=None, raw_result_path=None,
        )

    result = json.loads(result_path.read_text())
    docker_image = result.get("docker_image")
    docker_ok = False
    if docker_image:
        inspect = subprocess.run(["docker", "image", "inspect", docker_image], capture_output=True)
        docker_ok = inspect.returncode == 0

    status = "PASS" if result.get("completed") and docker_image and docker_ok else "FAIL"
    return RepoLaunchResult(
        status=status,
        instance_id=instance["instance_id"],
        repo=instance["repo"],
        resolved_commit_sha=instance["base_commit"],
        docker_image=docker_image,
        docker_image_layers=result.get("docker_image_layers"),
        setup_commands=result.get("setup_commands"),
        completed=result.get("completed"),
        exception=result.get("exception"),
        cost=result.get("cost"),
        duration_min=result.get("duration"),
        raw_result_path=str(result_path),
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Run RepoLaunch's setup stage on one instance")
    ap.add_argument("--instance", required=True, type=Path, help="Path to an instance JSON file")
    ap.add_argument("--config", required=True, type=Path, help="Path to a RepoLaunch config template JSON")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()

    instance = json.loads(args.instance.read_text())
    config = json.loads(args.config.read_text())
    result = run(instance, config, timeout_s=args.timeout)
    print(json.dumps(result.__dict__, indent=2))
    sys.exit(0 if result.status == "PASS" else 1)
