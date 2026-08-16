from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import anndata as ad
import pandas as pd
import yaml

from benchmark_ingest import inspect_anndata, load_ingest_contract, validate_ingested_adata


def test_validate_counts_only_contract(valid_adata, ingest_contract) -> None:
    report = validate_ingested_adata(valid_adata, ingest_contract)

    assert report.ok
    assert report.summary == {"n_obs": 3, "n_vars": 3}


def test_validation_rejects_x_split_and_bad_control_mapping(valid_adata, ingest_contract) -> None:
    invalid = valid_adata.copy()
    invalid.X = invalid.layers["counts"].copy()
    invalid.obs["split"] = "train"
    invalid.obs.loc["cell_2", "control"] = True

    report = validate_ingested_adata(invalid, ingest_contract)

    assert not report.ok
    assert any("X must be None" in error for error in report.errors)
    assert any("split" in error for error in report.errors)
    assert any("exactly match" in error for error in report.errors)


def test_validation_rejects_missing_single_cell_protocol(valid_adata, ingest_contract) -> None:
    invalid = valid_adata.copy()
    del invalid.uns["single_cell_protocol"]

    report = validate_ingested_adata(invalid, ingest_contract)

    assert not report.ok
    assert any('uns["single_cell_protocol"]' in error for error in report.errors)


def test_counts_only_h5ad_round_trip_and_inventory(valid_adata, ingest_contract, tmp_path) -> None:
    output = tmp_path / "counts_only.h5ad"
    valid_adata.write_h5ad(output)
    reopened = ad.read_h5ad(output)

    inventory = inspect_anndata(reopened)
    assert inventory["X"] == {"present": False}
    assert None not in inventory["layers"]
    assert inventory["layers"]["counts"]["sparse"] is True
    assert inventory["uns_keys"] == ["single_cell_protocol"]
    assert validate_ingested_adata(reopened, ingest_contract).ok
    backed = ad.read_h5ad(output, backed="r")
    try:
        assert inspect_anndata(backed)["layers"]["counts"]["shape"] == [3, 3]
        assert validate_ingested_adata(backed, ingest_contract).ok
    finally:
        backed.file.close()


def test_validation_accepts_complete_nullable_boolean(valid_adata, ingest_contract) -> None:
    valid_adata.obs["control"] = valid_adata.obs["control"].astype("boolean")

    assert validate_ingested_adata(valid_adata, ingest_contract).ok

    valid_adata.obs.loc["cell_2", "control"] = pd.NA
    report = validate_ingested_adata(valid_adata, ingest_contract)
    assert not report.ok
    assert any("must not contain missing" in error for error in report.errors)


def test_validation_reports_invalid_boolean_without_crashing(valid_adata, ingest_contract) -> None:
    valid_adata.obs["control"] = ["yes", "no", "no"]

    report = validate_ingested_adata(valid_adata, ingest_contract)

    assert not report.ok
    assert any("must have boolean dtype" in error for error in report.errors)


def test_contract_controls_group_minimum_and_cell_maximum(valid_adata, ingest_contract) -> None:
    group_rules = tuple(replace(rule, minimum=2) for rule in ingest_contract.group_size_rules)
    strict = replace(ingest_contract, group_size_rules=group_rules, max_obs_exclusive=3)

    report = validate_ingested_adata(valid_adata, strict)

    assert any("undersized groups" in error for error in report.errors)
    assert any("n_obs must be less than 3" in error for error in report.errors)


def test_validator_is_generic_over_column_names_labels_and_orientation(
    valid_adata,
    tmp_path,
) -> None:
    source = yaml.safe_load(
        Path("benchmarks/perturbation_prediction/ingest_contract.yaml").read_text()
    )
    source["obs"]["required_fields"]["concentration"] = source["obs"]["required_fields"].pop(
        "dose_uM"
    )
    source["obs"]["required_fields"]["treatment"] = source["obs"]["required_fields"].pop(
        "sm_name"
    )
    source["obs"]["required_fields"]["is_reference"] = source["obs"]["required_fields"].pop(
        "control"
    )
    indicator = source["obs"]["relations"]["indicators"][0]
    indicator.update(
        indicator_column="is_reference",
        value_column="treatment",
        equals="reference",
    )
    conditional = source["obs"]["relations"]["conditional_formats"][0]
    conditional["when"] = {"column": "is_reference", "equals": False}
    source["obs"]["group_size_rules"][0] = {
        "columns": ["treatment", "timepoint_hr", "concentration", "cell_type"],
        "minimum": 1,
    }
    source["uns"]["required_fields"][2]["allowed_values"] = ["forward"]
    source["limits"]["max_obs_exclusive"] = 10
    path = tmp_path / "alternate.yaml"
    path.write_text(yaml.safe_dump(source, sort_keys=False))

    alternate = valid_adata.copy()
    alternate.obs = alternate.obs.rename(
        columns={"dose_uM": "concentration", "sm_name": "treatment", "control": "is_reference"}
    )
    alternate.obs.loc[alternate.obs["is_reference"], "treatment"] = "reference"
    alternate.uns["single_cell_protocol"]["capture_orientation"] = "forward"

    assert validate_ingested_adata(alternate, load_ingest_contract(path)).ok
