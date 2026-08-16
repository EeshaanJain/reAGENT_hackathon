"""The Gauntlet's check implementations -- pure functions, reusable across every method.

Each check takes an already-produced prediction AnnData (+ reference data) and returns a
CheckResult. Kept dependency-light (numpy/pandas/anndata only) so these can be imported straight
into a Viash `test.py` later with no changes; only the *call site* that produces `pred` changes
(viash_shim.run_component() here -> a subprocess call into the built executable there).

These checks are ADDITIONAL to, not a reimplementation of, the real `viash test` gate. Verified
directly against the vendored OP3 submodule's actual shared test script
(common/component_tests/run_and_check_output.py): the real gate runs the compiled component,
asserts exit code 0, and checks that required schema slots (layer/uns keys from file_prediction.yaml)
are merely *present*. It does not check value ranges, row-order-exact-match, perturbation
sensitivity, network access, or run-to-run reproducibility -- that gap is what these checks exist
to close.

Output layer convention (verified against file_prediction.yaml and src/methods/scape/script.py's
real `layers={"prediction": ...}`): the output AnnData's prediction layer must always be named
literally "prediction", regardless of which de_train layer (`--layer`, default
clipped_sign_log10_pval) the model read as input. Callers pass "prediction" as `expected_layer`.

Maps directly onto plan_unified.md §6 / todo.html block G:
  G1 check_layer_conformance
  G2 check_id_map_alignment
  G3 check_perturbation_sensitivity
  G4 -- implemented as a pytest fixture in test_no_network.py, not a pure function (it has to wrap
        the *execution*, not just inspect the output)
  G6 check_output_sanity
  G7 check_stochastic_tolerance (deliberately requires an explicit tolerance -- see docstring)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd


@dataclass
class CheckResult:
    passed: bool
    message: str

    def __bool__(self) -> bool:
        return self.passed

    def assert_ok(self):
        assert self.passed, self.message


def check_layer_conformance(
    pred: ad.AnnData, expected_layer: str, bounds: tuple[float, float] | None
) -> CheckResult:
    """G1 -- the silent-killer check: model emits `logFC`, metric expects a bounded, differently
    scaled quantity like `clipped_sign_log10_pval` (bounded +/-4) -> garbage scores, zero errors.
    Assert the declared layer exists, is finite, and (if bounds are declared) stays in range.
    """
    if expected_layer not in pred.layers:
        available = list(pred.layers.keys())
        return CheckResult(False, f"expected layer '{expected_layer}' not found; adapter wrote {available}")

    values = np.asarray(pred.layers[expected_layer])
    if not np.all(np.isfinite(values)):
        n_bad = int((~np.isfinite(values)).sum())
        return CheckResult(False, f"layer '{expected_layer}' has {n_bad} non-finite value(s)")

    if bounds is not None:
        lo, hi = bounds
        out_of_range = int(((values < lo) | (values > hi)).sum())
        if out_of_range:
            return CheckResult(
                False,
                f"layer '{expected_layer}' has {out_of_range} value(s) outside declared bounds [{lo}, {hi}] "
                f"(observed range [{values.min():.3f}, {values.max():.3f}]) -- likely a unit/layer mismatch",
            )

    if np.allclose(values, 0.0):
        return CheckResult(False, f"layer '{expected_layer}' is all zeros -- adapter likely didn't write real predictions")

    return CheckResult(True, f"layer '{expected_layer}' present, finite, in range")


def check_id_map_alignment(pred: ad.AnnData, id_map: pd.DataFrame, gene_order: list[str] | None = None) -> CheckResult:
    """G2 -- exact id_map row order + gene space. Any reliance on the metric's `--resolve_genes`
    rescue is a hard fail in this pipeline, not a convenience, so this check does not attempt to
    reorder/reindex before comparing -- it compares as-is and fails loudly on mismatch.

    Row identity convention verified against src/methods/scape/script.py (a real, shipped OP3
    method): output obs is indexed by id_map's `id` column --
    `obs=pd.DataFrame(index=id_map["id"])` -- not by cell_type/sm_name columns.
    file_prediction.yaml requires no obs columns at all, so this check does not require
    cell_type/sm_name to be present on the output either -- only that obs_names match id_map["id"]
    exactly, in order.
    """
    if pred.n_obs != len(id_map):
        return CheckResult(False, f"row count mismatch: prediction has {pred.n_obs}, id_map has {len(id_map)}")

    pred_ids = list(pred.obs_names)
    expected_ids = [str(v) for v in id_map["id"]]
    if pred_ids != expected_ids:
        first_mismatch = next((i for i, (a, b) in enumerate(zip(pred_ids, expected_ids)) if a != b), None)
        return CheckResult(
            False,
            f"obs_names do not match id_map['id'] at index {first_mismatch}: "
            f"prediction={pred_ids[first_mismatch] if first_mismatch is not None else None!r} "
            f"id_map={expected_ids[first_mismatch] if first_mismatch is not None else None!r} "
            "(exact match required -- no --resolve_genes-style rescue here)",
        )

    if gene_order is not None:
        pred_genes = list(pred.var_names)
        if pred_genes != gene_order:
            return CheckResult(False, "gene order does not match the frozen fixture gene order (see fixture_manifest.json)")

    return CheckResult(True, "obs_names match id_map['id'] exactly, in order; gene space matches")


def check_output_sanity(pred: ad.AnnData, expected_layer: str, n_expected_genes: int) -> CheckResult:
    """G6 -- shape, no NaN/Inf, correct gene count. Broader than G1: this is the generic
    "didn't produce nonsense" check independent of the specific declared layer semantics.
    """
    if pred.n_vars != n_expected_genes:
        return CheckResult(False, f"gene count mismatch: expected {n_expected_genes}, got {pred.n_vars}")
    if expected_layer not in pred.layers:
        return CheckResult(False, f"layer '{expected_layer}' missing")
    values = np.asarray(pred.layers[expected_layer])
    if values.shape != (pred.n_obs, pred.n_vars):
        return CheckResult(False, f"layer shape {values.shape} != AnnData shape {(pred.n_obs, pred.n_vars)}")
    if np.isnan(values).any() or np.isinf(values).any():
        return CheckResult(False, "output contains NaN or Inf")
    return CheckResult(True, "output shape/values sane")


def check_perturbation_sensitivity(
    pred_real: ad.AnnData,
    pred_shuffled: ad.AnnData,
    expected_layer: str,
    *,
    min_median_rel_change: float = 0.05,
) -> CheckResult:
    """G3 -- shuffle sm_name in id_map, re-run, and require the prediction to change materially.
    Catches a model that has collapsed to predicting the training mean regardless of compound
    identity -- plausible-looking scores, zero actual perturbation-specificity.

    `min_median_rel_change` is a placeholder threshold (see README "what's real vs. a stand-in") --
    the plan flagged that "materially" was never turned into a number; 5% median relative L2 change
    is a starting point, not a validated one. Override it once the team decides G7/G3's real value.
    """
    for label, pred in (("real", pred_real), ("shuffled", pred_shuffled)):
        if expected_layer not in pred.layers:
            return CheckResult(
                False, f"'{expected_layer}' missing from the {label} run's output (see G1 for the layer-conformance check)"
            )

    real = np.asarray(pred_real.layers[expected_layer])
    shuffled = np.asarray(pred_shuffled.layers[expected_layer])
    if real.shape != shuffled.shape:
        return CheckResult(False, f"shape mismatch between real ({real.shape}) and shuffled ({shuffled.shape}) runs")

    row_norms = np.linalg.norm(real, axis=1)
    diffs = np.linalg.norm(real - shuffled, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel_change = np.where(row_norms > 1e-8, diffs / row_norms, diffs)
    median_rel_change = float(np.median(rel_change))

    if median_rel_change < min_median_rel_change:
        return CheckResult(
            False,
            f"median relative change after shuffling sm_name is {median_rel_change:.4f}, "
            f"below threshold {min_median_rel_change} -- prediction is likely insensitive to "
            "compound identity (collapsed to training mean)",
        )
    return CheckResult(True, f"median relative change after shuffle: {median_rel_change:.4f} (>= {min_median_rel_change})")


def check_stochastic_tolerance(
    pred1: ad.AnnData, pred2: ad.AnnData, expected_layer: str, tolerance: float | None
) -> CheckResult:
    """G7 -- "repeated runs are identical or within an explicitly defined stochastic tolerance."
    The flagged gap: no document anywhere defines that tolerance number. This function refuses to
    invent one -- pass tolerance=None and it returns a not-configured result rather than silently
    picking a number that would make the check meaningless.
    """
    if tolerance is None:
        return CheckResult(
            False,
            "G7 stochastic tolerance is not configured (see README / todo.html gap list) -- "
            "set BENCHMARK_ADAPT_STOCHASTIC_TOL or pass tolerance= explicitly before trusting this check",
        )
    for label, pred in (("first", pred1), ("second", pred2)):
        if expected_layer not in pred.layers:
            return CheckResult(False, f"'{expected_layer}' missing from the {label} run's output")

    v1 = np.asarray(pred1.layers[expected_layer])
    v2 = np.asarray(pred2.layers[expected_layer])
    max_abs_diff = float(np.max(np.abs(v1 - v2)))
    if max_abs_diff > tolerance:
        return CheckResult(False, f"max abs diff between repeated runs is {max_abs_diff:.4f}, exceeds tolerance {tolerance}")
    return CheckResult(True, f"max abs diff {max_abs_diff:.4f} within tolerance {tolerance}")
