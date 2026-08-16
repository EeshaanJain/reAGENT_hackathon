"""Run a raw VIASH-style script.py the way `viash build` + the compiled executable would,
without requiring the Viash CLI (a JVM tool) to be installed on this machine.

A component's script.py follows a fixed convention:

    ## VIASH START
    par = {...defaults for local editor testing...}
    meta = {...}
    ## VIASH END
    ... actual adapter logic using par[...] ...

`viash build` replaces everything between the markers with real CLI-parsed values. This shim does
the same textual substitution and executes the result as a subprocess, so:

  - the Gauntlet (gauntlet/checks.py + test_*.py) can run against a synthesized adapter today,
    before `viash` is available on the machine;
  - the substitution logic is small and auditable, so swapping it for a real `viash run` call
    later is a one-line change in run_component(), not a rewrite of every test.

This is explicitly a stand-in for `viash ns test`, not a replacement for it -- see README.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_START_MARKER = "## VIASH START"
_END_MARKER = "## VIASH END"


@dataclass
class ComponentRunResult:
    returncode: int
    stdout: str
    stderr: str
    par: dict

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _strip_viash_block(source: str) -> str:
    lines = source.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == _START_MARKER)
        end = next(i for i, l in enumerate(lines) if l.strip() == _END_MARKER)
    except StopIteration:
        raise ValueError(
            f"script has no '{_START_MARKER}' / '{_END_MARKER}' block -- not a VIASH-convention script"
        )
    return "\n".join(lines[:start] + lines[end + 1 :])


_NETWORK_BLOCK_PRELUDE = '''
import socket as _socket

class _NetworkBlocked(RuntimeError):
    pass

def _blocked(*a, **k):
    raise _NetworkBlocked("network access blocked during inference (Gauntlet G4)")

_socket.socket.connect = _blocked
_socket.socket.connect_ex = _blocked
_socket.create_connection = _blocked
'''


def run_component(
    script_path: str | Path,
    par: dict,
    meta: dict | None = None,
    *,
    timeout: int = 120,
    workdir: str | Path | None = None,
    block_network: bool = False,
) -> ComponentRunResult:
    """Inject `par`/`meta` into a VIASH-style script.py and execute it as a subprocess.

    Paths inside `par` should already be absolute (or resolvable from `workdir`) -- this shim does
    not do Viash's automatic path-resolution.

    block_network=True implements G4 (no network at inference): it monkeypatches socket connection
    calls to raise, *inside the subprocess actually running the adapter* -- not in the test
    process, which wouldn't touch the adapter's own socket calls at all.
    """
    script_path = Path(script_path)
    meta = meta or {"name": script_path.parent.name, "functionality_name": script_path.parent.name}
    source = _strip_viash_block(script_path.read_text())

    prelude = (
        "import json as _json\n"
        f"par = _json.loads({json.dumps(json.dumps(par))})\n"
        f"meta = _json.loads({json.dumps(json.dumps(meta))})\n"
    )
    if block_network:
        prelude += _NETWORK_BLOCK_PRELUDE
    rendered = prelude + source

    workdir = Path(workdir) if workdir else script_path.parent
    tmp_path = workdir / f".viash_shim_{script_path.stem}.py"
    tmp_path.write_text(rendered)

    try:
        proc = subprocess.run(
            [sys.executable, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
        return ComponentRunResult(proc.returncode, proc.stdout, proc.stderr, par)
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Run a VIASH-style script.py with injected par/meta")
    ap.add_argument("script_path")
    ap.add_argument("--par", required=True, help="JSON dict of par values")
    args = ap.parse_args()

    result = run_component(args.script_path, json.loads(args.par))
    print(result.stdout)
    if not result.ok:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
