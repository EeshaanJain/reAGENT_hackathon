"""Stage 4 driver: adapter synthesis.

Consumes the three-artifact handoff from Cecilia's lane (model_contract.yaml, a built Docker
image, execution_log.json), renders a task prompt, and invokes mini-swe-agent (`mini`) against
that image to produce script.py / config.vsh.yaml / test.py under output/<method_id>/.

Refuses to run if any of the three handoff artifacts is missing, and refuses (ScopeRejection) if
the contract's perturbation_encoding is gene_id -- see harness/contract.py.

Defaults to --dry-run: renders the prompt and prints the exact `mini` invocation without spending
any API budget. Verified against a real install: `mini --help` (mini-swe-agent 2.4.6) and
minisweagent/environments/docker.py's DockerEnvironmentConfig (fields: image, cwd, env, run_args,
timeout). The `-c environment.image=...` dotted-path form mirrors the `-c model.model_kwargs...`
example in `mini --help`'s own docs, but has not been exercised against a live model + API key --
double check https://mini-swe-agent.com/latest/usage/mini/ before the first --execute run, and
see C2 in method-integration-todo.html (RepoLaunch is a second, separate LLM integration with its
own cost -- mini-swe-agent here is a third; budget and log both, per execution_log.json's schema).
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from harness.contract import ContractValidationError, ScopeRejection, load_contract, require_valid, scope_gate

ROOT = Path(__file__).parent.parent
PROMPT_DIR = Path(__file__).parent / "prompts"
TEMPLATE_DIR = ROOT / "component_template"


class MissingHandoffArtifact(Exception):
    """Raised when model_contract.yaml, the Docker image, or execution_log.json isn't provided.

    All three are required, not optional conveniences -- see the discussion this harness was built
    from: the contract says what the model needs, the image is where synthesis can actually be
    validated by running it, and the execution log is the ground truth of what already
    worked/failed, which the contract alone can't tell you.
    """


def _summarize_execution_log(execution_log_path: Path | None) -> str:
    if execution_log_path is None:
        return "(no execution_log.json provided)"
    log = json.loads(execution_log_path.read_text())
    lines = [f"total_wall_clock_s={log.get('total_wall_clock_s', '?')}"]
    for cmd in log.get("commands", []):
        status = "ok" if cmd.get("returncode") == 0 else f"FAILED (rc={cmd.get('returncode')})"
        note = f" -- {cmd['note']}" if cmd.get("note") else ""
        lines.append(f"  [{cmd.get('stage', '?')}] {cmd.get('cmd', '?')}: {status}{note}")
    return "\n".join(lines)


def render_prompt(*, contract, method_id: str, docker_image: str, execution_log_path: Path | None, output_dir: Path, fixture_dir: Path) -> str:
    env = Environment(loader=FileSystemLoader(str(PROMPT_DIR)), trim_blocks=True, lstrip_blocks=True)
    template = env.get_template("adapter_synthesis.md.j2")

    contract_yaml_str = json.dumps(contract.raw, indent=2)  # rendered as a fenced block; JSON is valid enough for the prompt

    return template.render(
        method_id=method_id,
        contract_yaml=contract_yaml_str,
        docker_image=docker_image,
        execution_log_summary=_summarize_execution_log(execution_log_path),
        output_dir=str(output_dir),
        fixture_dir=str(fixture_dir),
        input_layer=contract.get("input_layer"),
        layer_bounds=None,  # filled in by the caller if the contract declares bounds; not modeled yet
        requires_sc_counts=contract.get("requires_sc_counts"),
        dockerfile_setup="(transcribed by Cecilia's Stage 1 -- see environment.dockerfile_source in the contract; "
        "this driver does not re-derive it, only points the agent at engines.docker.image)",
    )


def build_mini_invocation(
    *,
    prompt_text: str,
    docker_image: str,
    model: str,
    cost_limit: float,
    output_traj: Path,
    workdir: Path,
) -> list[str]:
    """Assemble the `mini` CLI invocation. See module docstring re: what's verified vs. assumed."""
    return [
        "mini",
        "--yolo",
        "--model", model,
        "--task", prompt_text,
        "--cost-limit", str(cost_limit),
        "--output", str(output_traj),
        "--environment-class", "docker",
        "-c", f"environment.image={docker_image}",
        "-c", f"environment.cwd={workdir}",
    ]


def synthesize(
    *,
    contract_path: Path,
    docker_image: str | None,
    execution_log_path: Path | None,
    output_dir: Path,
    fixture_dir: Path,
    model: str,
    cost_limit: float,
    execute: bool,
) -> int:
    if docker_image is None:
        raise MissingHandoffArtifact(
            "no --docker-image given. Stage 4 assumes Cecilia's built image already exists -- "
            "pass its tag/ref, or supply a model_contract.yaml whose environment.image is set."
        )

    contract = require_valid(load_contract(contract_path))

    try:
        scope_gate(contract)
    except ScopeRejection as e:
        print(f"SCOPE REJECTION: {e.reason}", file=sys.stderr)
        print(json.dumps(e.eval_record, indent=2), file=sys.stderr)
        return 2

    method_id = contract.raw.get("method_id", "unknown_method")
    output_dir = output_dir / method_id
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = render_prompt(
        contract=contract,
        method_id=method_id,
        docker_image=docker_image,
        execution_log_path=execution_log_path,
        output_dir=output_dir,
        fixture_dir=fixture_dir,
    )
    prompt_path = output_dir / "synthesis_prompt.md"
    prompt_path.write_text(prompt_text)

    # MODELSPEC.json travels with the component -- it's part of the deliverable directory
    # structure (config.vsh.yaml, script.py, test.py, MODELSPEC.json, DEVIATIONS.md), not just an
    # internal handoff artifact that stays behind in Cecilia's lane.
    (output_dir / "MODELSPEC.json").write_text(json.dumps(contract.raw, indent=2))

    # Seed the output dir with the templates so the agent has a concrete starting point rather
    # than a blank page -- it's expected to overwrite script.py's NotImplementedError body.
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), trim_blocks=True, lstrip_blocks=True)
    # Jinja's built-in `tojson` is HTML-safe (escapes "'" etc. as ' for <script> embedding) --
    # wrong tool for plain YAML text. config.vsh.yaml.j2 uses `| tojson` to get valid, properly
    # quoted/escaped YAML scalars for argument defaults/descriptions; plain json.dumps is correct here.
    env.filters["tojson"] = json.dumps
    templates = [
        ("script.py.j2", "script.py"),
        ("config.vsh.yaml.j2", "config.vsh.yaml"),
        ("test.py.j2", "test.py"),
        ("DEVIATIONS.md.j2", "DEVIATIONS.md"),
    ]
    for template_name, out_name in templates:
        rendered = env.get_template(template_name).render(
            method_id=method_id,
            docker_image=docker_image,
            repo_url=contract.get("model", "repo"),
            commit=contract.raw.get("model", {}).get("commit"),
            prediction_level=contract.get("prediction_level"),
            input_layer=contract.get("input_layer"),
            perturbation_encoding=contract.get("perturbation_encoding"),
            requires_sc_counts=contract.get("requires_sc_counts"),
            gene_space=contract.raw.get("gene_space"),
            entrypoint=contract.get("model", "entrypoint"),
            preferred_normalization="unknown",
            gpu_required=contract.get("environment", "gpu_required"),
            # Populated when Stage 2 ran with --comprehension-engine serena (see
            # serena_contract_mapping.py); [] for a heuristic-only contract, same as before.
            arguments=contract.raw.get("arguments") or [],
            dependencies=contract.raw.get("dependencies") or [],
        )
        (output_dir / out_name).write_text(rendered)

    traj_path = output_dir / "trajectory.json"
    cmd = build_mini_invocation(
        prompt_text=prompt_text,
        docker_image=docker_image,
        model=model,
        cost_limit=cost_limit,
        output_traj=traj_path,
        workdir=output_dir,
    )

    print(f"method_id: {method_id}")
    print(f"contract:  {contract_path}  (valid, citation-clean, scope: pass)")
    print(f"seeded:    {output_dir}/{{script.py, config.vsh.yaml, test.py, DEVIATIONS.md, MODELSPEC.json, synthesis_prompt.md}}")
    print(f"mini invocation ({'EXECUTING' if execute else 'dry-run, not executed'}):")
    print("  " + " ".join(shlex.quote(c) for c in cmd))

    if not execute:
        print("\nPass --execute (with a real --model and API credentials configured for mini-swe-agent's "
              "litellm backend) to actually run synthesis. This will spend API budget -- log cost/wall-clock "
              "into execution_log.json per C2, same as RepoLaunch's own budget.")
        return 0

    if shutil.which("docker") is None:
        print("docker executable not found on PATH -- mini's docker environment class needs it.", file=sys.stderr)
        return 1

    result = subprocess.run(cmd, cwd=output_dir)
    return result.returncode


def main():
    ap = argparse.ArgumentParser(description="Stage 4: synthesize a benchmark adapter from a model_contract.yaml")
    ap.add_argument("--contract", required=True, type=Path, help="Path to model_contract.yaml / MODELSPEC.json")
    ap.add_argument("--docker-image", type=str, default=None, help="Built image tag/ref from Cecilia's Stage 1")
    ap.add_argument("--execution-log", type=Path, default=None, help="Path to execution_log.json")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "output", help="Where to write <method_id>/")
    ap.add_argument("--fixture-dir", type=Path, default=ROOT / "fixtures" / "data")
    ap.add_argument("--model", type=str, default="unset-configure-me", help="Model for mini-swe-agent, e.g. a litellm model id")
    ap.add_argument("--cost-limit", type=float, default=2.0)
    ap.add_argument("--execute", action="store_true", help="Actually invoke mini (default: dry-run only)")
    args = ap.parse_args()

    docker_image = args.docker_image
    if docker_image is None:
        # fall back to the contract's own declared image, if the caller didn't override it
        try:
            contract = load_contract(args.contract)
            docker_image = contract.get("environment", "image", default=None)
        except Exception:
            pass

    try:
        rc = synthesize(
            contract_path=args.contract,
            docker_image=docker_image,
            execution_log_path=args.execution_log,
            output_dir=args.output_dir,
            fixture_dir=args.fixture_dir,
            model=args.model,
            cost_limit=args.cost_limit,
            execute=args.execute,
        )
    except (MissingHandoffArtifact, ContractValidationError) as e:
        print(f"REFUSING TO RUN: {e}", file=sys.stderr)
        raise SystemExit(1)

    raise SystemExit(rc)


if __name__ == "__main__":
    main()
