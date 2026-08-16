#!/usr/bin/env python3
"""Create leave-one-cell-type-out train/test manifests for sci-Plex 3.

Run from the repository root with::

    uv run python data_ingest/srivatsan_2020_sciplex3/create_cell_type_splits.py
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd

DATASET_ID = "srivatsan_2020_sciplex3"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "processed" / f"{DATASET_ID}.h5ad"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "splits" / DATASET_ID


def create_cell_type_manifests(obs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Create one deterministic leave-one-cell-type-out manifest per cell type."""
    if "cell_type" not in obs:
        raise ValueError("obs must contain a 'cell_type' column")
    if not obs.index.is_unique:
        raise ValueError("obs index must contain unique cell IDs")
    if obs.index.hasnans:
        raise ValueError("obs index contains missing cell IDs")

    cell_ids = pd.Index(obs.index.astype(str), name="cell_id")
    if not cell_ids.is_unique:
        raise ValueError("obs cell IDs are not unique after conversion to strings")

    source_cell_types = obs["cell_type"]
    if source_cell_types.isna().any():
        raise ValueError("obs['cell_type'] contains missing values")
    cell_types = source_cell_types.astype(str)
    if cell_types.str.strip().eq("").any():
        raise ValueError("obs['cell_type'] contains empty values")

    unique_cell_types = sorted(cell_types.unique())
    if len(unique_cell_types) < 2:
        raise ValueError("At least two cell types are required to create train/test splits")

    manifests: dict[str, pd.DataFrame] = {}
    cell_type_values = cell_types.to_numpy()
    for held_out_cell_type in unique_cell_types:
        manifests[held_out_cell_type] = pd.DataFrame(
            {
                "cell_id": cell_ids.to_numpy(),
                "cell_type": cell_type_values,
                "split": np.where(
                    cell_type_values == held_out_cell_type,
                    "test",
                    "train",
                ),
            }
        )
    return manifests


def write_cell_type_manifests(
    input_path: Path,
    output_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """Read only AnnData observation metadata and write every cell-type manifest."""
    input_path = input_path.resolve()
    output_dir = output_dir.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input H5AD does not exist: {input_path}")

    # anndata.read_h5ad(backed="r") still eagerly loads matrices stored in
    # layers. Read the standards-compliant obs element directly so this command
    # never loads the sci-Plex counts layer.
    with h5py.File(input_path, "r") as store:
        if "obs" not in store:
            raise ValueError(f"Input H5AD does not contain observation metadata: {input_path}")
        obs = ad.io.read_elem(store["obs"])
    manifests = create_cell_type_manifests(obs)

    outputs = {
        cell_type: output_dir / f"test_{cell_type}.csv" for cell_type in manifests
    }
    existing = [path for path in outputs.values() if path.exists()]
    if existing and not force:
        rendered = ", ".join(map(str, existing))
        raise FileExistsError(f"Split output already exists: {rendered}; pass --force to replace it")

    output_dir.mkdir(parents=True, exist_ok=True)
    for cell_type, manifest in manifests.items():
        output = outputs[cell_type]
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=output_dir,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                manifest.to_csv(temporary, index=False)
            temporary_path.chmod(0o644)
            temporary_path.replace(output)
        except BaseException:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing split CSVs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = write_cell_type_manifests(args.input, args.output_dir, force=args.force)
    for cell_type, output in outputs.items():
        manifest = pd.read_csv(output, usecols=["split"])
        counts = manifest["split"].value_counts().to_dict()
        print(
            f"held_out_cell_type={cell_type} "
            f"train={counts.get('train', 0)} test={counts.get('test', 0)} "
            f"output={output}"
        )


if __name__ == "__main__":
    main()
