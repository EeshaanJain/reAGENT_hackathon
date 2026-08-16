from __future__ import annotations

import anndata as ad
import pandas as pd
from rdkit.Chem import SaltRemover
from scipy import sparse

from psls_tooling import (
    LookupResult,
    drop_unresolved_treatments,
    normalize_inchikey,
    resolve_compounds,
    standardize_smiles,
)


def test_normalize_inchikey_is_strict() -> None:
    assert normalize_inchikey(" lfqscwfljhtthz-uhfffaoysa-n ") == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert normalize_inchikey("not-a-key") is None
    assert normalize_inchikey(None) is None


def test_standardize_smiles_removes_small_salt() -> None:
    result = standardize_smiles("CN(C)C.Cl")

    assert result.status == "desalted"
    assert result.desalted
    assert result.removed_fragments == ("Cl",)
    assert result.canonical_smiles == "CN(C)C"
    assert result.inchikey == "GETQZCLCWQTVFV-UHFFFAOYSA-N"


def test_standardize_smiles_preserves_large_recognized_fragment() -> None:
    remover = SaltRemover.SaltRemover(defnData="[Cl-]\nO=C([O-])c1ccccc1")
    result = standardize_smiles(
        "C[NH+](C)C.O=C([O-])c1ccccc1",
        salt_remover=remover,
    )

    assert result.status == "large_fragment_preserved"
    assert not result.desalted
    assert result.removed_fragments == ("O=C([O-])c1ccccc1",)
    assert "." in result.canonical_smiles
    assert result.parent_candidate_smiles == "C[NH+](C)C"


def test_resolve_compounds_uses_structure_before_fallback() -> None:
    compounds = pd.DataFrame(
        {
            "inchikey": [None, None],
            "SMILES": ["CCO", None],
            "name": ["ethanol", "fallback"],
        }
    )

    def fallback(row: pd.Series) -> LookupResult:
        assert row["name"] == "fallback"
        return LookupResult("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", "fixture", "resolved")

    result = resolve_compounds(compounds, fallback_resolver=fallback)

    assert result.loc[0, "inchikey"] == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert result.loc[0, "inchikey_source"] == "smiles_rdkit"
    assert result.loc[1, "inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert result.loc[1, "inchikey_source"] == "fixture"


def test_drop_unresolved_treatments_retains_controls() -> None:
    obs = pd.DataFrame(
        {
            "inchikey": [None, None, "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"],
            "control": [True, False, False],
            "sm_name_original": ["Vehicle", "Unknown drug", "Ethanol"],
        },
        index=["cell_1", "cell_2", "cell_3"],
    )
    adata = ad.AnnData(X=None, obs=obs, var=pd.DataFrame(index=["GENE"]), shape=(3, 1))
    adata.layers["counts"] = sparse.csr_matrix([[1], [2], [3]])

    filtered, report = drop_unresolved_treatments(adata)

    assert filtered.n_obs == 2
    assert filtered.obs["control"].sum() == 1
    assert report["cells_removed"] == 1
    assert report["unresolved_compounds"] == ["Unknown drug"]
