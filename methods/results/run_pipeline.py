#!/usr/bin/env python3
"""Canonical entry point for a full method-integration run: contract_gen Stage 0-3, then
benchmark_adapt Stage 4, both landing in one place -- methods/results/<method_id>/ -- instead of
split across contract_gen/output/<id>/ and benchmark_adapt/output/<id>/.

Within that directory, three subdirectories separate three different audiences (not one flat
pile of files):
  component/    the deliverable -- model_contract.yaml, script.py, config.vsh.yaml, test.py,
                DEVIATIONS.md, MODELSPEC.json. What a reviewer reads.
  predictions/  real model output, once benchmark_adapt/harness/run_component.py runs the
                component against data -- not written by this script itself.
  logs/         everything about *how* the run happened -- stage logs, execution_log.json,
                repo_manifest.json, RepoLaunch's own agent workspace, mini's trajectory.json,
                timing.json. What a debugger reads.

Wraps both stages as subprocesses (matching how they're documented to run standalone) rather than
importing them in-process: both lanes have a package literally named `harness`, and a normal
import would silently resolve against whichever one Python's import system found first --
orchestrator.py's own emit_artifacts() works around exactly this via importlib for the one cross-
lane import it needs; subprocesses sidestep the problem entirely for a full two-stage run.

Does NOT run the synthesized component against data -- see benchmark_adapt/harness/run_component.py
for that, invoked separately once synthesis finishes, since what "input data" means is genuinely
method-specific (a DE-signature fixture vs. a single-cell fixture, for example).

Usage:
    python methods/results/run_pipeline.py --method-id scape \\
        --paperclip-record contract_gen/fixtures/paperclip_scape_record.json \\
        --repolaunch-config contract_gen/fixtures/repolaunch_config_scape.json \\
        --comprehension-engine serena --execute --model anthropic/claude-sonnet-5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent
RESULTS_ROOT = METHODS_ROOT / "results"
CONTRACT_GEN_ROOT = METHODS_ROOT / "contract_gen"
BENCHMARK_ADAPT_ROOT = METHODS_ROOT / "benchmark_adapt"


def run_stage(cmd: list[str], *, cwd: Path, log_path: Path, stage_name: str) -> tuple[bool, float]:
    print(f"\n{'=' * 60}\n{stage_name}\n{'=' * 60}")
    print(f"$ {' '.join(cmd)}  (cwd={cwd})")
    t0 = datetime.now(timezone.utc)
    with open(log_path, "w") as log_f:
        proc = subprocess.run(cmd, cwd=cwd, stdout=log_f, stderr=subprocess.STDOUT)
    wall_clock_s = (datetime.now(timezone.utc) - t0).total_seconds()
    ok = proc.returncode == 0
    print(f"{stage_name}: {'OK' if ok else f'FAILED (rc={proc.returncode})'} in {wall_clock_s:.1f}s -- see {log_path}")
    return ok, wall_clock_s


def write_timing(logs_dir: Path, timings: dict) -> None:
    """Consolidated logs/timing.json -- the two big phases this wrapper itself times, plus (once
    available) the finer per-stage breakdown each lane already writes on its own side
    (repo_manifest.json:stage_timings_s, stage4_timing.json) -- so "how long did each step take"
    is answerable from one file without hunting through logs.
    """
    manifest_path = logs_dir / "repo_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        timings["contract_gen_stage_breakdown_s"] = manifest.get("stage_timings_s", {})
    stage4_timing_path = logs_dir / "stage4_timing.json"
    if stage4_timing_path.exists():
        timings["benchmark_adapt_detail"] = json.loads(stage4_timing_path.read_text())
    timings["total_s"] = round(sum(v for k, v in timings.items() if k in ("contract_gen_wall_clock_s", "benchmark_adapt_wall_clock_s") and isinstance(v, (int, float))), 1)
    (logs_dir / "timing.json").write_text(json.dumps(timings, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--method-id", required=True)
    ap.add_argument("--paperclip-record", required=True, type=Path)
    ap.add_argument("--repolaunch-config", required=True, type=Path)
    ap.add_argument("--comprehension-engine", choices=["heuristic", "serena"], default="serena")
    ap.add_argument("--repolaunch-timeout", type=int, default=1800)
    ap.add_argument("--model", default="anthropic/claude-sonnet-5", help="mini-swe-agent model")
    ap.add_argument("--cost-limit", type=float, default=2.0)
    ap.add_argument("--execute", action="store_true", help="Actually run mini-swe-agent (Stage 4). Omit for a dry-run seed only.")
    ap.add_argument("--skip-contract-gen", action="store_true", help="Reuse an existing methods/results/<method_id>/component/model_contract.yaml, skip Stage 0-3 entirely")
    args = ap.parse_args()

    result_dir = RESULTS_ROOT / args.method_id
    component_dir = result_dir / "component"
    predictions_dir = result_dir / "predictions"
    logs_dir = result_dir / "logs"
    for d in (component_dir, predictions_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    paperclip_record = args.paperclip_record.resolve()
    repolaunch_config = args.repolaunch_config.resolve()
    timings: dict = {"started_at": datetime.now(timezone.utc).isoformat()}

    if not args.skip_contract_gen:
        ok, wall_clock_s = run_stage(
            [
                sys.executable, "-m", "harness.orchestrator",
                "--paperclip-record", str(paperclip_record),
                "--repolaunch-config", str(repolaunch_config),
                "--comprehension-engine", args.comprehension_engine,
                "--repolaunch-timeout", str(args.repolaunch_timeout),
                "--output", str(result_dir),  # orchestrator.py splits this into component/ and logs/ itself
            ],
            cwd=CONTRACT_GEN_ROOT,
            log_path=logs_dir / "stage0-3_contract_gen.log",
            stage_name="Stage 0-3: contract_gen",
        )
        timings["contract_gen_wall_clock_s"] = round(wall_clock_s, 1)
        if not ok:
            print("Stopping -- contract_gen did not succeed. Not proceeding to Stage 4.")
            write_timing(logs_dir, timings)
            return 1
    else:
        print(f"Skipping Stage 0-3 (--skip-contract-gen); reusing {component_dir / 'model_contract.yaml'}")

    contract_path = component_dir / "model_contract.yaml"
    exec_log_path = logs_dir / "execution_log.json"
    if not contract_path.exists():
        print(f"No model_contract.yaml at {contract_path} -- cannot proceed to Stage 4.")
        write_timing(logs_dir, timings)
        return 1

    cmd = [
        sys.executable, "-m", "harness.synthesize_adapter",
        "--contract", str(contract_path),
        "--execution-log", str(exec_log_path),
        "--output-dir", str(RESULTS_ROOT),  # synthesize() appends /<method_id>/{component,predictions,logs} itself
        "--model", args.model,
        "--cost-limit", str(args.cost_limit),
    ]
    if args.execute:
        cmd.append("--execute")

    ok, wall_clock_s = run_stage(
        cmd, cwd=BENCHMARK_ADAPT_ROOT,
        log_path=logs_dir / "stage4_benchmark_adapt.log",
        stage_name="Stage 4: benchmark_adapt" + (" (dry-run)" if not args.execute else ""),
    )
    timings["benchmark_adapt_wall_clock_s"] = round(wall_clock_s, 1)
    write_timing(logs_dir, timings)
    if not ok:
        return 1

    print(f"\nDone. component/ + predictions/ + logs/ under {result_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
