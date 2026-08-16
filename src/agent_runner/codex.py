"""Benchmark-agnostic wrapper around ``codex exec``.

The Codex CLI is driven non-interactively: the prompt is piped on stdin, the
event stream is captured as JSONL, and the agent's final message is written to a
file. Nothing in this module knows about datasets, benchmarks, or ingestion --
callers supply the prompt and the run directory.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .io import atomic_write_json, atomic_write_text, utc_now

# ``codex`` is not always on PATH: the macOS build ships inside the ChatGPT app
# bundle. Probe PATH first, then the known bundle location.
BUNDLED_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")

UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SESSION_ID_KEYS = ("session_id", "thread_id", "conversation_id", "id")
# Only the session bootstrap events carry the id; give up after that.
SESSION_ID_SCAN_LIMIT = 50


def resolve_codex_bin(value: str | None = None) -> str:
    """Resolve the codex executable, preferring an explicit path or ``CODEX_BIN``."""
    candidate = value or os.environ.get("CODEX_BIN")
    if candidate:
        if os.path.sep in candidate:
            path = Path(candidate).expanduser().resolve()
            if not path.is_file() or not os.access(path, os.X_OK):
                raise FileNotFoundError(f"codex executable not found: {path}")
            return str(path)
        found = shutil.which(candidate)
        if not found:
            raise FileNotFoundError(f"codex executable not found on PATH: {candidate}")
        return found

    found = shutil.which("codex")
    if found:
        return found
    if BUNDLED_CODEX.is_file() and os.access(BUNDLED_CODEX, os.X_OK):
        return str(BUNDLED_CODEX)
    raise FileNotFoundError(
        "codex executable not found on PATH and no bundled copy at "
        f"{BUNDLED_CODEX}; pass --codex-bin or set CODEX_BIN"
    )


def codex_version(codex_bin: str) -> str | None:
    """Return ``codex --version`` output, or None when it cannot be determined."""
    try:
        completed = subprocess.run(
            [codex_bin, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def build_codex_command(
    codex_bin: str,
    *,
    cwd: Path,
    last_message_path: Path,
    sandbox: str = "workspace-write",
    model: str | None = None,
    reasoning_effort: str | None = None,
    network_access: bool = True,
    web_search: bool = True,
    add_dirs: tuple[Path, ...] = (),
    resume_session_id: str | None = None,
) -> list[str]:
    """Build the ``codex exec`` argv. Pure, so it can be asserted on in tests."""
    command = [codex_bin, "exec"]
    if resume_session_id is not None:
        command += ["resume", resume_session_id]
    command += ["--json", "--cd", str(cwd), "--sandbox", sandbox]
    if network_access:
        # ``workspace-write`` denies network by default; deposited matrices are remote.
        command += ["--config", "sandbox_workspace_write.network_access=true"]
    if web_search:
        command += ["--config", 'web_search="live"']
    if reasoning_effort is not None:
        command += ["--config", f'model_reasoning_effort="{reasoning_effort}"']
    if model is not None:
        command += ["--model", model]
    for directory in add_dirs:
        command += ["--add-dir", str(directory)]
    command += ["--output-last-message", str(last_message_path)]
    # Read the prompt from stdin.
    command.append("-")
    return command


@dataclass
class CodexResult:
    """Outcome of one ``codex exec`` invocation."""

    returncode: int
    command: list[str]
    started_at: str
    completed_at: str
    duration_seconds: float
    pid: int | None
    events_path: Path
    stderr_path: Path
    last_message_path: Path
    session_id: str | None = None
    rollout_path: Path | None = None
    timed_out: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run_codex_exec(
    prompt: str,
    run_dir: Path,
    *,
    codex_bin: str,
    cwd: Path,
    sandbox: str = "workspace-write",
    model: str | None = None,
    reasoning_effort: str | None = None,
    add_dirs: tuple[Path, ...] = (),
    resume_session_id: str | None = None,
    timeout: int = 21600,
    metadata: dict | None = None,
) -> CodexResult:
    """Run codex non-interactively, capturing prompt, events, stderr and command."""
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = run_dir / "prompt.md"
    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    command_path = run_dir / "command.json"
    last_message_path = run_dir / "last_message.md"
    atomic_write_text(prompt_path, prompt)

    command = build_codex_command(
        codex_bin,
        cwd=cwd,
        last_message_path=last_message_path,
        sandbox=sandbox,
        model=model,
        reasoning_effort=reasoning_effort,
        add_dirs=add_dirs,
        resume_session_id=resume_session_id,
    )

    started_at = utc_now()
    started_monotonic = time.monotonic()
    timed_out = False
    with events_path.open("wb") as events, stderr_path.open("wb") as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=events, stderr=errors)
        atomic_write_json(
            command_path,
            {
                "started_at": started_at,
                "pid": process.pid,
                "cwd": str(cwd),
                "sandbox": sandbox,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "timeout_seconds": timeout,
                "resume_session_id": resume_session_id,
                "command": command,
                **(metadata or {}),
            },
        )
        try:
            process.communicate(input=prompt.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.communicate()

    completed_at = utc_now()
    session_id = find_session_id(events_path)
    rollout_path = None
    if session_id is not None:
        rollout_path = copy_rollout(session_id, run_dir / "rollout.jsonl")

    return CodexResult(
        returncode=process.returncode,
        command=command,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=round(time.monotonic() - started_monotonic, 3),
        pid=process.pid,
        events_path=events_path,
        stderr_path=stderr_path,
        last_message_path=last_message_path,
        session_id=session_id,
        rollout_path=rollout_path,
        timed_out=timed_out,
    )


def _candidate_ids(value: object) -> list[str]:
    """Collect UUID-shaped values stored under a known session key."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in SESSION_ID_KEYS and isinstance(item, str) and UUID_PATTERN.match(item):
                found.append(item)
            else:
                found.extend(_candidate_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_candidate_ids(item))
    return found


def find_session_id(events_path: Path) -> str | None:
    """Extract the codex session id from a ``--json`` event stream."""
    if not events_path.is_file():
        return None
    try:
        with events_path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= SESSION_ID_SCAN_LIMIT:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                candidates = _candidate_ids(event)
                if candidates:
                    return candidates[0]
    except OSError:
        return None
    return None


def find_rollout(session_id: str) -> Path | None:
    """Locate the persisted rollout transcript for a session id."""
    sessions_dir = codex_home() / "sessions"
    if not sessions_dir.is_dir():
        return None
    matches = sorted(sessions_dir.glob(f"**/rollout-*-{session_id}.jsonl"))
    return matches[-1] if matches else None


def copy_rollout(session_id: str, destination: Path) -> Path | None:
    """Copy the session rollout next to the run's own logs, if it was persisted."""
    source = find_rollout(session_id)
    if source is None:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination
