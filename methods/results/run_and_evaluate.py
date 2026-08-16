"""Run a synthesized OP3 viash component against the benchmark_adapt fixture and score it.

Usage:
    python methods/results/run_and_evaluate.py <method_id>

Does two things a rendered config.vsh.yaml/script.py alone don't prove:
  1. Actually executes the component (via benchmark_adapt's viash_shim -- the same textual
     par/meta substitution `viash build` would do, see viash_shim.py's own docstring) against the
     real fixture de_train.h5ad/id_map.csv, and confirms it produces a genuine prediction.h5ad --
     an AnnData file with a layer literally named "prediction", OP3's own output-file convention
     (file_prediction.yaml).
  2. Scores that output against the fixture's held-out de_test.h5ad ground truth using MRRMSE
     (mean rowwise root-mean-squared-error) -- the same metric scAPE's own repo implements
     (scape/_losses.py:mrrmse) and OP3's own scoring component
     (task_perturbation_prediction/src/metrics/mean_rowwise_error, an R script -- reimplemented
     here in Python since no R/Rscript is available in this environment; same definition:
     mean over rows of sqrt(mean over columns of (pred - truth)^2)).

Writes <method_id>_prediction.h5ad and <method_id>_metrics.json into this directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).parent
BENCHMARK_ADAPT_ROOT = RESULTS_DIR.parent / "benchmark_adapt"
FIXTURE_DIR = BENCHMARK_ADAPT_ROOT / "fixtures" / "data"

sys.path.insert(0, str(BENCHMARK_ADAPT_ROOT))


def mrrmse(pred: "np.ndarray", truth: "np.ndarray") -> float:
    import numpy as np

    row_rmse = np.sqrt(np.mean((pred - truth) ** 2, axis=1))
    return float(np.mean(row_rmse))


def default_par_meta(script_path: Path) -> tuple[dict, dict]:
    """Extract the script's own `par`/`meta` dict from its `## VIASH START` ... `## VIASH END`
    block -- the VIASH-convention defaults meant for local testing (see viash_shim.py's docstring).
    Every synthesized adapter declares these (scAPE's real script does; the seeded template does
    too), so using them as a base -- rather than guessing a fixed par schema here -- is what stays
    correct across whatever par keys a given synthesized script actually needs (e.g. scAPE-derived
    adapters need "cell"/"epochs"/"n_genes"/...; a simpler adapter may need only "layer").
    """
    lines = script_path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "## VIASH START")
    end = next(i for i, l in enumerate(lines) if l.strip() == "## VIASH END")
    namespace: dict = {}
    exec("\n".join(lines[start + 1 : end]), namespace)  # noqa: S102 -- our own generated script, not untrusted input
    return namespace.get("par", {}), namespace.get("meta", {})


def main() -> int:
    import anndata as ad
    import numpy as np
    import pandas as pd

    from harness import viash_shim

    if len(sys.argv) != 2:
        print("usage: python run_and_evaluate.py <method_id>", file=sys.stderr)
        return 2
    method_id = sys.argv[1]

    script_path = BENCHMARK_ADAPT_ROOT / "output" / method_id / "script.py"
    if not script_path.exists():
        print(f"no synthesized component at {script_path}", file=sys.stderr)
        return 1

    pred_path = RESULTS_DIR / f"{method_id}_prediction.h5ad"
    par, meta = default_par_meta(script_path)
    par.update({
        "de_train": str(FIXTURE_DIR / "de_train.h5ad"),
        "id_map": str(FIXTURE_DIR / "id_map.csv"),
        "output": str(pred_path),
    })
    meta.setdefault("name", method_id)
    meta.setdefault("temp_dir", "/tmp")

    print(f"Running {script_path} against the fixture (de_train.h5ad + id_map.csv)...")
    print(f"par: {par}")
    result = viash_shim.run_component(script_path, par, meta=meta, workdir=RESULTS_DIR, timeout=600)
    report: dict = {
        "method_id": method_id,
        "script": str(script_path),
        "par": par,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }

    if not result.ok:
        report["status"] = "FAILED"
        print(f"Component execution FAILED (rc={result.returncode}). See stderr_tail in the report.")
        (RESULTS_DIR / f"{method_id}_metrics.json").write_text(json.dumps(report, indent=2))
        return 1

    if not pred_path.exists():
        report["status"] = "FAILED"
        report["error"] = "script exited 0 but did not write the declared output file"
        (RESULTS_DIR / f"{method_id}_metrics.json").write_text(json.dumps(report, indent=2))
        print(report["error"])
        return 1

    pred = ad.read_h5ad(pred_path)
    report["output_file"] = str(pred_path)
    report["output_shape"] = list(pred.shape)
    report["output_layers"] = list(pred.layers.keys())

    if "prediction" not in pred.layers:
        report["status"] = "FAILED"
        report["error"] = f"output has no 'prediction' layer (has: {list(pred.layers.keys())}) -- Gauntlet G1"
        (RESULTS_DIR / f"{method_id}_metrics.json").write_text(json.dumps(report, indent=2))
        print(report["error"])
        return 1

    pred_values = pred.layers["prediction"]
    if not np.isfinite(pred_values).all():
        report["status"] = "FAILED"
        report["error"] = "prediction contains NaN/Inf -- Gauntlet G6"
        (RESULTS_DIR / f"{method_id}_metrics.json").write_text(json.dumps(report, indent=2))
        print(report["error"])
        return 1

    id_map = pd.read_csv(FIXTURE_DIR / "id_map.csv")
    de_test = ad.read_h5ad(FIXTURE_DIR / "de_test.h5ad")
    if list(pred.obs_names) != [str(i) for i in id_map["id"]]:
        report["status"] = "FAILED"
        report["error"] = "obs_names != id_map['id'] (in order) -- Gauntlet G2"
        (RESULTS_DIR / f"{method_id}_metrics.json").write_text(json.dumps(report, indent=2))
        print(report["error"])
        return 1

    truth_layer = "clipped_sign_log10_pval" if "clipped_sign_log10_pval" in de_test.layers else list(de_test.layers.keys())[0]
    truth = pd.DataFrame(de_test.layers[truth_layer], index=de_test.obs_names, columns=de_test.var_names)
    truth = truth.loc[pred.obs_names, pred.var_names]

    score = mrrmse(pred_values, truth.to_numpy())
    zero_baseline = mrrmse(np.zeros_like(pred_values), truth.to_numpy())

    report["status"] = "OK"
    report["metric"] = "mrrmse"
    report["metric_vs_layer"] = truth_layer
    report["mrrmse"] = score
    report["mrrmse_zero_baseline"] = zero_baseline
    report["beats_zero_baseline"] = score < zero_baseline

    (RESULTS_DIR / f"{method_id}_metrics.json").write_text(json.dumps(report, indent=2))
    print(f"Component ran successfully. prediction.h5ad written to {pred_path}")
    print(f"MRRMSE vs. {truth_layer}: {score:.4f} (zero-prediction baseline: {zero_baseline:.4f})")
    print(f"Full report: {RESULTS_DIR / f'{method_id}_metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
