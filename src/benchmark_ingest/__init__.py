"""Reusable primitives for benchmark-configured dataset ingestion."""

from .adata import (
    IngestContract,
    ValidationReport,
    get_counts,
    inspect_anndata,
    inspect_dataframe,
    load_ingest_contract,
    sha256_file,
    validate_ingested_adata,
)
from .chemistry import (
    LookupResult,
    StructureResult,
    drop_unresolved_treatments,
    normalize_inchikey,
    resolve_compounds,
    standardize_smiles,
)
from .downloads import download_file
from .prompts import render_ingest_prompt
from .qc import compute_qc_metrics, filter_with_audit, summarize_qc
from .sampling import select_condition_subset
from .splits import (
    create_cell_type_manifests,
    split_adata_by_manifest,
    write_cell_type_manifests,
)

__all__ = [
    "IngestContract",
    "LookupResult",
    "StructureResult",
    "ValidationReport",
    "compute_qc_metrics",
    "create_cell_type_manifests",
    "download_file",
    "drop_unresolved_treatments",
    "filter_with_audit",
    "get_counts",
    "inspect_anndata",
    "inspect_dataframe",
    "load_ingest_contract",
    "normalize_inchikey",
    "render_ingest_prompt",
    "resolve_compounds",
    "select_condition_subset",
    "sha256_file",
    "standardize_smiles",
    "summarize_qc",
    "split_adata_by_manifest",
    "validate_ingested_adata",
    "write_cell_type_manifests",
]
