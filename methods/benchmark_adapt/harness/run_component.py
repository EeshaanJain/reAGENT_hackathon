"""Run a synthesized component against real input data and write its output file.

This is the harness's own "does the thing it produced actually work" step -- a rendered
config.vsh.yaml/script.py that were never executed aren't a finished deliverable, they're an
untested claim. Deliberately does **not** compute or save any scoring metric (MRRMSE or otherwise)
-- that's a separate downstream concern from generation, not something this module does.

Reuses viash_shim.run_component() (the same par/meta substitution `viash build` would do) --
no new execution mechanism here, just a stable entry point plus output-file verification.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import viash_shim


def default_par_meta(script_path: Path) -> tuple[dict, dict]:
    """Extract a script's own `par`/`meta` dict from its `## VIASH START` ... `## VIASH END`
    block -- the VIASH-convention defaults meant for local testing (see viash_shim.py's docstring).
    Every synthesized adapter declares these, so using them as a base -- rather than assuming a
    fixed par schema here -- is what stays correct across whatever par keys a given method actually
    needs (a DE-signature method needs `de_train`/`layer`; a single-cell method needs `sc_train`;
    neither is hardcoded here).
    """
    lines = script_path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "## VIASH START")
    end = next(i for i, l in enumerate(lines) if l.strip() == "## VIASH END")
    namespace: dict = {}
    exec("\n".join(lines[start + 1 : end]), namespace)  # noqa: S102 -- our own generated script, not untrusted input
    return namespace.get("par", {}), namespace.get("meta", {})


def run_and_verify(
    script_path: Path,
    *,
    par_overrides: dict | None = None,
    meta_overrides: dict | None = None,
    workdir: Path | None = None,
    timeout: int = 600,
) -> dict:
    """Run `script_path` with its own VIASH-block defaults, overridden by `par_overrides`, and
    confirm the declared output file actually landed and is a readable AnnData. Returns a plain
    dict report (JSON-serializable) -- no metric fields, by design.
    """
    # Resolve to absolute before viash_shim.run_component() changes the subprocess's cwd to
    # `workdir` -- a relative script_path/workdir combined with that cwd change is exactly the
    # kind of bug this guards against (hit for real: a relative --script path resolved to a
    # doubled, broken path once the subprocess's cwd no longer matched the caller's).
    script_path = script_path.resolve()
    workdir = (workdir or script_path.parent).resolve()
    par, meta = default_par_meta(script_path)
    par.update(par_overrides or {})
    meta.update(meta_overrides or {})
    if "output" not in par:
        raise ValueError("par must include 'output' (either from the script's own VIASH block or --par)")

    report: dict = {"script": str(script_path), "par": par, "meta": meta}

    result = viash_shim.run_component(script_path, par, meta=meta, workdir=workdir, timeout=timeout)
    report["returncode"] = result.returncode
    report["stdout_tail"] = result.stdout[-4000:]
    report["stderr_tail"] = result.stderr[-4000:]

    if not result.ok:
        report["status"] = "FAILED"
        return report

    output_path = Path(par["output"])
    if not output_path.exists():
        report["status"] = "FAILED"
        report["error"] = "script exited 0 but did not write the declared par['output'] file"
        return report

    import anndata as ad

    output = ad.read_h5ad(output_path)
    report["status"] = "OK"
    report["output_file"] = str(output_path)
    report["output_shape"] = list(output.shape)
    report["output_layers"] = list(output.layers.keys())
    report["output_obs_columns"] = list(output.obs.columns)
    report["output_uns_keys"] = list(output.uns.keys())
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--script", required=True, type=Path, help="Path to the synthesized script.py")
    ap.add_argument("--par", type=Path, default=None, help="JSON file of par overrides (e.g. real input paths)")
    ap.add_argument("--meta", type=Path, default=None, help="JSON file of meta overrides")
    ap.add_argument("--workdir", type=Path, default=None)
    ap.add_argument("--report", type=Path, default=None, help="Where to write the JSON report (default: alongside --par, or cwd)")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    par_overrides = json.loads(args.par.read_text()) if args.par else {}
    meta_overrides = json.loads(args.meta.read_text()) if args.meta else {}

    report = run_and_verify(
        args.script, par_overrides=par_overrides, meta_overrides=meta_overrides,
        workdir=args.workdir, timeout=args.timeout,
    )

    # Default alongside the actual output file (predictions/), not the script (component/) --
    # callers following the component/predictions/logs split should always pass par['output']
    # into predictions/, so this default naturally lands there too, without needing --report.
    default_report_dir = Path(par_overrides["output"]).parent if par_overrides.get("output") else args.script.parent
    report_path = args.report or (default_report_dir / "run_report.json")
    report_path.write_text(json.dumps(report, indent=2))

    if report["status"] != "OK":
        print(f"FAILED: {report.get('error', 'see stderr_tail in ' + str(report_path))}", file=sys.stderr)
        return 1

    print(f"OK: wrote {report['output_file']} shape={report['output_shape']} layers={report['output_layers']}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
