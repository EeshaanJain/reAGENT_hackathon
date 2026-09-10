#!/usr/bin/env python3
"""Drive a dataset ingest end to end with codex.

One prompt template serves every dataset; the only thing that changes per dataset
are the inputs below. This script turns those inputs into a committed
``dataset.yaml``, renders the shared prompt, runs ``codex exec`` unattended, keeps
the full agent trace, and then independently verifies the artifacts the agent
claims to have produced.

    uv run python scripts/run_ingest.py \\
      --benchmark benchmarks/perturbation_prediction \\
      --dataset-id emerald_bay_2026 \\
      --publication-url https://www.biorxiv.org/content/10.64898/2026.06.09.731197v1 \\
      --pdf data/2026.06.09.731197.full.pdf \\
      --data-url https://huggingface.co/datasets/tahoebio/EmeraldBay

    uv run python scripts/run_ingest.py --config benchmarks/.../emerald_bay_2026/dataset.yaml

Trace layout (gitignored):

    data_ingest/<dataset_id>/work/                 agent intermediates
    data_ingest/<dataset_id>/runs/<timestamp>/
        prompt.md  events.jsonl  stderr.log  command.json
        last_message.md  rollout.jsonl  run.json
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from agent_runner import (
    atomic_write_json,
    atomic_write_text,
    codex_version,
    resolve_codex_bin,
    run_codex_exec,
    sha256_path,
    utc_now,
    utc_stamp,
)
from benchmark_ingest import load_ingest_contract, render_ingest_prompt, validate_ingested_adata

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmarks" / "perturbation_prediction"
DEFAULT_SCRATCH = ROOT / "data_ingest"
# Ingests download multi-GB deposited matrices and stream them once; six hours.
DEFAULT_TIMEOUT = 21600

# Copied into a freshly created dataset.yaml. Kept in step with the benchmark's
# ingest_contract.yaml, which render_ingest_prompt cross-checks.
DEFAULT_SUBSET = {
    "condition_columns": ["sm_name", "timepoint_hr", "dose_uM", "cell_type"],
    "control_column": "control",
    "minimum_condition_size": 30,
    "target_min_cells": 195000,
    "minimum_acceptable_cells": 190000,
    "max_cells_exclusive": 200000,
    "seed": 42,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    inputs = parser.add_argument_group("dataset inputs")
    inputs.add_argument("--config", type=Path, help="Re-run from an existing dataset.yaml")
    inputs.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    inputs.add_argument("--dataset-id")
    inputs.add_argument("--publication-url")
    inputs.add_argument("--pdf", dest="local_pdf_path", help="Local publication PDF")
    inputs.add_argument("--data-url", dest="data_url_or_accession", help="Deposited data URL or accession")
    inputs.add_argument("--code-url", dest="code_url")
    inputs.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional dataset input rendered into the prompt (repeatable)",
    )
    inputs.add_argument(
        "--force", action="store_true", help="Overwrite an existing dataset.yaml"
    )

    agent = parser.add_argument_group("agent")
    agent.add_argument("--codex-bin", help="Path to the codex executable (default: PATH, then ChatGPT.app)")
    agent.add_argument("--model", help="Override the model (default: ~/.codex/config.toml)")
    agent.add_argument(
        "--reasoning-effort", help="Override reasoning effort (default: ~/.codex/config.toml)"
    )
    agent.add_argument(
        "--sandbox",
        default="workspace-write",
        choices=["read-only", "workspace-write", "danger-full-access"],
    )
    agent.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Seconds (default: 6h)")
    agent.add_argument("--resume", dest="resume_session_id", help="Resume a previous codex session id")
    agent.add_argument(
        "--prepare-only",
        action="store_true",
        help="Render the prompt and set up the run directory, but do not run codex",
    )
    agent.add_argument("--scratch-root", type=Path, default=DEFAULT_SCRATCH)
    return parser.parse_args(argv)


def parse_extras(items: list[str]) -> dict[str, str]:
    extras: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key.strip():
            raise SystemExit(f"--extra expects KEY=VALUE, got {item!r}")
        extras[key.strip()] = value.strip()
    return extras


def build_dataset_config(args: argparse.Namespace) -> dict[str, Any]:
    """Assemble a dataset.yaml payload from command-line inputs."""
    if not args.dataset_id:
        raise SystemExit("--dataset-id is required unless --config is given")
    if not args.publication_url:
        raise SystemExit("--publication-url is required unless --config is given")

    dataset: dict[str, Any] = {
        "dataset_id": args.dataset_id,
        "publication_url": args.publication_url,
    }
    for key in ("data_url_or_accession", "code_url", "local_pdf_path"):
        value = getattr(args, key)
        if value:
            dataset[key] = value
    dataset.update(parse_extras(args.extra))

    return {
        "dataset": dataset,
        "prompt_template": "../../prompts/data_ingest.md.template",
        "ingest_contract": "../../ingest_contract.yaml",
        "subset": dict(DEFAULT_SUBSET),
    }


def resolve_config(args: argparse.Namespace) -> Path:
    """Return the dataset.yaml path, writing it first when driven by flags."""
    if args.config is not None:
        path = args.config.resolve()
        if not path.is_file():
            raise SystemExit(f"dataset config not found: {path}")
        conflicting = [
            name
            for name in ("dataset_id", "publication_url", "local_pdf_path", "data_url_or_accession", "code_url")
            if getattr(args, name)
        ]
        if conflicting or args.extra:
            raise SystemExit(
                "--config is mutually exclusive with the dataset input flags; "
                "edit the config instead"
            )
        return path

    config = build_dataset_config(args)
    path = (args.benchmark.resolve() / "datasets" / args.dataset_id / "dataset.yaml").resolve()
    if path.exists() and not args.force:
        raise SystemExit(f"{path} already exists; pass --config to reuse it or --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    print(f"wrote {path}")
    return path


def git_revision() -> dict[str, Any]:
    def run(*command: str) -> str | None:
        try:
            completed = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return completed.stdout.strip() if completed.returncode == 0 else None

    head = run("git", "rev-parse", "HEAD")
    status = run("git", "status", "--porcelain")
    return {"head": head, "dirty": bool(status) if status is not None else None}


def verify_artifacts(dataset_id: str, dataset_dir: Path, contract_path: Path, subset: dict) -> dict:
    """Independently check what the agent produced. Never trust last_message.md."""
    import anndata as ad

    h5ad = ROOT / "data" / "processed" / f"{dataset_id}.h5ad"
    report: dict[str, Any] = {
        "ingest_script": _file_status(dataset_dir / "ingest.py"),
        "ingest_params": _file_status(dataset_dir / "ingest_params.yaml"),
        "ingest_report": _file_status(dataset_dir / "ingest_report.md"),
        "h5ad": _file_status(h5ad),
    }
    problems = [
        name
        for name in ("ingest_script", "ingest_report", "h5ad")
        if not report[name]["exists"]
    ]
    if problems:
        report["ok"] = False
        report["errors"] = [f"missing expected artifact: {name}" for name in problems]
        return report

    report["h5ad"]["sha256"] = sha256_path(h5ad)
    contract = load_ingest_contract(contract_path)
    adata = ad.read_h5ad(h5ad)
    try:
        validation = validate_ingested_adata(adata, contract)
        errors = list(validation.errors)
        max_cells = int(subset["max_cells_exclusive"])
        if adata.n_obs >= max_cells:
            errors.append(f"n_obs={adata.n_obs} is not below max_cells_exclusive={max_cells}")
        report.update(
            {
                "n_obs": int(adata.n_obs),
                "n_vars": int(adata.n_vars),
                "errors": errors,
                "warnings": list(validation.warnings),
                "summary": validation.summary,
                "ok": not errors,
            }
        )
    finally:
        del adata
    return report


def _file_status(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "exists": exists,
        "bytes": path.stat().st_size if exists else None,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = resolve_config(args)
    config = yaml.safe_load(config_path.read_text())
    dataset_id = str(config["dataset"]["dataset_id"])
    dataset_dir = config_path.parent
    contract_path = (dataset_dir / config["ingest_contract"]).resolve()

    scratch = args.scratch_root.resolve() / dataset_id
    work_dir = scratch / "work"
    run_dir = scratch / "runs" / utc_stamp()
    work_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Renders strictly: a missing input or a subset/contract disagreement fails
    # here, before any agent time is spent.
    prompt = render_ingest_prompt(config_path, work_dir=work_dir)
    atomic_write_text(run_dir / "prompt.md", prompt)

    codex_bin = resolve_codex_bin(args.codex_bin)
    template_path = (dataset_dir / config["prompt_template"]).resolve()
    provenance = {
        "dataset_id": dataset_id,
        "dataset_config": config_path.relative_to(ROOT).as_posix(),
        "dataset_config_sha256": sha256_path(config_path),
        "template_sha256": sha256_path(template_path),
        "contract_sha256": sha256_path(contract_path),
        "codex_bin": codex_bin,
        "codex_version": codex_version(codex_bin),
        "git": git_revision(),
    }

    if args.prepare_only:
        atomic_write_json(
            run_dir / "run.json",
            {"status": "prepared", "prepared_at": utc_now(), "run_dir": str(run_dir), **provenance},
        )
        print(f"prompt:   {run_dir / 'prompt.md'}")
        print(f"work dir: {work_dir}")
        print(f"run dir:  {run_dir}")
        print("\nrun:")
        print(f"  {codex_bin} exec --json --cd {ROOT} --sandbox {args.sandbox} \\")
        print("    --config sandbox_workspace_write.network_access=true \\")
        print(f"    --output-last-message {run_dir / 'last_message.md'} - < {run_dir / 'prompt.md'}")
        return 0

    print(f"running codex for {dataset_id}; trace -> {run_dir}")
    result = run_codex_exec(
        prompt,
        run_dir,
        codex_bin=codex_bin,
        cwd=ROOT,
        sandbox=args.sandbox,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        resume_session_id=args.resume_session_id,
        timeout=args.timeout,
        metadata=provenance,
    )

    verification = verify_artifacts(dataset_id, dataset_dir, contract_path, config["subset"])
    record = {
        "status": "complete" if (result.ok and verification.get("ok")) else "failed",
        "argv": sys.argv,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "duration_seconds": result.duration_seconds,
        "session_id": result.session_id,
        "rollout": result.rollout_path.name if result.rollout_path else None,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "sandbox": args.sandbox,
        "prompt_sha256": sha256_path(run_dir / "prompt.md"),
        "verification": verification,
        **provenance,
    }
    atomic_write_json(run_dir / "run.json", record)

    if result.timed_out:
        print(f"codex exec timed out after {args.timeout}s; see {result.stderr_path}", file=sys.stderr)
    elif result.returncode != 0:
        print(
            f"codex exec exited {result.returncode}; see {result.stderr_path} and {result.events_path}",
            file=sys.stderr,
        )
    if not verification.get("ok"):
        print("artifact verification FAILED:", file=sys.stderr)
        for error in verification.get("errors", []):
            print(f"  - {error}", file=sys.stderr)
    else:
        print(
            f"verified {verification['n_obs']:,} cells x {verification['n_vars']:,} genes "
            f"-> data/processed/{dataset_id}.h5ad"
        )
    print(f"run record: {run_dir / 'run.json'}")
    return 0 if record["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
