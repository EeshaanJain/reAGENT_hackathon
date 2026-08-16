from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import anndata as ad
import pandas as pd
import pytest
from scipy import sparse

from psls_tooling import IngestContract, load_ingest_contract


@pytest.fixture
def ingest_contract() -> IngestContract:
    path = Path("benchmarks/perturbation_prediction/ingest_contract.yaml")
    contract = load_ingest_contract(path)
    group_rules = tuple(replace(rule, minimum=1) for rule in contract.group_size_rules)
    return replace(contract, group_size_rules=group_rules, max_obs_exclusive=100)


@pytest.fixture
def valid_adata() -> ad.AnnData:
    counts = sparse.csr_matrix([[1, 0, 2], [0, 3, 0], [2, 2, 0]], dtype=int)
    obs = pd.DataFrame(
        {
            "dose_uM": [0.0, 1.0, 1.0],
            "timepoint_hr": [24.0, 24.0, 24.0],
            "cell_type": ["A549", "A549", "K562"],
            "sm_name": ["control", "ethanol", "ethanol"],
            "sm_name_original": ["Vehicle", "Ethanol", "Ethanol"],
            "inchikey": [None, "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"],
            "batch": ["plate_1", "plate_1", "plate_2"],
            "control": [True, False, False],
        },
        index=["cell_1", "cell_2", "cell_3"],
    )
    var = pd.DataFrame(index=["MT-CO1", "GENE1", "GENE2"])
    adata = ad.AnnData(X=None, obs=obs, var=var, shape=counts.shape)
    adata.layers["counts"] = counts
    adata.uns["single_cell_protocol"] = {
        "chemistry": "sci-RNA-seq3",
        "capture_orientation": "3prime",
        "source": "publication methods",
    }
    return adata
