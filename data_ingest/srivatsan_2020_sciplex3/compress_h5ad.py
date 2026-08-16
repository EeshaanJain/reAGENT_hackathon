#!/usr/bin/env python3
"""Create a smaller, directly readable copy of the validated sciPlex3 H5AD.

The source ingest already uses gzip.  This repack adds the standard HDF5 byte-
shuffle filter to the three large CSR arrays before gzip compression.  It does
not alter any logical values, dtypes, AnnData fields, or metadata.

Run from the repository root with::

    uv run python data_ingest/srivatsan_2020_sciplex3/compress_h5ad.py

The HDF5 command-line tools ``h5repack`` and ``h5diff`` must be installed.
They are provided by the Homebrew ``hdf5`` package on macOS.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path

import anndata as ad

from psls_tooling import validate_ingested_adata

ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "srivatsan_2020_sciplex3"
DEFAULT_INPUT = ROOT / "data" / "processed" / f"{DATASET_ID}.h5ad"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / f"{DATASET_ID}_compressed.h5ad"
CSR_DATASETS = (
    "/layers/counts/data",
    "/layers/counts/indices",
    "/layers/counts/indptr",
)


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    """Return the SHA-256 checksum without loading the file into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing output only after the new copy passes validation.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    temporary = output.with_name(f".{output.name}.tmp")

    if not source.is_file():
        raise FileNotFoundError(f"Input H5AD does not exist: {source}")
    if source == output:
        raise ValueError("Input and output must be different; the source is preserved.")
    if output.exists() and not args.force:
        raise FileExistsError(f"Output already exists: {output}; pass --force to replace it.")
    if temporary.exists():
        raise FileExistsError(f"Temporary output already exists: {temporary}")

    h5repack = shutil.which("h5repack")
    h5diff = shutil.which("h5diff")
    if h5repack is None or h5diff is None:
        raise RuntimeError("h5repack and h5diff are required (install the HDF5 command-line tools).")

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [h5repack]
    for dataset in CSR_DATASETS:
        command.extend(("-f", f"{dataset}:SHUF", "-f", f"{dataset}:GZIP=4"))
    command.extend((str(source), str(temporary)))

    try:
        subprocess.run(command, check=True)

        # h5diff compares logical HDF5 values and attributes, independent of filters.
        subprocess.run((h5diff, "-q", str(source), str(temporary)), check=True)

        reopened = ad.read_h5ad(temporary)
        validation = validate_ingested_adata(reopened)
        if not validation.ok:
            raise RuntimeError(
                "Compressed H5AD failed validation: "
                f"errors={validation.errors!r}, warnings={validation.warnings!r}"
            )
        del reopened

        if output.exists():
            output.unlink()
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    source_bytes = source.stat().st_size
    output_bytes = output.stat().st_size
    reduction = 100.0 * (1.0 - output_bytes / source_bytes)
    print(f"output={output}")
    print(f"source_bytes={source_bytes}")
    print(f"output_bytes={output_bytes}")
    print(f"size_reduction_pct={reduction:.2f}")
    print(f"sha256={sha256_file(output)}")
    print(f"validation_summary={validation.summary}")


if __name__ == "__main__":
    main()
