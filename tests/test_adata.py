from __future__ import annotations

import anndata as ad

from psls_tooling import inspect_anndata, validate_ingested_adata


def test_validate_counts_only_contract(valid_adata) -> None:
    report = validate_ingested_adata(valid_adata)

    assert report.ok
    assert report.summary == {"n_obs": 3, "n_vars": 3, "control_cells": 1}


def test_validation_rejects_x_split_and_bad_control_mapping(valid_adata) -> None:
    invalid = valid_adata.copy()
    invalid.X = invalid.layers["counts"].copy()
    invalid.obs["split"] = "train"
    invalid.obs.loc["cell_2", "control"] = True

    report = validate_ingested_adata(invalid)

    assert not report.ok
    assert any("X must be None" in error for error in report.errors)
    assert any("split" in error for error in report.errors)
    assert any("exactly match" in error for error in report.errors)


def test_validation_rejects_missing_single_cell_protocol(valid_adata) -> None:
    invalid = valid_adata.copy()
    del invalid.uns["single_cell_protocol"]

    report = validate_ingested_adata(invalid)

    assert not report.ok
    assert any('uns["single_cell_protocol"]' in error for error in report.errors)


def test_counts_only_h5ad_round_trip_and_inventory(valid_adata, tmp_path) -> None:
    output = tmp_path / "counts_only.h5ad"
    valid_adata.write_h5ad(output)
    reopened = ad.read_h5ad(output)

    inventory = inspect_anndata(reopened)
    assert inventory["X"] == {"present": False}
    assert None not in inventory["layers"]
    assert inventory["layers"]["counts"]["sparse"] is True
    assert inventory["uns_keys"] == ["single_cell_protocol"]
    assert validate_ingested_adata(reopened).ok
