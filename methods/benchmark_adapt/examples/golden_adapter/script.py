import hashlib

import anndata as ad
import numpy as np
import pandas as pd

## VIASH START
par = {
    "de_train": "../../fixtures/data/de_train.h5ad",
    "id_map": "../../fixtures/data/id_map.csv",
    "layer": "clipped_sign_log10_pval",
    "output": "prediction.h5ad",
}
meta = {"name": "golden_adapter"}
## VIASH END

# A toy but genuinely correct reference adapter (the A1 "hand-write one adapter" golden reference,
# sized for the tiny fixture rather than a real OP3 dataset). For each id_map row, it predicts the
# training DE profile of a deterministic hash-selected "nearest" training compound observed for
# that cell type, read from whichever de_train layer `par['layer']` names (real wf_method.yaml
# argument, default clipped_sign_log10_pval). It's not a scientifically meaningful method -- the
# point is that it (a) only reads de_train + id_map, never de_test, (b) is a genuine function of
# sm_name so shuffling id_map's sm_name changes the prediction (Gauntlet G3), and (c) copies real,
# already in-range training values through unchanged, so range/finiteness (G1) hold by
# construction.
#
# Output convention verified against src/methods/scape/script.py, a real shipped OP3 method:
# layer literally named "prediction" (file_prediction.yaml), obs indexed by id_map["id"] (no
# cell_type/sm_name columns required or expected on the output).

print("Reading input files", flush=True)
de_train = ad.read_h5ad(par["de_train"])
id_map = pd.read_csv(par["id_map"])
layer = par["layer"]

train_profiles: dict[str, dict[str, np.ndarray]] = {}
for i, (cell_type, sm_name) in enumerate(zip(de_train.obs["cell_type"], de_train.obs["sm_name"])):
    train_profiles.setdefault(cell_type, {})[sm_name] = de_train.layers[layer][i]


def nearest_train_compound(cell_type: str, sm_name: str, available: list[str]) -> str:
    compounds = sorted(available)
    h = int(hashlib.sha256(f"{cell_type}|{sm_name}".encode()).hexdigest(), 16)
    return compounds[h % len(compounds)]


print("Predicting", flush=True)
n_genes = de_train.n_vars
preds = np.zeros((len(id_map), n_genes), dtype=np.float32)
for i, row in id_map.iterrows():
    available = train_profiles.get(row["cell_type"])
    if not available:
        raise ValueError(f"no training compounds observed for cell_type={row['cell_type']!r}")
    nn = nearest_train_compound(row["cell_type"], row["sm_name"], list(available.keys()))
    preds[i] = available[nn]

print("Writing output", flush=True)
out = ad.AnnData(
    layers={"prediction": preds},
    obs=pd.DataFrame(index=id_map["id"].astype(str)),
    var=pd.DataFrame(index=de_train.var_names),
    uns={
        "dataset_id": de_train.uns.get("dataset_id", "unknown"),
        "method_id": meta["name"],
    },
)
out.write_h5ad(par["output"], compression="gzip")
print("Done", flush=True)
