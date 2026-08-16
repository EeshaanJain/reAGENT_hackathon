"""Deterministic, benchmark-configurable dataset subsetting."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd


def _stable_rank(cell_id: str, seed: int) -> bytes:
    return hashlib.sha256(f"{seed}\0{cell_id}".encode()).digest()


def select_condition_subset(
    obs: pd.DataFrame,
    *,
    condition_columns: Sequence[str],
    minimum_condition_size: int,
    control_column: str,
    max_cells_exclusive: int,
    target_min_cells: int,
    seed: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Select a reproducible subset while retaining condition coverage."""
    columns = tuple(condition_columns)
    if not columns:
        raise ValueError("condition_columns must not be empty")
    missing = [column for column in (*columns, control_column) if column not in obs]
    if missing:
        raise ValueError(f"Subset columns are missing: {missing}")
    if minimum_condition_size <= 0:
        raise ValueError("minimum_condition_size must be positive")
    if max_cells_exclusive <= 0:
        raise ValueError("max_cells_exclusive must be positive")
    if not 0 <= target_min_cells < max_cells_exclusive:
        raise ValueError("target_min_cells must be nonnegative and below max_cells_exclusive")
    if not obs.index.is_unique or obs.index.hasnans:
        raise ValueError("obs index must contain unique, non-missing cell identifiers")
    cell_ids = pd.Index(obs.index.astype(str))
    if not cell_ids.is_unique:
        raise ValueError("obs cell identifiers must remain unique after string conversion")
    controls = obs[control_column]
    if not pd.api.types.is_bool_dtype(controls.dtype) or controls.isna().any():
        raise ValueError(f"obs[{control_column!r}] must be non-nullable boolean data")
    controls = controls.astype(bool)

    grouped = obs.groupby(list(columns), observed=True, dropna=False)
    group_sizes = grouped.size().rename("n_cells")
    row_group_sizes = grouped[control_column].transform("size")
    eligible = row_group_sizes.ge(minimum_condition_size).to_numpy()
    eligible_controls = eligible & controls.to_numpy()
    eligible_treated = eligible & ~controls.to_numpy()
    control_count = int(eligible_controls.sum())
    max_selected = max_cells_exclusive - 1
    if control_count > max_selected:
        raise ValueError(
            f"Eligible controls alone ({control_count:,}) exceed the cell limit ({max_selected:,})"
        )

    treated_sizes = (
        obs.loc[eligible_treated]
        .groupby(list(columns), observed=True, dropna=False)
        .size()
    )
    eligible_total = int(eligible.sum())
    cap: int | None = None
    selected = eligible.copy()
    if eligible_total > max_selected:
        if treated_sizes.empty:
            raise ValueError("No treated conditions are available for cap-based subsetting")
        low, high = 0, int(treated_sizes.max())
        while low <= high:
            candidate = (low + high) // 2
            total = control_count + int(treated_sizes.clip(upper=candidate).sum())
            if total <= max_selected:
                cap = candidate
                low = candidate + 1
            else:
                high = candidate - 1
        if cap is None or cap < minimum_condition_size:
            raise ValueError(
                "The cell limit cannot retain every eligible condition at the configured minimum"
            )

        selected = eligible_controls.copy()
        eligible_positions = np.flatnonzero(eligible_treated)
        treated_frame = obs.iloc[eligible_positions]
        for _, positions in treated_frame.groupby(list(columns), observed=True, dropna=False).indices.items():
            absolute_positions = eligible_positions[np.asarray(positions, dtype=int)]
            if len(absolute_positions) <= cap:
                selected[absolute_positions] = True
                continue
            ranked = sorted(
                absolute_positions,
                key=lambda position: (_stable_rank(cell_ids[position], seed), cell_ids[position]),
            )
            selected[np.asarray(ranked[:cap], dtype=int)] = True

    final_counts = obs.loc[selected].groupby(list(columns), observed=True, dropna=False).size()
    if final_counts.empty:
        raise ValueError("No conditions meet the configured minimum size")
    dropped_counts = group_sizes[group_sizes < minimum_condition_size]
    audit = {
        "condition_columns": list(columns),
        "minimum_condition_size": int(minimum_condition_size),
        "max_cells_exclusive": int(max_cells_exclusive),
        "target_min_cells": int(target_min_cells),
        "seed": int(seed),
        "cells_before": int(len(obs)),
        "conditions_before": int(len(group_sizes)),
        "undersized_conditions_removed": int(len(dropped_counts)),
        "undersized_cells_removed": int(dropped_counts.sum()),
        "eligible_cells": eligible_total,
        "eligible_conditions": int((group_sizes >= minimum_condition_size).sum()),
        "control_cells_retained": control_count,
        "treated_condition_cap": cap,
        "cells_after": int(selected.sum()),
        "conditions_after": int(len(final_counts)),
        "minimum_final_condition_size": int(final_counts.min()),
        "target_met": bool(selected.sum() >= target_min_cells),
    }
    return selected, audit
