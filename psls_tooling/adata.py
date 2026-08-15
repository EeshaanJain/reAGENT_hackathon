"""AnnData inspection and validation helpers for dataset-ingestion agents."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse

from .chemistry import normalize_inchikey

REQUIRED_OBS_COLUMNS = (
    "dose_uM",
    "timepoint_hr",
    "cell_type",
    "sm_name",
    "inchikey",
    "batch",
    "control",
)
CONTROL_LABEL = "control"
CAPTURE_ORIENTATIONS = {"3prime", "5prime", "full_length", "unknown"}


@dataclass
class ValidationReport:
    """Structured validation result returned by :func:`validate_ingested_adata`."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Return whether validation completed without errors."""
        return not self.errors

    def raise_for_errors(self) -> None:
        """Raise one ``ValueError`` containing all validation errors."""
        if self.errors:
            raise ValueError("Invalid ingested AnnData:\n- " + "\n- ".join(self.errors))


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of a local source file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _sample_values(series: pd.Series, sample_size: int) -> list[str]:
    values = series.drop_duplicates().head(sample_size)
    return ["<NA>" if pd.isna(value) else str(value) for value in values]


def inspect_dataframe(frame: pd.DataFrame, *, sample_size: int = 5) -> list[dict[str, Any]]:
    """Summarize column semantics without assuming a dataset-specific schema."""
    return [
        {
            "column": str(column),
            "dtype": str(frame[column].dtype),
            "missing": int(frame[column].isna().sum()),
            "unique": int(frame[column].nunique(dropna=False)),
            "examples": _sample_values(frame[column], sample_size),
        }
        for column in frame.columns
    ]


def _matrix_inventory(matrix: Any) -> dict[str, Any]:
    if matrix is None:
        return {"present": False}
    return {
        "present": True,
        "type": type(matrix).__name__,
        "shape": [int(value) for value in matrix.shape],
        "dtype": str(matrix.dtype),
        "sparse": bool(sparse.issparse(matrix) or hasattr(matrix, "to_memory")),
    }


def inspect_anndata(adata: Any, *, sample_size: int = 5) -> dict[str, Any]:
    """Return a JSON-serializable inventory of an AnnData object."""
    raw_x = None if adata.raw is None else adata.raw.X
    return {
        "shape": [int(adata.n_obs), int(adata.n_vars)],
        "X": _matrix_inventory(adata.X),
        "raw_X": _matrix_inventory(raw_x),
        "layers": {name: _matrix_inventory(matrix) for name, matrix in adata.layers.items() if name is not None},
        "obs": inspect_dataframe(adata.obs, sample_size=sample_size),
        "var": inspect_dataframe(adata.var, sample_size=sample_size),
        "obs_names_unique": bool(adata.obs_names.is_unique),
        "var_names_unique": bool(adata.var_names.is_unique),
        "obsm_keys": list(adata.obsm.keys()),
        "obsp_keys": list(adata.obsp.keys()),
        "uns_keys": list(adata.uns.keys()),
    }


def get_counts(adata: Any, *, layer: str = "counts") -> Any:
    """Return the canonical counts matrix or raise a precise schema error."""
    if layer not in adata.layers:
        raise KeyError(f"Required AnnData layer {layer!r} is missing")
    return adata.layers[layer]


def _iter_nonzero_chunks(matrix: Any, chunk_size: int = 1_000_000):
    data = matrix.data if sparse.issparse(matrix) else np.asarray(matrix).ravel()
    for start in range(0, data.size, chunk_size):
        yield np.asarray(data[start : start + chunk_size])


def _validate_counts(matrix: Any, report: ValidationReport) -> None:
    if not sparse.issparse(matrix):
        report.errors.append('layers["counts"] must be a sparse matrix')
    if not np.issubdtype(matrix.dtype, np.number):
        report.errors.append('layers["counts"] must have a numeric dtype')
        return

    for values in _iter_nonzero_chunks(matrix):
        if not np.isfinite(values).all():
            report.errors.append('layers["counts"] contains non-finite values')
            break
        if (values < 0).any():
            report.errors.append('layers["counts"] contains negative values')
            break
        if not np.equal(values, np.rint(values)).all():
            report.errors.append('layers["counts"] contains non-integer values')
            break


def _validate_obs(adata: Any, report: ValidationReport) -> None:
    missing = [column for column in REQUIRED_OBS_COLUMNS if column not in adata.obs]
    if missing:
        report.errors.append(f"Missing required obs columns: {missing}")
        return

    obs = adata.obs
    for column in ("dose_uM", "timepoint_hr"):
        if not pd.api.types.is_numeric_dtype(obs[column]):
            report.errors.append(f"obs[{column!r}] must be numeric")
        elif obs[column].isna().any() or not np.isfinite(obs[column]).all() or (obs[column] < 0).any():
            report.errors.append(f"obs[{column!r}] must contain finite nonnegative values")

    for column in ("cell_type", "sm_name", "batch"):
        if obs[column].isna().any() or obs[column].astype(str).str.strip().eq("").any():
            report.errors.append(f"obs[{column!r}] must not contain missing or empty values")

    if not pd.api.types.is_bool_dtype(obs["control"]):
        report.errors.append('obs["control"] must have boolean dtype')
        return

    control = obs["control"]
    tag_matches = obs["sm_name"].astype(str).eq(CONTROL_LABEL)
    if not control.any():
        report.errors.append("At least one control observation is required")
    if not tag_matches.any():
        report.errors.append(f"The {CONTROL_LABEL!r} label does not occur in obs['sm_name']")
    if not control.equals(tag_matches):
        report.errors.append(f"obs['control'] must exactly match obs['sm_name'] == {CONTROL_LABEL!r}")

    treated_keys = obs.loc[~control, "inchikey"].map(normalize_inchikey)
    if treated_keys.isna().any():
        report.errors.append("Every treated observation must have a valid full InChIKey")


def _validate_single_cell_protocol(adata: Any, report: ValidationReport) -> None:
    protocol = adata.uns.get("single_cell_protocol")
    if not isinstance(protocol, Mapping):
        report.errors.append('uns["single_cell_protocol"] must be a mapping')
        return

    for field_name in ("chemistry", "capture_orientation", "source"):
        value = protocol.get(field_name)
        if not isinstance(value, str) or not value.strip():
            report.errors.append(
                f'uns["single_cell_protocol"][{field_name!r}] must be a non-empty string'
            )

    orientation = protocol.get("capture_orientation")
    if orientation not in CAPTURE_ORIENTATIONS:
        report.errors.append(
            'uns["single_cell_protocol"]["capture_orientation"] must be one of '
            f"{sorted(CAPTURE_ORIENTATIONS)}"
        )


def validate_ingested_adata(adata: Any, *, raise_on_error: bool = False) -> ValidationReport:
    """Validate the canonical counts-only, OP3-style ingestion contract."""
    report = ValidationReport(summary={"n_obs": int(adata.n_obs), "n_vars": int(adata.n_vars)})
    if adata.X is not None:
        report.errors.append("X must be None; raw counts belong only in layers['counts']")
    if "counts" not in adata.layers:
        report.errors.append('Required layer "counts" is missing')
    else:
        counts = adata.layers["counts"]
        if counts.shape != adata.shape:
            report.errors.append('layers["counts"] does not match the AnnData shape')
        _validate_counts(counts, report)

    if not adata.obs_names.is_unique:
        report.errors.append("obs_names must be unique")
    if not adata.var_names.is_unique:
        report.errors.append("var_names must be unique")
    if "split" in adata.obs:
        report.errors.append("obs['split'] is downstream metadata and must not be created during ingestion")

    _validate_obs(adata, report)
    _validate_single_cell_protocol(adata, report)
    report.summary["control_cells"] = int(adata.obs.get("control", pd.Series(dtype=bool)).eq(True).sum())
    if raise_on_error:
        report.raise_for_errors()
    return report
