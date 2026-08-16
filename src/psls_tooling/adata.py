"""AnnData inspection and config-driven validation helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .chemistry import normalize_inchikey


@dataclass(frozen=True)
class MatrixContract:
    """Storage and value rules for the primary AnnData matrix."""

    x_must_be_none: bool
    counts_layer: str
    require_sparse: bool
    require_numeric: bool
    require_finite: bool
    require_nonnegative: bool
    require_integral: bool
    require_unique_obs_names: bool
    require_unique_var_names: bool


@dataclass(frozen=True)
class ObsFieldRule:
    """Validation rules for one required observation column."""

    dtype: str
    nullable: bool = False
    nonempty: bool = False
    finite: bool = False
    minimum: float | None = None


@dataclass(frozen=True)
class IndicatorRule:
    """Require a boolean column to equal a value comparison."""

    indicator_column: str
    value_column: str
    equals: Any
    require_true: bool = False


@dataclass(frozen=True)
class ConditionalFormatRule:
    """Validate a field format for rows matching a condition."""

    column: str
    format: str
    when_column: str
    when_equals: Any
    required: bool = True


@dataclass(frozen=True)
class GroupSizeRule:
    """Require every observed group to contain a minimum number of rows."""

    columns: tuple[str, ...]
    minimum: int


@dataclass(frozen=True)
class MetadataFieldRule:
    """Validate one nested field under ``adata.uns``."""

    path: tuple[str, ...]
    dtype: str
    nonempty: bool = False
    allowed_values: tuple[Any, ...] = ()


@dataclass(frozen=True)
class IngestContract:
    """Parsed benchmark contract consumed by AnnData validation."""

    schema_version: int
    matrix: MatrixContract
    obs_fields: Mapping[str, ObsFieldRule]
    forbidden_obs_columns: tuple[str, ...]
    indicator_rules: tuple[IndicatorRule, ...]
    conditional_format_rules: tuple[ConditionalFormatRule, ...]
    group_size_rules: tuple[GroupSizeRule, ...]
    metadata_fields: tuple[MetadataFieldRule, ...]
    max_obs_exclusive: int | None = None


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


def _mapping(value: Any, *, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{location} must be a mapping")
    return value


def _required(mapping: Mapping[str, Any], key: str, *, location: str) -> Any:
    if key not in mapping:
        raise ValueError(f"{location} is missing required key {key!r}")
    return mapping[key]


def load_ingest_contract(path: str | Path) -> IngestContract:
    """Load a benchmark-specific AnnData contract from YAML."""
    contract_path = Path(path)
    data = _mapping(yaml.safe_load(contract_path.read_text()), location=str(contract_path))
    version = _required(data, "schema_version", location=str(contract_path))
    if version != 1:
        raise ValueError(f"Unsupported ingest contract schema_version: {version!r}")

    matrix_data = _mapping(_required(data, "matrix", location=str(contract_path)), location="matrix")
    matrix = MatrixContract(
        x_must_be_none=bool(_required(matrix_data, "x_must_be_none", location="matrix")),
        counts_layer=str(_required(matrix_data, "counts_layer", location="matrix")),
        require_sparse=bool(_required(matrix_data, "require_sparse", location="matrix")),
        require_numeric=bool(_required(matrix_data, "require_numeric", location="matrix")),
        require_finite=bool(_required(matrix_data, "require_finite", location="matrix")),
        require_nonnegative=bool(_required(matrix_data, "require_nonnegative", location="matrix")),
        require_integral=bool(_required(matrix_data, "require_integral", location="matrix")),
        require_unique_obs_names=bool(
            _required(matrix_data, "require_unique_obs_names", location="matrix")
        ),
        require_unique_var_names=bool(
            _required(matrix_data, "require_unique_var_names", location="matrix")
        ),
    )

    obs_data = _mapping(_required(data, "obs", location=str(contract_path)), location="obs")
    field_data = _mapping(_required(obs_data, "required_fields", location="obs"), location="obs.required_fields")
    obs_fields: dict[str, ObsFieldRule] = {}
    valid_dtypes = {"boolean", "numeric", "string"}
    for name, raw_rule in field_data.items():
        rule = _mapping(raw_rule, location=f"obs.required_fields.{name}")
        dtype = str(_required(rule, "dtype", location=f"obs.required_fields.{name}"))
        if dtype not in valid_dtypes:
            raise ValueError(f"Unsupported obs dtype for {name!r}: {dtype!r}")
        obs_fields[str(name)] = ObsFieldRule(
            dtype=dtype,
            nullable=bool(rule.get("nullable", False)),
            nonempty=bool(rule.get("nonempty", False)),
            finite=bool(rule.get("finite", False)),
            minimum=None if "minimum" not in rule else float(rule["minimum"]),
        )

    relations = _mapping(obs_data.get("relations", {}), location="obs.relations")
    indicators = tuple(
        IndicatorRule(
            indicator_column=str(_required(item, "indicator_column", location="indicator rule")),
            value_column=str(_required(item, "value_column", location="indicator rule")),
            equals=_required(item, "equals", location="indicator rule"),
            require_true=bool(item.get("require_true", False)),
        )
        for raw_item in relations.get("indicators", [])
        for item in [_mapping(raw_item, location="indicator rule")]
    )
    conditional_formats = tuple(
        ConditionalFormatRule(
            column=str(_required(item, "column", location="conditional format rule")),
            format=str(_required(item, "format", location="conditional format rule")),
            when_column=str(
                _required(
                    _mapping(_required(item, "when", location="conditional format rule"), location="when"),
                    "column",
                    location="when",
                )
            ),
            when_equals=_required(
                _mapping(_required(item, "when", location="conditional format rule"), location="when"),
                "equals",
                location="when",
            ),
            required=bool(item.get("required", True)),
        )
        for raw_item in relations.get("conditional_formats", [])
        for item in [_mapping(raw_item, location="conditional format rule")]
    )
    group_sizes = tuple(
        GroupSizeRule(
            columns=tuple(str(column) for column in _required(item, "columns", location="group rule")),
            minimum=int(_required(item, "minimum", location="group rule")),
        )
        for raw_item in obs_data.get("group_size_rules", [])
        for item in [_mapping(raw_item, location="group rule")]
    )

    uns_data = _mapping(_required(data, "uns", location=str(contract_path)), location="uns")
    metadata_fields = tuple(
        MetadataFieldRule(
            path=tuple(str(part) for part in _required(item, "path", location="uns field rule")),
            dtype=str(_required(item, "dtype", location="uns field rule")),
            nonempty=bool(item.get("nonempty", False)),
            allowed_values=tuple(item.get("allowed_values", [])),
        )
        for raw_item in _required(uns_data, "required_fields", location="uns")
        for item in [_mapping(raw_item, location="uns field rule")]
    )
    limits = _mapping(data.get("limits", {}), location="limits")
    max_obs = limits.get("max_obs_exclusive")
    if max_obs is not None and int(max_obs) <= 0:
        raise ValueError("limits.max_obs_exclusive must be positive")

    return IngestContract(
        schema_version=version,
        matrix=matrix,
        obs_fields=obs_fields,
        forbidden_obs_columns=tuple(str(value) for value in obs_data.get("forbidden_columns", [])),
        indicator_rules=indicators,
        conditional_format_rules=conditional_formats,
        group_size_rules=group_sizes,
        metadata_fields=metadata_fields,
        max_obs_exclusive=None if max_obs is None else int(max_obs),
    )


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


def _backed_layers_inventory(adata: Any) -> dict[str, dict[str, Any]]:
    layers: dict[str, dict[str, Any]] = {}
    store = adata.file["layers"]
    for name in store:
        element = store[name]
        encoding = str(element.attrs.get("encoding-type", "dataset"))
        if encoding in {"csr_matrix", "csc_matrix"}:
            shape = element.attrs["shape"]
            dtype = element["data"].dtype
            is_sparse = True
        else:
            shape = element.shape
            dtype = element.dtype
            is_sparse = False
        layers[str(name)] = {
            "present": True,
            "type": encoding,
            "shape": [int(value) for value in shape],
            "dtype": str(dtype),
            "sparse": is_sparse,
        }
    return layers


def inspect_anndata(adata: Any, *, sample_size: int = 5) -> dict[str, Any]:
    """Return a JSON-serializable inventory of an AnnData object."""
    try:
        x = adata.X
    except KeyError:
        x = None
    try:
        raw_x = None if adata.raw is None else adata.raw.X
    except KeyError:
        raw_x = None
    layers = (
        _backed_layers_inventory(adata)
        if adata.isbacked
        else {
            name: _matrix_inventory(matrix)
            for name, matrix in adata.layers.items()
            if name is not None
        }
    )
    return {
        "shape": [int(adata.n_obs), int(adata.n_vars)],
        "X": _matrix_inventory(x),
        "raw_X": _matrix_inventory(raw_x),
        "layers": layers,
        "obs": inspect_dataframe(adata.obs, sample_size=sample_size),
        "var": inspect_dataframe(adata.var, sample_size=sample_size),
        "obs_names_unique": bool(adata.obs_names.is_unique),
        "var_names_unique": bool(adata.var_names.is_unique),
        "obsm_keys": list(adata.obsm.keys()),
        "obsp_keys": list(adata.obsp.keys()),
        "uns_keys": list(adata.uns.keys()),
    }


def get_counts(adata: Any, *, layer: str = "counts") -> Any:
    """Return a named counts matrix or raise a precise schema error."""
    if layer not in adata.layers:
        raise KeyError(f"Required AnnData layer {layer!r} is missing")
    return adata.layers[layer]


def _iter_nonzero_chunks(matrix: Any, chunk_size: int = 1_000_000):
    data = matrix.data if sparse.issparse(matrix) else np.asarray(matrix).ravel()
    for start in range(0, data.size, chunk_size):
        yield np.asarray(data[start : start + chunk_size])


def _validate_counts(matrix: Any, contract: MatrixContract, report: ValidationReport) -> None:
    label = f'layers["{contract.counts_layer}"]'
    if contract.require_sparse and not sparse.issparse(matrix):
        report.errors.append(f"{label} must be a sparse matrix")
    if contract.require_numeric and not np.issubdtype(matrix.dtype, np.number):
        report.errors.append(f"{label} must have a numeric dtype")
        return

    for values in _iter_nonzero_chunks(matrix):
        if contract.require_finite and not np.isfinite(values).all():
            report.errors.append(f"{label} contains non-finite values")
            break
        if contract.require_nonnegative and (values < 0).any():
            report.errors.append(f"{label} contains negative values")
            break
        if contract.require_integral and not np.equal(values, np.rint(values)).all():
            report.errors.append(f"{label} contains non-integer values")
            break


def _validate_obs_field(name: str, series: pd.Series, rule: ObsFieldRule, report: ValidationReport) -> None:
    missing = series.isna()
    if not rule.nullable and missing.any():
        report.errors.append(f"obs[{name!r}] must not contain missing values")

    if rule.dtype == "boolean":
        valid_dtype = pd.api.types.is_bool_dtype(series.dtype)
    elif rule.dtype == "numeric":
        valid_dtype = pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(
            series.dtype
        )
    else:
        valid_dtype = all(isinstance(value, str) for value in series[~missing].tolist())
    if not valid_dtype:
        report.errors.append(f"obs[{name!r}] must have {rule.dtype} dtype")
        return

    present = series[~missing]
    if rule.nonempty and present.astype(str).str.strip().eq("").any():
        report.errors.append(f"obs[{name!r}] must not contain empty values")
    if rule.dtype == "numeric" and (rule.finite or rule.minimum is not None):
        values = present.to_numpy(dtype=float)
        if rule.finite and not np.isfinite(values).all():
            report.errors.append(f"obs[{name!r}] must contain finite values")
        if rule.minimum is not None and (values < rule.minimum).any():
            report.errors.append(f"obs[{name!r}] must contain values >= {rule.minimum:g}")


def _validate_obs(adata: Any, contract: IngestContract, report: ValidationReport) -> None:
    missing = [column for column in contract.obs_fields if column not in adata.obs]
    if missing:
        report.errors.append(f"Missing required obs columns: {missing}")
    for name, rule in contract.obs_fields.items():
        if name in adata.obs:
            _validate_obs_field(name, adata.obs[name], rule, report)

    for column in contract.forbidden_obs_columns:
        if column in adata.obs:
            report.errors.append(f"obs[{column!r}] is forbidden by the ingest contract")

    for rule in contract.indicator_rules:
        if rule.indicator_column not in adata.obs or rule.value_column not in adata.obs:
            continue
        if not pd.api.types.is_bool_dtype(adata.obs[rule.indicator_column].dtype):
            continue
        indicator = adata.obs[rule.indicator_column].astype("boolean")
        expected = adata.obs[rule.value_column].eq(rule.equals).astype("boolean")
        if not bool(indicator.eq(expected).fillna(False).all()):
            report.errors.append(
                f"obs[{rule.indicator_column!r}] must exactly match "
                f"obs[{rule.value_column!r}] == {rule.equals!r}"
            )
        if rule.require_true and not bool(indicator.fillna(False).any()):
            report.errors.append(f"At least one true value is required in obs[{rule.indicator_column!r}]")

    formatters = {"inchikey": normalize_inchikey}
    for rule in contract.conditional_format_rules:
        if rule.column not in adata.obs or rule.when_column not in adata.obs:
            continue
        if rule.format not in formatters:
            report.errors.append(f"Unsupported configured format: {rule.format!r}")
            continue
        selected = adata.obs[rule.when_column].eq(rule.when_equals).fillna(False)
        normalized = adata.obs.loc[selected, rule.column].map(formatters[rule.format])
        if rule.required and normalized.isna().any():
            report.errors.append(
                f"obs[{rule.column!r}] must contain valid {rule.format} values where "
                f"obs[{rule.when_column!r}] == {rule.when_equals!r}"
            )

    for rule in contract.group_size_rules:
        missing_group_columns = [column for column in rule.columns if column not in adata.obs]
        if missing_group_columns:
            continue
        counts = adata.obs.groupby(list(rule.columns), observed=True, dropna=False).size()
        too_small = counts[counts < rule.minimum]
        if len(too_small):
            report.errors.append(
                f"Observed groups over {list(rule.columns)} must contain at least {rule.minimum} rows; "
                f"found {len(too_small)} undersized groups"
            )


def _nested_value(root: Mapping[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    value: Any = root
    for part in path:
        if not isinstance(value, Mapping) or part not in value:
            return False, None
        value = value[part]
    return True, value


def _validate_uns(adata: Any, contract: IngestContract, report: ValidationReport) -> None:
    for rule in contract.metadata_fields:
        exists, value = _nested_value(adata.uns, rule.path)
        rendered_path = "uns" + "".join(f'["{part}"]' for part in rule.path)
        if not exists:
            report.errors.append(f"{rendered_path} is required")
            continue
        valid_type = (rule.dtype == "mapping" and isinstance(value, Mapping)) or (
            rule.dtype == "string" and isinstance(value, str)
        )
        if not valid_type:
            report.errors.append(f"{rendered_path} must be a {rule.dtype}")
            continue
        if rule.nonempty and isinstance(value, str) and not value.strip():
            report.errors.append(f"{rendered_path} must be non-empty")
        if rule.allowed_values and value not in rule.allowed_values:
            report.errors.append(f"{rendered_path} must be one of {sorted(rule.allowed_values)}")


def validate_ingested_adata(
    adata: Any,
    contract: IngestContract,
    *,
    raise_on_error: bool = False,
) -> ValidationReport:
    """Validate an AnnData object against an explicit benchmark contract."""
    report = ValidationReport(summary={"n_obs": int(adata.n_obs), "n_vars": int(adata.n_vars)})
    matrix_contract = contract.matrix
    if matrix_contract.x_must_be_none and adata.X is not None:
        report.errors.append("X must be None")
    if matrix_contract.counts_layer not in adata.layers:
        report.errors.append(f"Required layer {matrix_contract.counts_layer!r} is missing")
    else:
        counts = adata.layers[matrix_contract.counts_layer]
        if counts.shape != adata.shape:
            report.errors.append(
                f'layers["{matrix_contract.counts_layer}"] does not match the AnnData shape'
            )
        _validate_counts(counts, matrix_contract, report)

    if matrix_contract.require_unique_obs_names and not adata.obs_names.is_unique:
        report.errors.append("obs_names must be unique")
    if matrix_contract.require_unique_var_names and not adata.var_names.is_unique:
        report.errors.append("var_names must be unique")
    if contract.max_obs_exclusive is not None and adata.n_obs >= contract.max_obs_exclusive:
        report.errors.append(f"n_obs must be less than {contract.max_obs_exclusive:,}")

    _validate_obs(adata, contract, report)
    _validate_uns(adata, contract, report)
    if raise_on_error:
        report.raise_for_errors()
    return report
