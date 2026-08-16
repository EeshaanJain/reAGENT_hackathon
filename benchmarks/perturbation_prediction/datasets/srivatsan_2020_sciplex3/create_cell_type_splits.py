#!/usr/bin/env python3
"""Create leave-one-cell-type-out manifests for the SciPlex dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from psls_tooling import write_cell_type_manifests

DATASET_ID = "srivatsan_2020_sciplex3"
ROOT = Path(__file__).resolve().parents[4]
DEFAULT_INPUT = ROOT / "data" / "processed" / f"{DATASET_ID}.h5ad"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "splits" / DATASET_ID


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--force", action="store_true", help="Replace existing split CSVs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = write_cell_type_manifests(args.input, args.output_dir, force=args.force)
    for cell_type, output in outputs.items():
        counts = pd.read_csv(output, usecols=["split"])["split"].value_counts().to_dict()
        print(
            f"held_out_cell_type={cell_type} "
            f"train={counts.get('train', 0)} test={counts.get('test', 0)} "
            f"output={output}"
        )


if __name__ == "__main__":
    main()
