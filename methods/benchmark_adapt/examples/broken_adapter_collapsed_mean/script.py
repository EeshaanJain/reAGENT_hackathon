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
meta = {"name": "broken_adapter_collapsed_mean"}
## VIASH END

# Deliberately broken, so the Gauntlet has a failing case to catch (G3). Writes the correctly
# named "prediction" layer with in-range values -- passes G1/G6 -- but the prediction depends
# only on cell_type, never on sm_name. Shuffling id_map's sm_name produces an identical
# prediction. This is the "collapsed to the training mean" failure mode: it scores respectably
# while carrying zero perturbation-specific signal.

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
