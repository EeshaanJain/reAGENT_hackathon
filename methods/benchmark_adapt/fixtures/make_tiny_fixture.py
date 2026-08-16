"""Build the frozen tiny fixture that Stage 4 (adapter synthesis) and the Gauntlet iterate against.

Implements todo.html item A2: a small DE-signature slice with a *frozen* gene order, recorded as a
SHA256 that the Gauntlet can assert against (G2: exact id_map row order + gene space).

Schema verified directly against the vendored OP3 submodule (../../task_perturbation_prediction),
not just the plan docs:
  - src/api/file_de_train.yaml   -- required obs: cell_type, sm_name, sm_lincs_id, SMILES, split,
                                     control. Required layers: logFC, P.Value, adj.P.Value, is_de,
                                     is_de_adj, sign_log10_pval, clipped_sign_log10_pval (AveExpr/
                                     t/B optional -- omitted here). Required uns: dataset_id,
                                     dataset_name, dataset_summary, dataset_description.
  - src/api/file_id_map.yaml     -- id (integer), cell_type, sm_name.
  - src/api/file_prediction.yaml -- output layer must be literally named "prediction" (verified
                                     against src/methods/scape/script.py's real
                                     `layers={"prediction": ...}`), uns: dataset_id, method_id.
  - src/api/wf_method.yaml       -- `--layer` argument (default clipped_sign_log10_pval) selects
                                     *which de_train layer* a method reads. This is a different
                                     thing from the output layer name, which is always "prediction"
                                     regardless of --layer.

Known gap: file_de_train.yaml also requires `uns.single_cell_obs`, a per-cell metadata dataframe.
Fabricating that would mean simulating real single-cell data, which defeats the point of a
DE-signature-only toy fixture -- deliberately omitted, not forgotten.

This fixture lives in de_train/de_test/id_map space -- the same shape OP3 methods actually receive
-- not raw single-cell counts. That's a deliberate choice: Sei's lane targets the DE-signature-
compatible methods (the six Kaggle-derived methods, Chem-PerturBridge-style representations); the
single-cell-input class (chemCPA/CPA/biolord) is the known API gap this workstream files as a
finding rather than works around here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

RNG_SEED = 20260815
N_GENES = 500
CELL_TYPES = ["celltype_A", "celltype_B"]
TRAIN_COMPOUNDS = ["compound_1", "compound_2", "compound_3", "compound_4", "compound_5", "compound_6"]
TEST_COMPOUNDS = ["compound_7", "compound_8"]

INPUT_LAYER_DEFAULT = "clipped_sign_log10_pval"  # what `--layer` defaults to (wf_method.yaml)
INPUT_LAYER_BOUNDS = (-4.0, 4.0)
DE_TRAIN_LAYERS = ["logFC", "P.Value", "adj.P.Value", "is_de", "is_de_adj", "sign_log10_pval", "clipped_sign_log10_pval"]
OUTPUT_LAYER = "prediction"  # the ONLY layer name file_prediction.yaml permits, always -- not configurable

OUT_DIR = Path(__file__).parent / "data"


def _gene_ids(n: int) -> list[str]:
    return [f"g{str(i).zfill(4)}" for i in range(n)]


def _simulate_sign_log10_pval(rng: np.random.Generator, rows: list[tuple[str, str]], gene_ids: list[str]) -> np.ndarray:
    """A crude but deterministic DE-signature simulator: each (cell_type, compound) row gets a
    sparse set of "responsive" genes with a signed, bounded score; everything else is near zero.
    Good enough to exercise the Gauntlet's shape/range/sensitivity checks -- not a biological claim.
    Produces the (unclipped) sign_log10_pval-shaped matrix; clipped_sign_log10_pval is derived from it.
    """
    n_genes = len(gene_ids)
    mat = rng.normal(loc=0.0, scale=0.15, size=(len(rows), n_genes))
    for i, (cell_type, compound) in enumerate(rows):
        # a compound-specific + cell-type-specific set of responsive genes, so shuffling sm_name
        # (G3, perturbation sensitivity) actually changes which genes move.
        compound_seed = int(hashlib.sha256(f"{compound}|{cell_type}".encode()).hexdigest(), 16) % (2**32)
        local_rng = np.random.default_rng(compound_seed)
        n_responsive = local_rng.integers(15, 40)
        idx = local_rng.choice(n_genes, size=n_responsive, replace=False)
        signs = local_rng.choice([-1.0, 1.0], size=n_responsive)
        mags = local_rng.uniform(1.0, 5.0, size=n_responsive)  # allow some to exceed the +/-4 clip bound
        mat[i, idx] = signs * mags
    return mat


def _compound_metadata(compounds: list[str]) -> dict[str, dict]:
    """Deterministic, clearly-synthetic per-compound sm_lincs_id / SMILES -- not real registered
    compounds, just enough structure (one value per compound, consistent across cell types) to
    populate the required de_train columns.
    """
    meta = {}
    for i, compound in enumerate(sorted(compounds)):
        meta[compound] = {
            "sm_lincs_id": f"LSM-{20000 + i}",
            "SMILES": f"C{'C' * (i % 5 + 1)}O",  # synthetic placeholder, not a real structure
        }
    return meta


def _build_split(
    rng: np.random.Generator, rows: list[tuple[str, str]], gene_ids: list[str], split_name: str, compound_meta: dict[str, dict]
) -> ad.AnnData:
    n_genes = len(gene_ids)
    sign_log10_pval = _simulate_sign_log10_pval(rng, rows, gene_ids)
    clipped = np.clip(sign_log10_pval, *INPUT_LAYER_BOUNDS)
    logfc = sign_log10_pval / 2.0  # loosely correlated stand-in, not a real relationship

    n = len(rows)
    obs = pd.DataFrame(
        {
            "cell_type": [r[0] for r in rows],
            "sm_name": [r[1] for r in rows],
            "sm_lincs_id": [compound_meta[r[1]]["sm_lincs_id"] for r in rows],
            "SMILES": [compound_meta[r[1]]["SMILES"] for r in rows],
            "split": [split_name] * n,
            "control": [False] * n,
        }
    )

    adata = ad.AnnData(X=clipped, obs=obs, var=pd.DataFrame(index=gene_ids))
    adata.layers["logFC"] = logfc
    adata.layers["P.Value"] = rng.uniform(0.0, 0.05, size=(n, n_genes))
    adata.layers["adj.P.Value"] = rng.uniform(0.0, 0.05, size=(n, n_genes))
    adata.layers["is_de"] = np.abs(sign_log10_pval) > 1.0
    adata.layers["is_de_adj"] = np.abs(sign_log10_pval) > 1.3
    adata.layers["sign_log10_pval"] = sign_log10_pval
    adata.layers["clipped_sign_log10_pval"] = clipped
    adata.uns["dataset_id"] = "benchmark_adapt_tiny_fixture"
    adata.uns["dataset_name"] = "benchmark_adapt tiny synthetic fixture"
    adata.uns["dataset_summary"] = "Synthetic DE-signature slice for exercising the Stage 4/5 harness -- not real biological data."
    adata.uns["dataset_description"] = (
        "Deterministically generated by fixtures/make_tiny_fixture.py. "
        "Does not include uns.single_cell_obs (file_de_train.yaml also requires this for full "
        "schema conformance; omitted here since fabricating it would mean simulating real "
        "single-cell data, defeating the point of a lightweight DE-only fixture)."
    )
    return adata


def build(out_dir: Path = OUT_DIR, seed: int = RNG_SEED) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    gene_ids = _gene_ids(N_GENES)
    compound_meta = _compound_metadata(TRAIN_COMPOUNDS + TEST_COMPOUNDS)

    train_rows = [(ct, cp) for ct in CELL_TYPES for cp in TRAIN_COMPOUNDS]
    test_rows = [(ct, cp) for ct in CELL_TYPES for cp in TEST_COMPOUNDS]

    de_train = _build_split(rng, train_rows, gene_ids, "train", compound_meta)
    de_test = _build_split(rng, test_rows, gene_ids, "private_test", compound_meta)

    id_map = pd.DataFrame(
        {
            "id": list(range(len(test_rows))),  # integer, per file_id_map.yaml
            "cell_type": [r[0] for r in test_rows],
            "sm_name": [r[1] for r in test_rows],
        }
    )

    de_train_path = out_dir / "de_train.h5ad"
    de_test_path = out_dir / "de_test.h5ad"
    id_map_path = out_dir / "id_map.csv"

    de_train.write_h5ad(de_train_path)
    de_test.write_h5ad(de_test_path)
    id_map.to_csv(id_map_path, index=False)

    gene_order_sha256 = hashlib.sha256("\n".join(gene_ids).encode()).hexdigest()

    manifest = {
        "seed": seed,
        "n_genes": N_GENES,
        "cell_types": CELL_TYPES,
        "train_compounds": TRAIN_COMPOUNDS,
        "test_compounds": TEST_COMPOUNDS,
        "de_train_layers": DE_TRAIN_LAYERS,
        "input_layer_default": INPUT_LAYER_DEFAULT,
        "input_layer_bounds": list(INPUT_LAYER_BOUNDS),
        "output_layer": OUTPUT_LAYER,
        "gene_order_sha256": gene_order_sha256,
        "n_train_rows": len(train_rows),
        "n_test_rows": len(test_rows),
        "files": {
            "de_train": str(de_train_path.relative_to(out_dir.parent)),
            "de_test": str(de_test_path.relative_to(out_dir.parent)),
            "id_map": str(id_map_path.relative_to(out_dir.parent)),
        },
    }
    (out_dir / "fixture_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    manifest = build()
    print(f"Wrote fixture to {OUT_DIR}/")
    print(f"  de_train: {manifest['n_train_rows']} rows x {manifest['n_genes']} genes, layers={manifest['de_train_layers']}")
    print(f"  de_test:  {manifest['n_test_rows']} rows x {manifest['n_genes']} genes")
    print(f"  input layer (via --layer, default): {manifest['input_layer_default']}")
    print(f"  required output layer (always):     {manifest['output_layer']}")
    print(f"  gene_order_sha256: {manifest['gene_order_sha256']}")
