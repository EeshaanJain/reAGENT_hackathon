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
meta = {"name": "broken_adapter_wrong_layer"}
## VIASH END

# Deliberately broken, so the Gauntlet has a failing case to catch (G1). file_prediction.yaml
# requires the output layer be named literally "prediction" (verified against
# src/methods/scape/script.py's real `layers={"prediction": ...}`) -- this adapter writes "logFC"
# instead. A real metric component would find no "prediction" layer at all: confident-looking
# garbage, zero runtime errors -- exactly the "silent killer" G1 exists for. See
# broken_adapter_collapsed_mean/ for the separate G3 failure mode (correct layer, insensitive to
# compound identity).

print("Reading input files", flush=True)
de_train = ad.read_h5ad(par["de_train"])
id_map = pd.read_csv(par["id_map"])
layer = par["layer"]

means: dict[str, np.ndarray] = {}
for ct in de_train.obs["cell_type"].unique():
    mask = (de_train.obs["cell_type"] == ct).values
    means[ct] = de_train.layers[layer][mask].mean(axis=0)

preds = np.stack([means[row["cell_type"]] for _, row in id_map.iterrows()]).astype(np.float32)

out = ad.AnnData(
    layers={"logFC": preds},  # <-- the bug: wrong layer name, should be "prediction"
    obs=pd.DataFrame(index=id_map["id"].astype(str)),
    var=pd.DataFrame(index=de_train.var_names),
    uns={
        "dataset_id": de_train.uns.get("dataset_id", "unknown"),
        "method_id": meta["name"],
    },
)
out.write_h5ad(par["output"], compression="gzip")
print("Done", flush=True)
