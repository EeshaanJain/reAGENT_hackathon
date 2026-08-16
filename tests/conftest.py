from __future__ import annotations

import anndata as ad
import pandas as pd
import pytest
from scipy import sparse


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
