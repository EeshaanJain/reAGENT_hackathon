from __future__ import annotations

import numpy as np

from benchmark_ingest import compute_qc_metrics, filter_with_audit, summarize_qc


def test_compute_and_summarize_qc(valid_adata) -> None:
    compute_qc_metrics(valid_adata)

    np.testing.assert_array_equal(valid_adata.obs["total_counts"], [3, 3, 4])
    np.testing.assert_array_equal(valid_adata.obs["n_genes_by_counts"], [2, 1, 2])
    np.testing.assert_allclose(valid_adata.obs["pct_counts_mt"], [100 / 3, 0, 50])
    np.testing.assert_array_equal(valid_adata.var["total_counts"], [3, 5, 2])
    np.testing.assert_array_equal(valid_adata.var["n_cells_by_counts"], [2, 2, 1])

    summary = summarize_qc(valid_adata, by=("batch", "control"))
    assert summary["n_cells"].sum() == 3
    assert set(summary.columns) >= {"batch", "control", "total_counts_q05", "pct_counts_mt_q95"}


def test_filter_with_audit_uses_caller_selected_masks(valid_adata) -> None:
    filtered, audit = filter_with_audit(
        valid_adata,
        cell_mask=[True, False, True],
        gene_mask=[False, True, True],
        decisions={"cell_rule": "fixture", "gene_rule": "fixture"},
    )

    assert filtered.shape == (2, 2)
    assert audit["cells_removed"] == 1
    assert audit["genes_removed"] == 1
    assert audit["decisions"]["cell_rule"] == "fixture"
