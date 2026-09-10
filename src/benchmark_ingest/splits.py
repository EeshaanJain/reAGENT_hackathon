"""Helpers for applying downstream train/test manifests to AnnData objects."""

from __future__ import annotations

import tempfile
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd

TRAIN_LABEL = "train"
TEST_LABEL = "test"
VALID_SPLIT_LABELS = frozenset({TRAIN_LABEL, TEST_LABEL})


def create_cell_type_manifests(obs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Create one deterministic leave-one-cell-type-out manifest per cell type."""
    if "cell_type" not in obs:
        raise ValueError("obs must contain a 'cell_type' column")
    if not obs.index.is_unique:
        raise ValueError("obs index must contain unique cell IDs")
    if obs.index.hasnans:
        raise ValueError("obs index contains missing cell IDs")

    cell_ids = pd.Index(obs.index.astype(str), name="cell_id")
    if not cell_ids.is_unique:
        raise ValueError("obs cell IDs are not unique after conversion to strings")
    source_cell_types = obs["cell_type"]
    if source_cell_types.isna().any():
        raise ValueError("obs['cell_type'] contains missing values")
    cell_types = source_cell_types.astype(str)
    if cell_types.str.strip().eq("").any():
        raise ValueError("obs['cell_type'] contains empty values")

    unique_cell_types = sorted(cell_types.unique())
    if len(unique_cell_types) < 2:
        raise ValueError("At least two cell types are required to create train/test splits")
    cell_type_values = cell_types.to_numpy()
    return {
        held_out: pd.DataFrame(
            {
                "cell_id": cell_ids.to_numpy(),
                "cell_type": cell_type_values,
                "split": np.where(cell_type_values == held_out, TEST_LABEL, TRAIN_LABEL),
            }
        )
        for held_out in unique_cell_types
    }


def write_cell_type_manifests(
    input_path: Path,
    output_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """Read observation metadata only and write every cell-type manifest."""
    input_path = input_path.resolve()
    output_dir = output_dir.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input H5AD does not exist: {input_path}")

    with h5py.File(input_path, "r") as store:
        if "obs" not in store:
            raise ValueError(f"Input H5AD does not contain observation metadata: {input_path}")
        obs = ad.io.read_elem(store["obs"])
    manifests = create_cell_type_manifests(obs)
    outputs = {cell_type: output_dir / f"test_{cell_type}.csv" for cell_type in manifests}
    existing = [path for path in outputs.values() if path.exists()]
    if existing and not force:
        rendered = ", ".join(map(str, existing))
        raise FileExistsError(f"Split output already exists: {rendered}; pass --force to replace it")

    output_dir.mkdir(parents=True, exist_ok=True)
    for cell_type, manifest in manifests.items():
        output = outputs[cell_type]
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=output_dir,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                manifest.to_csv(temporary, index=False)
            temporary_path.chmod(0o644)
            temporary_path.replace(output)
        except BaseException:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
    return outputs


def _display_values(values: pd.Index, *, limit: int = 5) -> list[str]:
    return values.astype(str).tolist()[:limit]


def _independent_subset(adata: ad.AnnData, mask: np.ndarray) -> ad.AnnData:
    subset = adata[mask]
    if adata.isbacked:
        return subset.to_memory()
    return subset.copy()


def _counts_only_memory_facade(adata: ad.AnnData) -> ad.AnnData:
    """Work around AnnData backed reads that assume an on-disk X exists."""

    def mapping_without_x(mapping):
        return {key: mapping[key] for key in mapping if key is not None}

    return ad.AnnData(
        X=None,
        obs=adata.obs,
        var=adata.var,
        uns=adata.uns,
        obsm=mapping_without_x(adata.obsm),
        varm=mapping_without_x(adata.varm),
        layers=mapping_without_x(adata.layers),
        raw=adata.raw,
        shape=adata.shape,
        obsp=mapping_without_x(adata.obsp),
        varp=mapping_without_x(adata.varp),
    )


def split_adata_by_manifest(
    adata: ad.AnnData,
    split_df: pd.DataFrame,
    *,
    cell_id_col: str = "cell_id",
    split_col: str = "split",
) -> tuple[ad.AnnData, ad.AnnData]:
    """Return independent train and test subsets from an exact cell manifest.

    The manifest is aligned to ``adata.obs_names`` by cell identifier, so its
    row order does not affect the returned subsets. Every observation must occur
    exactly once and split labels must be exactly ``"train"`` or ``"test"``.
    If the manifest contains ``cell_type``, it is checked against AnnData after
    identifier alignment.
    """
    if not isinstance(split_df, pd.DataFrame):
        raise TypeError("split_df must be a pandas DataFrame")

    missing_columns = [column for column in (cell_id_col, split_col) if column not in split_df]
    if missing_columns:
        raise ValueError(f"Split manifest is missing required columns: {missing_columns}")
    if not adata.obs_names.is_unique:
        raise ValueError("adata.obs_names must be unique")

    raw_cell_ids = split_df[cell_id_col]
    if raw_cell_ids.isna().any():
        raise ValueError(f"Split manifest column {cell_id_col!r} contains missing values")
    cell_ids = pd.Index(raw_cell_ids.astype(str), name=cell_id_col)
    duplicated = cell_ids[cell_ids.duplicated()].unique()
    if len(duplicated):
        raise ValueError(
            "Split manifest contains duplicate cell IDs: "
            f"{_display_values(duplicated)}"
        )

    obs_ids = pd.Index(adata.obs_names.astype(str), name=cell_id_col)
    missing_ids = obs_ids.difference(cell_ids, sort=False)
    unknown_ids = cell_ids.difference(obs_ids, sort=False)
    if len(missing_ids) or len(unknown_ids):
        raise ValueError(
            "Split manifest must cover adata.obs_names exactly; "
            f"missing={_display_values(missing_ids)}, "
            f"unknown={_display_values(unknown_ids)}"
        )

    labels = split_df[split_col]
    if labels.isna().any():
        raise ValueError(f"Split manifest column {split_col!r} contains missing values")
    label_values = labels.astype(str)
    invalid_labels = sorted(set(label_values) - VALID_SPLIT_LABELS)
    if invalid_labels:
        raise ValueError(
            f"Split manifest labels must be {sorted(VALID_SPLIT_LABELS)}; "
            f"invalid={invalid_labels}"
        )
    missing_labels = sorted(VALID_SPLIT_LABELS - set(label_values))
    if missing_labels:
        raise ValueError(f"Split manifest must contain non-empty train and test partitions: {missing_labels}")

    manifest = split_df.copy()
    manifest.index = cell_ids
    aligned = manifest.reindex(obs_ids)

    if "cell_type" in aligned:
        if "cell_type" not in adata.obs:
            raise ValueError("Split manifest contains cell_type but adata.obs does not")
        if aligned["cell_type"].isna().any():
            raise ValueError("Split manifest column 'cell_type' contains missing values")
        manifest_cell_types = aligned["cell_type"].astype(str).to_numpy()
        adata_cell_types = adata.obs["cell_type"].astype(str).to_numpy()
        mismatch = manifest_cell_types != adata_cell_types
        if mismatch.any():
            mismatched_ids = obs_ids[mismatch]
            raise ValueError(
                "Split manifest cell_type values do not match adata.obs: "
                f"{_display_values(mismatched_ids)}"
            )

    aligned_labels = aligned[split_col].astype(str).to_numpy()
    train_mask = aligned_labels == TRAIN_LABEL
    test_mask = aligned_labels == TEST_LABEL

    if adata.isbacked:
        try:
            _ = adata.X
        except KeyError:
            # AnnData currently assumes backed objects always have /X. The
            # repository contract deliberately stores counts only in a layer,
            # so construct a non-backed facade before copying the two slices.
            memory_adata = _counts_only_memory_facade(adata)
            return memory_adata[train_mask].copy(), memory_adata[test_mask].copy()
    return _independent_subset(adata, train_mask), _independent_subset(adata, test_mask)
