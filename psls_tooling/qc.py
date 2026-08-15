"""Dataset-adaptive QC primitives that calculate evidence but choose no thresholds."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse

from .adata import get_counts


def _axis_sum(matrix: Any, axis: int) -> np.ndarray:
    return np.asarray(matrix.sum(axis=axis)).ravel()


def _detected_features(matrix: Any, axis: int) -> np.ndarray:
    if sparse.issparse(matrix):
        return np.asarray(matrix.getnnz(axis=axis)).ravel()
    return np.asarray(np.count_nonzero(matrix, axis=axis)).ravel()


def compute_qc_metrics(
    adata: Any,
    *,
    counts_layer: str = "counts",
    gene_symbol_col: str | None = None,
    mitochondrial_prefix: str = "MT-",
    inplace: bool = True,
) -> Any:
    """Calculate common cell and gene QC metrics from the canonical counts layer."""
    result = adata if inplace else adata.copy()
    counts = get_counts(result, layer=counts_layer)
    total_counts = _axis_sum(counts, axis=1)
    n_genes = _detected_features(counts, axis=1)

    symbols = result.var_names if gene_symbol_col is None else result.var[gene_symbol_col].astype(str)
    mitochondrial = pd.Index(symbols).astype(str).str.upper().str.startswith(mitochondrial_prefix.upper())
    mt_counts = _axis_sum(counts[:, mitochondrial], axis=1) if mitochondrial.any() else np.zeros(result.n_obs)
    pct_mt = np.divide(
        mt_counts * 100.0,
        total_counts,
        out=np.zeros_like(total_counts, dtype=float),
        where=total_counts > 0,
    )

    result.obs["total_counts"] = total_counts
    result.obs["n_genes_by_counts"] = n_genes
    result.obs["pct_counts_mt"] = pct_mt
    result.var["total_counts"] = _axis_sum(counts, axis=0)
    result.var["n_cells_by_counts"] = _detected_features(counts, axis=0)
    result.var["mt"] = mitochondrial
    return result


def summarize_qc(
    adata: Any,
    *,
    by: Sequence[str] = ("batch", "cell_type", "control"),
) -> pd.DataFrame:
    """Summarize QC distributions across caller-selected biological strata."""
    required_metrics = ("total_counts", "n_genes_by_counts", "pct_counts_mt")
    missing_metrics = [metric for metric in required_metrics if metric not in adata.obs]
    if missing_metrics:
        raise KeyError(f"Calculate QC metrics before summarizing; missing {missing_metrics}")
    missing_groups = [column for column in by if column not in adata.obs]
    if missing_groups:
        raise KeyError(f"QC grouping columns are missing: {missing_groups}")

    grouped = adata.obs.groupby(list(by), observed=True, dropna=False)
    summary = grouped.agg(
        n_cells=("total_counts", "size"),
        total_counts_median=("total_counts", "median"),
        total_counts_q05=("total_counts", lambda values: values.quantile(0.05)),
        total_counts_q95=("total_counts", lambda values: values.quantile(0.95)),
        n_genes_median=("n_genes_by_counts", "median"),
        n_genes_q05=("n_genes_by_counts", lambda values: values.quantile(0.05)),
        n_genes_q95=("n_genes_by_counts", lambda values: values.quantile(0.95)),
        pct_counts_mt_median=("pct_counts_mt", "median"),
        pct_counts_mt_q95=("pct_counts_mt", lambda values: values.quantile(0.95)),
    )
    return summary.reset_index()


def filter_with_audit(
    adata: Any,
    *,
    cell_mask: Sequence[bool],
    gene_mask: Sequence[bool],
    decisions: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    """Apply agent-selected QC masks and return a compact audit record."""
    cell_mask_array = np.asarray(cell_mask, dtype=bool)
    gene_mask_array = np.asarray(gene_mask, dtype=bool)
    if cell_mask_array.shape != (adata.n_obs,):
        raise ValueError(f"cell_mask must have shape {(adata.n_obs,)}, got {cell_mask_array.shape}")
    if gene_mask_array.shape != (adata.n_vars,):
        raise ValueError(f"gene_mask must have shape {(adata.n_vars,)}, got {gene_mask_array.shape}")

    filtered = adata[cell_mask_array, gene_mask_array].copy()
    audit = {
        "cells_before": int(adata.n_obs),
        "cells_after": int(filtered.n_obs),
        "cells_removed": int((~cell_mask_array).sum()),
        "genes_before": int(adata.n_vars),
        "genes_after": int(filtered.n_vars),
        "genes_removed": int((~gene_mask_array).sum()),
        "decisions": decisions,
    }
    return filtered, audit
