from __future__ import annotations

import pandas as pd
import pytest

from benchmark_ingest import select_condition_subset


def _sampling_obs() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    index: list[str] = []
    for treatment, size, control in [
        ("reference", 35, True),
        ("drug_a", 50, False),
        ("drug_b", 45, False),
        ("too_small", 20, False),
    ]:
        for offset in range(size):
            rows.append({"treatment": treatment, "is_reference": control})
            index.append(f"{treatment}_{offset:03d}")
    return pd.DataFrame(rows, index=index)


def _select(obs: pd.DataFrame):
    return select_condition_subset(
        obs,
        condition_columns=["treatment"],
        minimum_condition_size=30,
        control_column="is_reference",
        max_cells_exclusive=111,
        target_min_cells=100,
        seed=42,
    )


def test_condition_subset_is_deterministic_and_order_independent() -> None:
    obs = _sampling_obs()
    selected, audit = _select(obs)
    shuffled = obs.sample(frac=1, random_state=7)
    shuffled_selected, shuffled_audit = _select(shuffled)

    selected_ids = set(obs.index[selected])
    shuffled_ids = set(shuffled.index[shuffled_selected])
    assert selected_ids == shuffled_ids
    assert set(obs.index[obs["is_reference"]]).issubset(selected_ids)
    assert not any(cell_id.startswith("too_small") for cell_id in selected_ids)
    assert audit == shuffled_audit
    assert audit["treated_condition_cap"] == 37
    assert audit["cells_after"] == 109
    assert audit["conditions_after"] == 3
    assert audit["undersized_conditions_removed"] == 1
    assert audit["undersized_cells_removed"] == 20
    assert audit["minimum_final_condition_size"] == 35
    assert audit["target_met"] is True


def test_condition_subset_keeps_all_when_already_below_limit() -> None:
    obs = _sampling_obs().iloc[:85]

    selected, audit = _select(obs)

    assert selected.all()
    assert audit["treated_condition_cap"] is None
    assert audit["cells_after"] == 85
    assert audit["target_met"] is False


def test_condition_subset_rejects_controls_over_limit() -> None:
    obs = pd.DataFrame(
        {"treatment": "reference", "is_reference": True},
        index=[f"cell_{index}" for index in range(40)],
    )

    with pytest.raises(ValueError, match="controls alone"):
        select_condition_subset(
            obs,
            condition_columns=["treatment"],
            minimum_condition_size=30,
            control_column="is_reference",
            max_cells_exclusive=40,
            target_min_cells=30,
            seed=42,
        )
