from __future__ import annotations

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from benchmark_ingest import (
    create_cell_type_manifests,
    split_adata_by_manifest,
    write_cell_type_manifests,
)


def _valid_manifest() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cell_id": ["cell_1", "cell_2", "cell_3"],
            "cell_type": ["A549", "A549", "K562"],
            "split": ["train", "train", "test"],
        }
    )


def test_create_cell_type_manifests_is_deterministic() -> None:
    obs = pd.DataFrame(
        {"cell_type": ["MCF7", "A549", "K562", "A549"]},
        index=["cell_4", "cell_1", "cell_3", "cell_2"],
    )

    manifests = create_cell_type_manifests(obs)

    assert list(manifests) == ["A549", "K562", "MCF7"]
    for held_out, manifest in manifests.items():
        assert list(manifest.columns) == ["cell_id", "cell_type", "split"]
        assert manifest["cell_id"].tolist() == obs.index.tolist()
        assert set(manifest["split"]) == {"train", "test"}
        assert manifest.loc[manifest["split"].eq("test"), "cell_type"].eq(held_out).all()
        assert manifest.loc[manifest["split"].eq("train"), "cell_type"].ne(held_out).all()


def test_split_adata_aligns_shuffled_manifest_and_returns_copies(valid_adata) -> None:
    manifest = _valid_manifest().sample(frac=1, random_state=7).reset_index(drop=True)

    adata_train, adata_test = split_adata_by_manifest(valid_adata, manifest)

    assert adata_train.obs_names.tolist() == ["cell_1", "cell_2"]
    assert adata_test.obs_names.tolist() == ["cell_3"]
    assert not adata_train.is_view
    assert not adata_test.is_view
    assert "split" not in adata_train.obs
    assert "split" not in adata_test.obs
    adata_train.obs["local_change"] = True
    assert "local_change" not in valid_adata.obs


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda frame: frame.drop(index=2), "cover adata.obs_names exactly"),
        (
            lambda frame: frame.assign(cell_id=["cell_1", "cell_2", "unknown"]),
            "cover adata.obs_names exactly",
        ),
        (
            lambda frame: frame.assign(cell_id=["cell_1", "cell_1", "cell_3"]),
            "duplicate cell IDs",
        ),
        (
            lambda frame: frame.assign(cell_id=["cell_1", None, "cell_3"]),
            "contains missing values",
        ),
        (
            lambda frame: frame.assign(split=["train", "validation", "test"]),
            "labels must be",
        ),
        (
            lambda frame: frame.assign(split=["train", "train", "train"]),
            "non-empty train and test",
        ),
        (
            lambda frame: frame.assign(cell_type=["A549", "K562", "K562"]),
            "cell_type values do not match",
        ),
    ],
)
def test_split_adata_rejects_invalid_manifests(valid_adata, mutate, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        split_adata_by_manifest(valid_adata, mutate(_valid_manifest()))


def test_split_adata_supports_backed_input(valid_adata, tmp_path) -> None:
    input_path = tmp_path / "input.h5ad"
    valid_adata.obsm["embedding"] = np.arange(6).reshape(3, 2)
    valid_adata.obsp["cell_graph"] = sparse.eye(3, format="csr")
    valid_adata.varm["loadings"] = np.arange(6).reshape(3, 2)
    valid_adata.varp["gene_graph"] = sparse.eye(3, format="csr")
    valid_adata.raw = ad.AnnData(
        X=valid_adata.layers["counts"].copy(),
        obs=pd.DataFrame(index=valid_adata.obs_names.copy()),
        var=valid_adata.var.copy(),
    )
    valid_adata.write_h5ad(input_path)
    backed = ad.read_h5ad(input_path, backed="r")
    try:
        adata_train, adata_test = split_adata_by_manifest(backed, _valid_manifest())
    finally:
        backed.file.close()

    assert not adata_train.isbacked
    assert not adata_test.isbacked
    assert not adata_train.is_view
    assert not adata_test.is_view
    assert adata_train.obs_names.tolist() == ["cell_1", "cell_2"]
    assert adata_test.obs_names.tolist() == ["cell_3"]
    assert list(adata_train.layers) == ["counts"]
    assert list(adata_train.obsm) == ["embedding"]
    assert list(adata_train.obsp) == ["cell_graph"]
    assert list(adata_train.varm) == ["loadings"]
    assert list(adata_train.varp) == ["gene_graph"]
    assert adata_train.raw is not None
    assert adata_train.raw.n_obs == 2
    assert adata_train.uns == valid_adata.uns


def test_write_cell_type_manifests_and_overwrite_guard(valid_adata, tmp_path) -> None:
    input_path = tmp_path / "input.h5ad"
    output_dir = tmp_path / "splits"
    valid_adata.write_h5ad(input_path)

    outputs = write_cell_type_manifests(input_path, output_dir)

    assert list(outputs) == ["A549", "K562"]
    assert {path.name for path in outputs.values()} == {"test_A549.csv", "test_K562.csv"}
    for held_out, path in outputs.items():
        manifest = pd.read_csv(path)
        assert list(manifest.columns) == ["cell_id", "cell_type", "split"]
        assert manifest["cell_id"].tolist() == valid_adata.obs_names.tolist()
        test_types = manifest.loc[manifest["split"].eq("test"), "cell_type"]
        assert test_types.eq(held_out).all()

    with pytest.raises(FileExistsError, match="pass --force"):
        write_cell_type_manifests(input_path, output_dir)
    assert write_cell_type_manifests(input_path, output_dir, force=True) == outputs
