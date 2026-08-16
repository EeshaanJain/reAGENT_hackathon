"""Helpers for applying downstream train/test manifests to AnnData objects."""

from __future__ import annotations

import anndata as ad
import numpy as np
import pandas as pd

TRAIN_LABEL = "train"
TEST_LABEL = "test"
VALID_SPLIT_LABELS = frozenset({TRAIN_LABEL, TEST_LABEL})


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
