from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from benchmark_ingest import standardize_smiles
from benchmarks.perturbation_prediction.datasets.srivatsan_2020_sciplex3.ingest import (
    FALLBACK_SOURCE,
    _patch_fallback_structure_audit,
    stream_counts,
)


@pytest.mark.parametrize("fallback_rows", [0, 2])
def test_fallback_audit_patch_rejects_unexpected_row_count(fallback_rows: int) -> None:
    sources = [FALLBACK_SOURCE] * fallback_rows or ["smiles_rdkit"]
    resolved = pd.DataFrame({"inchikey_source": sources})
    cached_parent = standardize_smiles("CN(C)C.Cl")

    with pytest.raises(RuntimeError, match="expected 1 .* row"):
        _patch_fallback_structure_audit(resolved, cached_parent)


def test_fallback_audit_patch_records_cached_structure() -> None:
    resolved = pd.DataFrame(
        {
            "inchikey_source": [FALLBACK_SOURCE],
            "canonical_smiles": [None],
            "desalted": [False],
            "removed_fragments": [""],
            "parent_candidate_smiles": [None],
            "parent_candidate_inchikey": [None],
        }
    )
    cached_parent = standardize_smiles("CN(C)C.Cl")

    _patch_fallback_structure_audit(resolved, cached_parent)

    assert resolved.loc[0, "canonical_smiles"] == "CN(C)C"
    assert bool(resolved.loc[0, "desalted"])
    assert resolved.loc[0, "removed_fragments"] == "Cl"


def test_stream_counts_reports_true_zero_based_maximum_indices(tmp_path) -> None:
    coordinates = tmp_path / "counts.tsv"
    coordinates.write_text("1\t1\t2\n3\t1\t1\n2\t2\t4\n3\t2\t5\n")

    counts, audit = stream_counts(
        coordinates,
        n_source_genes=3,
        n_source_cells=2,
        source_total_umis=np.array([3, 9], dtype=np.int64),
        gene_map=np.array([0, 1, 2], dtype=np.int32),
        cell_map=np.array([0, 1], dtype=np.int32),
        n_output_cells=2,
        n_output_genes=3,
    )

    assert counts.shape == (2, 3)
    assert audit["raw_gene_index_max"] == 2
    assert audit["raw_cell_index_max"] == 1
