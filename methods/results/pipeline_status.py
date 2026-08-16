#!/usr/bin/env python3
"""Live status for the method-integration pipeline (contract_gen Stage 0-3 + benchmark_adapt Stage 4).

Usage:
    python methods/results/pipeline_status.py [--method-id scape] [--watch] [--interval 10]

Answers, for a given method_id, in one glance:
  - Is anything actually running right now? (a real `ps` process check, not just file mtimes --
    a stalled/crashed run can leave files behind with no process attached, and this tool should
    say so, not report "running" from stale state.)
  - Which orchestrator stage is it on (parsed from the log this pipeline is expected to be run
    with output redirected to -- see methods/README.md's "Running the full pipeline
    autonomously").
  - RepoLaunch (Stage 1)'s own live progress: agent turn count + running cost, read straight out
    of its own workdir (playground/<id>/llm/*.md, setup.log) -- the same files a human watching
    the run would tail. RepoLaunch's parent process buffers its subprocess output until exit
    (repolaunch_runner.py uses subprocess.run(capture_output=True)), so the orchestrator's own log
    goes quiet during Stage 1 even though real work is happening -- these files are where the
    actual progress is visible.
  - Once contract_gen finishes: model_contract.yaml headline fields, or the failure reason.
  - benchmark_adapt (Stage 4)'s own process + trajectory.json/script.py state, once started.

No dependency beyond the standard library -- meant to be run standalone, repeatedly, alongside a
pipeline run in another terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_GEN_ROOT = METHODS_ROOT / "contract_gen"
BENCHMARK_ADAPT_ROOT = METHODS_ROOT / "benchmark_adapt"
RESULTS_ROOT = METHODS_ROOT / "results"

PROC_PATTERNS = {
    "orchestrator": "harness.orchestrator",
    "repolaunch": "RepoLaunch/.venv/bin/launch",
    "synthesize_adapter": "harness.synthesize_adapter",
    "mini": "mini --yolo",
}


def _ps_aux() -> str:
    return subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout


def find_processes(ps_output: str) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {name: [] for name in PROC_PATTERNS}
    for line in ps_output.splitlines()[1:]:
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        pid, cmd = parts[1], parts[10]
        for name, pattern in PROC_PATTERNS.items():
            if pattern in cmd:
                found[name].append({"pid": pid, "cmd": cmd})
    for procs in found.values():
        for p in procs:
            etime = subprocess.run(["ps", "-o", "etime=", "-p", p["pid"]], capture_output=True, text=True).stdout.strip()
            p["elapsed"] = etime or "?"
    return found


def last_stage_marker(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    marker = None
    # requires at least one letter in the captured group -- otherwise a bare "====...====" banner
    # line (this log's own header/footer separators) matches with an empty/junk capture, since
    # `.+?` is non-greedy and happily matches a handful of "=" characters as "content".
    stage_re = re.compile(r"===\s*([^=]*[A-Za-z][^=]*?)\s*===")
    for line in log_path.read_text(errors="ignore").splitlines():
        m = stage_re.search(line)
        if m:
            marker = m.group(1)
        elif line.startswith("Done."):
            marker = line.strip()
    return marker


def repolaunch_progress(output_dir: Path, instance_id: str) -> dict | None:
    playground = output_dir / "repolaunch" / "playground" / instance_id
    if not playground.exists():
        return None
    llm_dir = playground / "llm"
    n_turns = len(list(llm_dir.glob("*.md"))) if llm_dir.exists() else 0

    setup_log = playground / "setup.log"
    total_cost = 0.0
    last_action = None
    if setup_log.exists():
        text = setup_log.read_text(errors="ignore")
        total_cost = sum(float(x) for x in re.findall(r"cost usd:\s*([\d.]+)", text))
        actions = re.findall(r"<command>(.*?)</command>", text, re.S)
        if actions:
            last_action = actions[-1].strip().replace("\n", " ")[:160]

    result_path = playground / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None

    return {"n_turns": n_turns, "total_cost_usd": round(total_cost, 4), "last_action": last_action, "result": result}


def contract_gen_status(method_id: str, log_path: Path) -> dict:
    result_dir = RESULTS_ROOT / method_id
    logs_dir = result_dir / "logs"
    status: dict = {
        "stage_marker": last_stage_marker(log_path),
        "repo_manifest": None,
        "contract_headline": None,
        "repolaunch": repolaunch_progress(logs_dir, method_id),
    }
    manifest_path = logs_dir / "repo_manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        status["repo_manifest"] = {
            "repolaunch_status": m.get("repolaunch_status"),
            "docker_image": m.get("docker_image"),
            "commit": m.get("resolved_commit_sha"),
        }
    contract_path = result_dir / "component" / "model_contract.yaml"
    if contract_path.exists():
        try:
            import yaml

            c = yaml.safe_load(contract_path.read_text())
            status["contract_headline"] = {
                "entrypoint": c.get("model", {}).get("entrypoint", {}).get("value"),
                "prediction_level": c.get("prediction_level", {}).get("value"),
                "requires_sc_counts": c.get("requires_sc_counts", {}).get("value"),
                "n_arguments": len(c.get("arguments") or []),
                "n_dependencies": len(c.get("dependencies") or []),
            }
        except ImportError:
            status["contract_headline"] = {"note": "pyyaml not available to parse -- file exists"}
    return status


_MINI_STEP_RE = re.compile(r"mini-swe-agent \(step (\d+), \$([\d.]+)\)")


def benchmark_adapt_status(method_id: str, log_path: Path | None) -> dict:
    result_dir = RESULTS_ROOT / method_id
    script_path = result_dir / "component" / "script.py"
    status: dict = {"seeded": script_path.exists(), "stub": None, "trajectory": None, "log_tail": None, "mini_progress": None}
    if script_path.exists():
        status["stub"] = "NotImplementedError" in script_path.read_text()
    traj_path = result_dir / "logs" / "trajectory.json"
    if traj_path.exists():
        status["trajectory"] = {"mtime": time.ctime(traj_path.stat().st_mtime), "size_bytes": traj_path.stat().st_size}
    if log_path and log_path.exists():
        text = log_path.read_text(errors="ignore")
        lines = text.splitlines()
        status["log_tail"] = lines[-5:]
        # Unlike RepoLaunch (subprocess.run(capture_output=True), buffered until exit),
        # synthesize_adapter.py invokes mini without capturing output, so its per-step
        # "mini-swe-agent (step N, $cost)" markers stream straight into this log in real time.
        steps = _MINI_STEP_RE.findall(text)
        if steps:
            last_step, last_cost = steps[-1]
            status["mini_progress"] = {"step": int(last_step), "cost_usd": float(last_cost)}
    return status


def render(method_id: str, procs: dict, cg: dict, ba: dict) -> str:
    ba_running = bool(procs.get("synthesize_adapter") or procs.get("mini"))
    lines = [f"=== Pipeline status: {method_id}  ({time.strftime('%H:%M:%S')}) ==="]

    lines.append("\n-- Processes --")
    any_running = False
    for name, plist in procs.items():
        if plist:
            any_running = True
            for p in plist:
                lines.append(f"  RUNNING  {name:<20} pid={p['pid']} elapsed={p['elapsed']}")
    if not any_running:
        lines.append("  (none of orchestrator/RepoLaunch/synthesize_adapter/mini are running)")

    lines.append("\n-- contract_gen (Stage 0-3) --")
    lines.append(f"  last stage marker: {cg['stage_marker'] or '(no log yet)'}")
    rl = cg["repolaunch"]
    if rl:
        lines.append(f"  RepoLaunch: {rl['n_turns']} agent turn(s), ~${rl['total_cost_usd']} so far")
        if rl["last_action"]:
            lines.append(f"    last action: {rl['last_action']}")
        if rl["result"]:
            lines.append(f"    result.json present: completed={rl['result'].get('completed')} docker_image={rl['result'].get('docker_image')}")
    if cg["repo_manifest"]:
        lines.append(f"  repo_manifest.json: repolaunch_status={cg['repo_manifest']['repolaunch_status']} image={cg['repo_manifest']['docker_image']}")
    if cg["contract_headline"]:
        lines.append(f"  model_contract.yaml: {cg['contract_headline']}")
        lines.append("  >>> contract_gen COMPLETE")
    else:
        lines.append("  contract_gen not yet complete (no model_contract.yaml)")

    lines.append("\n-- benchmark_adapt (Stage 4) --")
    if not ba["seeded"]:
        lines.append("  not started yet (no output dir)")
    else:
        lines.append(f"  script.py is a stub: {ba['stub']}")
        if ba["mini_progress"]:
            lines.append(f"  mini-swe-agent: step {ba['mini_progress']['step']}, ~${ba['mini_progress']['cost_usd']} so far")
        if ba["trajectory"]:
            lines.append(f"  trajectory.json: {ba['trajectory']}")
        if ba_running:
            lines.append("  RUNNING -- not done yet (trajectory.json is written incrementally, its presence alone isn't completion)")
        elif ba["trajectory"] or ba["stub"] is False:
            lines.append("  >>> benchmark_adapt synthesis COMPLETE (no process running, and script.py/trajectory.json present)")
        else:
            lines.append("  seeded but neither running nor complete -- check log_tail below for what happened")
        if ba["log_tail"]:
            lines.append("  recent log lines:")
            for l in ba["log_tail"]:
                lines.append(f"    {l}")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--method-id", default="scape")
    ap.add_argument("--contract-gen-log", type=Path, default=None, help="Default: methods/results/<method-id>/logs/stage0-3_contract_gen.log")
    ap.add_argument("--benchmark-adapt-log", type=Path, default=None, help="Default: methods/results/<method-id>/logs/stage4_benchmark_adapt.log")
    ap.add_argument("--watch", action="store_true", help="Refresh continuously until Ctrl-C")
    ap.add_argument("--interval", type=float, default=10.0)
    args = ap.parse_args()

    logs_dir = RESULTS_ROOT / args.method_id / "logs"
    contract_gen_log = args.contract_gen_log or (logs_dir / "stage0-3_contract_gen.log")
    benchmark_adapt_log = args.benchmark_adapt_log or (logs_dir / "stage4_benchmark_adapt.log")

    while True:
        procs = find_processes(_ps_aux())
        cg = contract_gen_status(args.method_id, contract_gen_log)
        ba = benchmark_adapt_status(args.method_id, benchmark_adapt_log)
        output = render(args.method_id, procs, cg, ba)

        if args.watch:
            os.system("clear")
            print(output)
            print(f"\n(refreshing every {args.interval}s -- Ctrl-C to stop)")
            time.sleep(args.interval)
        else:
            print(output)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
