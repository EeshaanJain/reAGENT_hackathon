"""Build a small single-cell fixture (sc_train.h5ad + id_map.csv) for CPA-class methods
(requires_sc_counts=true), by subsetting the real dataset at
data/srivatsan_2020_sciplex3_compressed.h5ad -- genuine single-cell structure (real counts, real
per-cell obs), not fabricated, matched to what CPA's own synthesized adapter (script.py) actually
reads: adata.X for raw counts (the source file only has a `counts` layer -- moved into X here),
obs['cell_type']/obs['sm_name']/obs['control'] (the source file's own real column names already
match what the adapter looks for).

Usage:
    python fixtures/make_sc_fixture.py [--cell-type A549] [--n-compounds 8] [--cells-per-group 60] [--n-genes 800]

Writes fixtures/data_sc/sc_train.h5ad and fixtures/data_sc/id_map.csv.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_H5AD = REPO_ROOT / "data" / "srivatsan_2020_sciplex3_compressed.h5ad"
OUT_DIR = Path(__file__).parent / "data_sc"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cell-type", default="A549")
    ap.add_argument("--n-compounds", type=int, default=8)
    ap.add_argument("--cells-per-group", type=int, default=60, help="cap per (cell_type, sm_name) group, for speed")
    ap.add_argument("--n-genes", type=int, default=800, help="most-variable genes, for speed")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if not SOURCE_H5AD.exists():
        raise FileNotFoundError(f"real dataset not found at {SOURCE_H5AD}")

    rng = np.random.default_rng(args.seed)
    print(f"Reading {SOURCE_H5AD} (backed mode)...")
    full = ad.read_h5ad(SOURCE_H5AD, backed="r")

    ct_mask = full.obs["cell_type"] == args.cell_type
    control_names = full.obs.loc[ct_mask & full.obs["control"], "sm_name"].unique().tolist()
    treated_names = full.obs.loc[ct_mask & ~full.obs["control"], "sm_name"].unique().tolist()
    chosen_compounds = list(rng.choice(treated_names, size=min(args.n_compounds, len(treated_names)), replace=False))
    keep_sm_names = set(control_names) | set(chosen_compounds)
    print(f"cell_type={args.cell_type!r}: {len(control_names)} control label(s), "
          f"{len(chosen_compounds)}/{len(treated_names)} compound(s) selected")

    # Cap cells per (cell_type, sm_name) group for speed -- this is a smoke-test fixture, not a
    # training-quality dataset.
    keep_idx = []
    obs = full.obs
    group_mask = ct_mask & obs["sm_name"].isin(keep_sm_names)
    for sm in keep_sm_names:
        idx = obs.index[group_mask & (obs["sm_name"] == sm)]
        if len(idx) > args.cells_per_group:
            idx = rng.choice(idx, size=args.cells_per_group, replace=False)
        keep_idx.extend(idx)
    keep_idx = sorted(set(keep_idx))
    print(f"selected {len(keep_idx)} cells total")

    # Source file has no .X at all (only layers["counts"]) -- full[keep_idx].to_memory() touches
    # .X internally and crashes (KeyError: 'X' doesn't exist). Slice the backed counts layer and
    # obs/var (already eagerly-loaded pandas frames even in backed mode) directly instead.
    keep_pos = [full.obs.index.get_loc(i) for i in keep_idx]
    counts = full.layers["counts"][keep_pos]
    counts_dense = counts.toarray() if hasattr(counts, "toarray") else np.asarray(counts)
    obs_sub = full.obs.iloc[keep_pos]

    # Most-variable genes, for speed (real single-cell training on all 18k genes is not what a
    # smoke-test fixture needs).
    gene_var = counts_dense.var(axis=0)
    top_genes = np.argsort(gene_var)[::-1][: args.n_genes]
    counts_dense = counts_dense[:, top_genes]
    var = full.var.iloc[top_genes].copy()

    # script.py reads adata.X for raw counts (setup_anndata's is_count_data=True path) -- the
    # source file only ever has a `counts` layer, never .X. Move it, don't duplicate needlessly.
    # Plain numpy/object dtypes throughout -- the source file's obs/var use pandas nullable
    # string/categorical extension arrays in places, which older anndata (<0.11, pinned here via
    # the shared reagent env) refuses to write without an explicit opt-in setting.
    out = ad.AnnData(
        X=counts_dense.astype(np.float32),
        obs=pd.DataFrame(
            {
                "cell_type": obs_sub["cell_type"].astype(str).to_numpy(dtype=object),
                "sm_name": obs_sub["sm_name"].astype(str).to_numpy(dtype=object),
                "control": obs_sub["control"].to_numpy(dtype=bool),
                "dose_uM": obs_sub["dose_uM"].to_numpy(dtype=np.float64),
            },
            index=np.asarray(obs_sub.index, dtype=object),
        ),
        var=pd.DataFrame(index=np.asarray(var.index, dtype=object)),
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sc_train_path = OUT_DIR / "sc_train.h5ad"
    out.write_h5ad(sc_train_path, compression="gzip")
    print(f"Wrote {sc_train_path}: {out.shape[0]} cells x {out.shape[1]} genes, "
          f"{out.obs['sm_name'].nunique()} sm_name values ({out.obs['control'].sum()} control cells)")

    # id_map: query every non-control compound against this cell type (the only cell type in the
    # fixture -- multi-cell-type querying isn't exercised here, matching the fixture's own scope).
    id_map = pd.DataFrame({
        "id": range(len(chosen_compounds)),
        "cell_type": args.cell_type,
        "sm_name": chosen_compounds,
    })
    id_map_path = OUT_DIR / "id_map.csv"
    id_map.to_csv(id_map_path, index=False)
    print(f"Wrote {id_map_path}: {len(id_map)} query rows")


if __name__ == "__main__":
    main()
