#!/usr/bin/env python3
"""Reproducibly ingest the official sci-Plex 3 count matrix and metadata.

This script intentionally starts from the processed UMI coordinate matrix
deposited at GEO. It never downloads or processes sequencing reads.
"""

from __future__ import annotations

import gc
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from benchmark_ingest import (
    LookupResult,
    compute_qc_metrics,
    download_file,
    drop_unresolved_treatments,
    filter_with_audit,
    inspect_anndata,
    inspect_dataframe,
    load_ingest_contract,
    resolve_compounds,
    select_condition_subset,
    sha256_file,
    standardize_smiles,
    summarize_qc,
    validate_ingested_adata,
)

DATASET_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
DATASET_CONFIG_PATH = DATASET_DIR / "dataset.yaml"
DATASET_CONFIG = yaml.safe_load(DATASET_CONFIG_PATH.read_text())
DATASET_METADATA = DATASET_CONFIG["dataset"]
INGEST_CONFIG = DATASET_CONFIG["ingest"]
SUBSET_CONFIG = DATASET_CONFIG["subset"]
DATASET_ID = str(DATASET_METADATA["dataset_id"])
GEO_ACCESSION = str(DATASET_METADATA["accession"])
PUBLICATION_URL = str(DATASET_METADATA["publication_url"])
CODE_URL = str(DATASET_METADATA["code_url"])
CODE_COMMIT = str(DATASET_METADATA["code_commit"])
GEO_URL = str(DATASET_METADATA["data_url_or_accession"])
PROTOCOL_URL = str(DATASET_METADATA["protocol_url"])
CONTRACT_PATH = (DATASET_DIR / DATASET_CONFIG["ingest_contract"]).resolve()
INGEST_CONTRACT = load_ingest_contract(CONTRACT_PATH)
RAW_DIR = ROOT / "data" / "raw" / DATASET_ID
OUTPUT = ROOT / "data" / "processed" / f"{DATASET_ID}.h5ad"
REPORT = DATASET_DIR / "ingest_report.md"
PUBLICATION_PDF = ROOT / str(DATASET_METADATA["local_pdf_path"])
PUBLICATION_PDF_SHA256 = str(DATASET_METADATA["local_pdf_sha256"])
SOURCE_FILES: dict[str, dict[str, str]] = INGEST_CONFIG["source_files"]
REQUIRED_PDATA_COLUMNS = frozenset(map(str, INGEST_CONFIG["required_pdata_columns"]))
MATRIX_CHUNK_ROWS = int(INGEST_CONFIG["matrix_chunk_rows"])
EXPECTED_TREATED_COMPOUNDS = int(INGEST_CONFIG["expected_treated_compounds"])
CONTROL_CONFIG = INGEST_CONFIG["control"]
CONTROL_CATALOG_NUMBER = str(CONTROL_CONFIG["source_catalog_number"])
CONTROL_LABEL = str(CONTROL_CONFIG["output_label"])
FALLBACK_CONFIG = INGEST_CONFIG["exact_identifier_fallback"]
FALLBACK_CAS_NUMBER = str(FALLBACK_CONFIG["cas_number"])
FALLBACK_EXPECTED_INCHIKEY = str(FALLBACK_CONFIG["expected_inchikey"])
FALLBACK_SOURCE = str(FALLBACK_CONFIG["source"])
FALLBACK_EXPECTED_ROWS = int(FALLBACK_CONFIG["expected_rows"])
PROTOCOL_CONFIG = INGEST_CONFIG["single_cell_protocol"]


def log(message: str) -> None:
    print(message, flush=True)


def download_and_verify_sources() -> dict[str, Path]:
    """Download missing processed inputs and reject checksum mismatches."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for key, source in SOURCE_FILES.items():
        path = RAW_DIR / source["filename"]
        paths[key] = path
        if not path.exists():
            log(f"Downloading {source['url']}")
            download_file(source["url"], path)
        actual = sha256_file(path)
        if actual != source["sha256"]:
            raise RuntimeError(
                f"BLOCKER: checksum mismatch for {path}: expected {source['sha256']}, got {actual}"
            )
    if not PUBLICATION_PDF.exists():
        raise RuntimeError(f"BLOCKER: required local publication PDF is missing: {PUBLICATION_PDF}")
    actual_pdf = sha256_file(PUBLICATION_PDF)
    if actual_pdf != PUBLICATION_PDF_SHA256:
        raise RuntimeError(
            "BLOCKER: local publication PDF checksum differs from the audited copy: "
            f"expected {PUBLICATION_PDF_SHA256}, got {actual_pdf}"
        )
    return paths


def read_sources(paths: dict[str, Path]) -> dict[str, pd.DataFrame]:
    """Read and validate every downloaded metadata file before transformation."""
    frames = {
        "cell_annotations": pd.read_csv(
            paths["cell_annotations"], sep="\t", header=None, names=["cell", "sample"]
        ),
        "gene_annotations": pd.read_csv(paths["gene_annotations"], sep=r"\s+"),
        "hash_metadata": pd.read_csv(paths["hash_metadata"], sep="\t"),
        "pdata": pd.read_csv(paths["pdata"], sep=r"\s+"),
        "hash_sample_sheet": pd.read_csv(
            paths["hash_sample_sheet"],
            sep=r"\s+",
            header=None,
            names=["hash_id", "sequence", "n_hashes"],
        ),
        "gencode_bed": pd.read_csv(
            paths["gencode_bed"],
            sep="\t",
            header=None,
            names=[
                "chrom",
                "start",
                "end",
                "transcript_id",
                "score",
                "strand",
                "gene_id",
                "gene_symbol",
                "gene_type",
            ],
        ),
    }
    cells = frames["cell_annotations"]
    genes = frames["gene_annotations"]
    pdata = frames["pdata"]
    if not cells["cell"].is_unique or not genes["id"].is_unique or not pdata["cell"].is_unique:
        raise RuntimeError("BLOCKER: deposited cell or gene identifiers are not unique")
    if not np.array_equal(pdata.index.astype(str), pdata["cell"].astype(str).to_numpy()):
        raise RuntimeError("BLOCKER: pData row names and explicit cell identifiers disagree")
    if len(cells) != len(pdata) or not np.array_equal(
        cells["cell"].to_numpy(), pdata["cell"].to_numpy()
    ):
        raise RuntimeError("BLOCKER: pData rows do not exactly match deposited matrix cell order")
    if not np.array_equal(cells["sample"].to_numpy(), pdata["sample"].to_numpy()):
        raise RuntimeError("BLOCKER: cell-annotation and pData sample labels disagree")
    missing = sorted(REQUIRED_PDATA_COLUMNS - set(pdata))
    if missing:
        raise RuntimeError(f"BLOCKER: required deposited pData columns are missing: {missing}")
    return frames


def metadata_inventory(frames: dict[str, pd.DataFrame]) -> dict[str, list[dict[str, Any]]]:
    return {name: inspect_dataframe(frame) for name, frame in frames.items()}


def resolve_chemicals(
    hash_metadata: pd.DataFrame, pubchem_cache: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Resolve deposited structures, using one exact-CAS cache before any name lookup."""
    treated = (
        hash_metadata.loc[
            ~hash_metadata["vehicle"], ["catalog_number", "name", "CAS.Number", "SMILES"]
        ]
        .drop_duplicates()
        .sort_values("catalog_number")
        .reset_index(drop=True)
    )
    if len(treated) != EXPECTED_TREATED_COMPOUNDS or not treated["catalog_number"].is_unique:
        raise RuntimeError(
            "BLOCKER: expected "
            f"{EXPECTED_TREATED_COMPOUNDS} unique treated catalog numbers in deposited metadata"
        )

    # Explicit call retained for the audit even though resolve_compounds also calls it internally.
    direct_results = treated["SMILES"].map(standardize_smiles)
    direct_by_catalog = dict(zip(treated["catalog_number"], direct_results, strict=True))

    pubchem = json.loads(pubchem_cache.read_text())
    properties = pubchem.get("PropertyTable", {}).get("Properties", [])
    if len(properties) != 1:
        raise RuntimeError("BLOCKER: exact PubChem CAS query did not return one unique structure")
    cached_property = properties[0]
    cached_parent = standardize_smiles(cached_property.get("SMILES"))
    if cached_parent.inchikey != FALLBACK_EXPECTED_INCHIKEY:
        raise RuntimeError(
            f"BLOCKER: exact-CAS parent for {FALLBACK_CAS_NUMBER} changed or is ambiguous"
        )

    def exact_identifier_fallback(row: pd.Series) -> LookupResult:
        if str(row.get("CAS.Number", "")).strip() == FALLBACK_CAS_NUMBER:
            return LookupResult(
                cached_parent.inchikey,
                FALLBACK_SOURCE,
                cached_parent.status,
            )
        return LookupResult(None, "exact_identifier_only", "not_found")

    resolved = resolve_compounds(
        treated,
        inchikey_col=None,
        smiles_col="SMILES",
        fallback_resolver=exact_identifier_fallback,
    )

    _patch_fallback_structure_audit(resolved, cached_parent)

    unresolved = resolved.loc[resolved["inchikey"].isna(), "catalog_number"].tolist()
    resolved["multicomponent_structure"] = resolved["chemical_status"].isin(
        ["large_fragment_preserved", "multicomponent_preserved"]
    )
    resolved["sm_name"] = resolved["name"].astype(str).str.strip()
    audit = {
        "treated_compounds": int(len(treated)),
        "direct_structure_status": pd.Series([result.status for result in direct_results])
        .value_counts()
        .to_dict(),
        "final_resolution_status": resolved["chemical_status"].value_counts().to_dict(),
        "resolution_sources": resolved["inchikey_source"].value_counts().to_dict(),
        "unresolved_catalog_numbers": unresolved,
        "preserved_multicomponent": resolved.loc[
            resolved["multicomponent_structure"],
            ["catalog_number", "name", "chemical_status", "canonical_smiles", "inchikey"],
        ].to_dict(orient="records"),
        "desalted": resolved.loc[
            resolved["desalted"], ["catalog_number", "name", "removed_fragments"]
        ].to_dict(orient="records"),
        "direct_results": {
            catalog: asdict(result) for catalog, result in direct_by_catalog.items()
        },
    }
    return resolved, audit


def _patch_fallback_structure_audit(resolved: pd.DataFrame, cached_parent: Any) -> None:
    """Attach cached structure details to exactly the configured fallback rows."""
    fallback_indices = resolved.index[resolved["inchikey_source"].eq(FALLBACK_SOURCE)]
    if len(fallback_indices) != FALLBACK_EXPECTED_ROWS:
        raise RuntimeError(
            "BLOCKER: expected "
            f"{FALLBACK_EXPECTED_ROWS} {FALLBACK_SOURCE!r} row(s), found {len(fallback_indices)}"
        )
    for idx in fallback_indices:
        resolved.loc[idx, "canonical_smiles"] = cached_parent.canonical_smiles
        resolved.loc[idx, "desalted"] = cached_parent.desalted
        resolved.loc[idx, "removed_fragments"] = "|".join(cached_parent.removed_fragments)
        resolved.loc[idx, "parent_candidate_smiles"] = cached_parent.parent_candidate_smiles
        resolved.loc[idx, "parent_candidate_inchikey"] = cached_parent.parent_candidate_inchikey


def build_obs(
    pdata: pd.DataFrame, resolved: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Apply published hash identity QC, attach treatment semantics, and drop unresolved drugs."""
    hash_pass = (
        pdata["top_oligo_P"].notna()
        & pdata["top_oligo_W"].notna()
        & pdata["hash_umis_P"].ge(5)
        & pdata["hash_umis_W"].ge(5)
        & pdata["top_to_second_best_ratio_P"].ge(5)
        & pdata["top_to_second_best_ratio_W"].ge(5)
        & pdata["rt_well"].ne(1)
    )
    semantic_columns = [
        "cell_type",
        "replicate",
        "time_point",
        "catalog_number",
        "dose",
        "product_name",
    ]
    semantics_complete = pdata[semantic_columns].notna().all(axis=1)
    identity_mask = hash_pass & semantics_complete
    identity_audit = {
        "cells_in_deposited_matrix": int(len(pdata)),
        "hash_pass": int(hash_pass.sum()),
        "hash_fail": int((~hash_pass).sum()),
        "hash_pass_without_legal_condition": int((hash_pass & ~semantics_complete).sum()),
        "identity_cells_retained": int(identity_mask.sum()),
        "criteria": (
            "both top hashes present; >=5 UMIs on each hash; >=5-fold top/second ratio on each "
            "hash; rt_well != 1; complete legal condition metadata"
        ),
    }

    source = pdata.loc[identity_mask].copy()
    source.index = pd.Index(source.pop("cell").astype(str), name="cell_id")
    if not source.index.is_unique:
        raise RuntimeError("BLOCKER: retained source cell identifiers are not unique")

    chem = resolved.set_index("catalog_number")
    chemical_columns = [
        "sm_name",
        "inchikey",
        "inchikey_source",
        "chemical_status",
        "canonical_smiles",
        "desalted",
        "removed_fragments",
        "parent_candidate_smiles",
        "parent_candidate_inchikey",
        "multicomponent_structure",
        "CAS.Number",
    ]
    for column in chemical_columns:
        source[column] = source["catalog_number"].map(chem[column])

    control = source["vehicle"].astype(bool)
    if not control.equals(source["catalog_number"].eq(CONTROL_CATALOG_NUMBER)):
        raise RuntimeError(
            "BLOCKER: deposited vehicle flags and configured control catalog labels disagree"
        )
    if not source.loc[control, "dose"].eq(0).all():
        raise RuntimeError("BLOCKER: a deposited vehicle cell has nonzero dose")

    source["sm_name_original"] = source["product_name"]
    source.loc[control, "sm_name"] = CONTROL_LABEL
    source.loc[control, "inchikey"] = None
    source.loc[control, "inchikey_source"] = "control_not_applicable"
    source.loc[control, "chemical_status"] = "control_not_applicable"
    source.loc[control, "canonical_smiles"] = None
    source.loc[control, "desalted"] = False
    source.loc[control, "removed_fragments"] = ""
    source.loc[control, "parent_candidate_smiles"] = None
    source.loc[control, "parent_candidate_inchikey"] = None
    source.loc[control, "multicomponent_structure"] = False

    source["dose_uM"] = source["dose"].astype(float) / 1000.0
    source["timepoint_hr"] = source["time_point"].astype(float)
    source["batch"] = source["replicate"].astype(str)
    source["control"] = control.astype(bool)
    source["desalted"] = source["desalted"].astype(bool)
    source["multicomponent_structure"] = source["multicomponent_structure"].astype(bool)

    rename = {
        "Size_Factor": "source_size_factor",
        "n.umi": "source_total_umis",
        "sample": "source_sample",
        "replicate": "source_replicate",
        "time_point": "source_timepoint_hr",
        "dose": "source_dose_nM",
        "vehicle": "source_vehicle",
        "treatment": "source_treatment",
        "product_name": "source_product_name",
    }
    source = source.rename(columns=rename)
    # Avoid duplicating canonical columns under less precise source names.
    source = source.drop(columns=["dose_character"], errors="ignore")

    required_first = [
        "dose_uM",
        "timepoint_hr",
        "cell_type",
        "sm_name",
        "sm_name_original",
        "inchikey",
        "batch",
        "control",
    ]
    source = source[required_first + [column for column in source if column not in required_first]]

    metadata_only = ad.AnnData(X=None, obs=source, shape=(len(source), 0))
    metadata_only, chemical_loss = drop_unresolved_treatments(metadata_only)
    obs = metadata_only.obs.copy()
    if obs["dose_uM"].isna().any() or obs["timepoint_hr"].isna().any():
        raise RuntimeError("BLOCKER: retained cells have missing dose or time")
    return obs, identity_audit, chemical_loss


def build_gene_map(
    genes: pd.DataFrame, gencode: pd.DataFrame
) -> tuple[np.ndarray, pd.DataFrame, dict[str, Any]]:
    """Map deposited gene rows to unique protein-coding symbols."""
    pc = (
        gencode.loc[gencode["gene_type"].eq("protein_coding")]
        .groupby(["gene_id", "gene_symbol"], sort=False, observed=True)
        .agg(chrom=("chrom", lambda values: "|".join(sorted(set(map(str, values))))))
        .reset_index()
    )
    matched = (
        genes.reset_index(names="source_gene_index")
        .merge(pc, left_on=["id", "gene_short_name"], right_on=["gene_id", "gene_symbol"])
        .sort_values("source_gene_index")
    )
    if len(matched) != pc["gene_id"].nunique():
        raise RuntimeError(
            "BLOCKER: deposited human genes do not match pinned GENCODE v27 protein-coding IDs"
        )
    symbols = pd.Index(pd.unique(matched["gene_short_name"]), name="gene_symbol")
    symbol_to_index = pd.Series(np.arange(len(symbols), dtype=np.int32), index=symbols)
    gene_map = np.full(len(genes), -1, dtype=np.int32)
    gene_map[matched["source_gene_index"].to_numpy()] = symbol_to_index.loc[
        matched["gene_short_name"]
    ].to_numpy(dtype=np.int32)

    grouped = matched.groupby("gene_short_name", sort=False, observed=True)
    var = grouped.agg(
        source_gene_ids=("id", lambda values: "|".join(map(str, values))),
        source_gene_id_count=("id", "size"),
        chromosomes=("chrom", lambda values: "|".join(sorted(set(map(str, values))))),
    )
    var = var.reindex(symbols)
    var["gene_type"] = "protein_coding"
    var["gencode_release"] = "v27"
    audit = {
        "deposited_genes": int(len(genes)),
        "human_genes": int(genes["id"].str.startswith("ENSG").sum()),
        "mouse_genes": int(genes["id"].str.startswith("ENSMUSG").sum()),
        "protein_coding_source_ids": int(len(matched)),
        "unique_protein_coding_symbols_before_expression_qc": int(len(var)),
        "symbols_aggregated_from_multiple_ids": int((var["source_gene_id_count"] > 1).sum()),
    }
    return gene_map, var, audit


def stream_counts(
    path: Path,
    *,
    n_source_genes: int,
    n_source_cells: int,
    source_total_umis: np.ndarray,
    gene_map: np.ndarray,
    cell_map: np.ndarray,
    n_output_cells: int,
    n_output_genes: int,
) -> tuple[sparse.csr_matrix, dict[str, Any]]:
    """Read the 1-based, cell-major coordinate file into a filtered CSR matrix."""
    data_chunks: list[np.ndarray] = []
    index_chunks: list[np.ndarray] = []
    row_nnz = np.zeros(n_output_cells, dtype=np.int64)
    raw_cell_totals = np.zeros(n_source_cells, dtype=np.int64)
    raw_nnz = 0
    retained_coordinate_rows = 0
    min_count = np.iinfo(np.int32).max
    max_count = 0
    max_gene_index = -1
    max_cell_index = -1
    previous_gene = -1
    previous_cell = -1

    reader = pd.read_csv(
        path,
        sep="\t",
        header=None,
        names=["gene", "cell", "count"],
        dtype={"gene": np.int32, "cell": np.int32, "count": np.int32},
        chunksize=MATRIX_CHUNK_ROWS,
    )
    for chunk_number, chunk in enumerate(reader, start=1):
        gene = chunk["gene"].to_numpy(copy=False) - 1
        cell = chunk["cell"].to_numpy(copy=False) - 1
        count = chunk["count"].to_numpy(copy=False)
        if len(chunk) == 0:
            continue
        if (
            gene.min() < 0
            or cell.min() < 0
            or count.min() <= 0
            or gene.max() >= n_source_genes
            or cell.max() >= n_source_cells
        ):
            raise RuntimeError("BLOCKER: count coordinate or value is outside deposited bounds")
        if previous_cell > cell[0] or (
            previous_cell == cell[0] and previous_gene >= gene[0]
        ):
            raise RuntimeError("BLOCKER: count coordinates are not strictly cell-major ordered")
        cell_delta = np.diff(cell)
        gene_delta = np.diff(gene)
        if np.any(cell_delta < 0) or np.any(gene_delta[cell_delta == 0] <= 0):
            raise RuntimeError("BLOCKER: count coordinates are unordered or duplicated")
        previous_gene = int(gene[-1])
        previous_cell = int(cell[-1])

        raw_nnz += len(chunk)
        min_count = min(min_count, int(count.min()))
        max_count = max(max_count, int(count.max()))
        max_gene_index = max(max_gene_index, int(gene.max()))
        max_cell_index = max(max_cell_index, int(cell.max()))
        raw_cell_totals += np.bincount(
            cell, weights=count, minlength=n_source_cells
        ).astype(np.int64)

        mapped_gene = gene_map[gene]
        mapped_cell = cell_map[cell]
        keep = (mapped_gene >= 0) & (mapped_cell >= 0)
        if keep.any():
            output_cells = mapped_cell[keep]
            if np.any(np.diff(output_cells) < 0):
                raise RuntimeError("BLOCKER: retained cell rows lost source order")
            output_genes = mapped_gene[keep].astype(np.int32, copy=True)
            output_counts = count[keep].astype(np.int32, copy=True)
            row_nnz += np.bincount(output_cells, minlength=n_output_cells).astype(np.int64)
            index_chunks.append(output_genes)
            data_chunks.append(output_counts)
            retained_coordinate_rows += len(output_counts)

        if chunk_number % 10 == 0:
            log(
                f"Read {raw_nnz:,} raw coordinate rows; retained "
                f"{retained_coordinate_rows:,} protein-coding rows"
            )

    # The annotation deliberately retains genes with zero counts, so the largest
    # observed gene index need not reach the final annotation row. Every cell was
    # source-filtered at >=500 UMIs and therefore must occur in the matrix.
    if max_cell_index != n_source_cells - 1:
        raise RuntimeError(
            "BLOCKER: count-coordinate cell maximum does not match deposited annotations"
        )
    if not np.array_equal(raw_cell_totals, source_total_umis.astype(np.int64)):
        mismatch = int(np.count_nonzero(raw_cell_totals != source_total_umis))
        raise RuntimeError(
            f"BLOCKER: raw matrix column sums disagree with deposited n.umi for {mismatch} cells"
        )

    indices = np.concatenate(index_chunks) if index_chunks else np.array([], dtype=np.int32)
    data = np.concatenate(data_chunks) if data_chunks else np.array([], dtype=np.int32)
    del index_chunks, data_chunks
    gc.collect()
    indptr = np.empty(n_output_cells + 1, dtype=np.int64)
    indptr[0] = 0
    np.cumsum(row_nnz, out=indptr[1:])
    if int(indptr[-1]) != len(data):
        raise RuntimeError("Internal error: CSR row counts do not match retained coordinates")
    counts = sparse.csr_matrix(
        (data, indices, indptr), shape=(n_output_cells, n_output_genes), copy=False
    )
    before_symbol_sum = int(counts.nnz)
    counts.sum_duplicates()
    counts.sort_indices()
    counts.eliminate_zeros()
    audit = {
        "format": "headerless tab-delimited 1-based gene_index, cell_index, UMI_count",
        "source_orientation": "genes_by_cells",
        "output_orientation": "cells_by_genes",
        "source_shape": [n_source_genes, n_source_cells],
        "raw_coordinate_rows": int(raw_nnz),
        "raw_count_min": int(min_count),
        "raw_count_max": int(max_count),
        "raw_gene_index_max": int(max_gene_index),
        "raw_cell_index_max": int(max_cell_index),
        "coordinates_strictly_cell_major": True,
        "source_column_sums_match_pdata_n_umi": True,
        "protein_coding_coordinate_rows": before_symbol_sum,
        "symbol_aggregated_nnz": int(counts.nnz),
        "symbol_duplicate_coordinates_summed": before_symbol_sum - int(counts.nnz),
        "dtype": str(counts.dtype),
        "sparse": True,
    }
    return counts, audit


def choose_qc_thresholds(adata: ad.AnnData) -> dict[str, Any]:
    """Select conservative rounded cutoffs from extreme dataset tails."""

    def round_down(value: float, multiple: int) -> int:
        return int(math.floor(value / multiple) * multiple)

    total_q001 = float(adata.obs["total_counts"].quantile(0.001))
    genes_q001 = float(adata.obs["n_genes_by_counts"].quantile(0.001))
    mt_q999 = float(adata.obs["pct_counts_mt"].quantile(0.999))
    return {
        "min_total_counts": max(100, round_down(total_q001, 25)),
        "min_genes_by_counts": max(50, round_down(genes_q001, 10)),
        "max_pct_counts_mt": min(20.0, max(5.0, float(math.ceil(mt_q999)))),
        "min_cells_by_counts_per_gene": 10,
        "derivation_total_counts": "rounded down 0.1st percentile, floor 100",
        "derivation_n_genes": "rounded down 0.1st percentile, floor 50",
        "derivation_pct_mt": "rounded up 99.9th percentile, bounded to [5, 20] percent",
        "derivation_gene_cells": "lower sparse tail; require detection in at least 10 cells",
    }


def qc_group_retention(obs: pd.DataFrame, mask: np.ndarray, column: str) -> pd.DataFrame:
    frame = pd.DataFrame({column: obs[column], "retained": mask}, index=obs.index)
    result = (
        frame.groupby(column, observed=True, dropna=False)["retained"]
        .agg(n_cells="size", cells_retained="sum", retention_fraction="mean")
        .reset_index()
    )
    result["cells_removed"] = result["n_cells"] - result["cells_retained"]
    return result


def apply_qc(
    adata: ad.AnnData,
) -> tuple[ad.AnnData, dict[str, Any], dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    compute_qc_metrics(adata)
    summaries = {
        "batch": summarize_qc(adata, by=("batch",)),
        "cell_type": summarize_qc(adata, by=("cell_type",)),
        "timepoint_hr": summarize_qc(adata, by=("timepoint_hr",)),
        "dose_uM": summarize_qc(adata, by=("dose_uM",)),
        "control": summarize_qc(adata, by=("control",)),
        "sm_name": summarize_qc(adata, by=("sm_name",)),
        "batch_cell_type": summarize_qc(adata, by=("batch", "cell_type")),
    }
    thresholds = choose_qc_thresholds(adata)
    cell_mask = (
        adata.obs["total_counts"].ge(thresholds["min_total_counts"])
        & adata.obs["n_genes_by_counts"].ge(thresholds["min_genes_by_counts"])
        & adata.obs["pct_counts_mt"].le(thresholds["max_pct_counts_mt"])
    ).to_numpy()
    gene_mask = adata.var["n_cells_by_counts"].ge(
        thresholds["min_cells_by_counts_per_gene"]
    ).to_numpy()
    retention = {
        column: qc_group_retention(adata.obs, cell_mask, column)
        for column in ["batch", "cell_type", "timepoint_hr", "dose_uM", "control", "sm_name"]
    }
    filtered, filter_audit = filter_with_audit(
        adata,
        cell_mask=cell_mask,
        gene_mask=gene_mask,
        decisions=thresholds,
    )
    compute_qc_metrics(filtered)
    filter_audit["pre_filter_quantiles"] = {
        metric: {
            str(q): float(adata.obs[metric].quantile(q))
            for q in [0, 0.001, 0.01, 0.05, 0.5, 0.95, 0.99, 0.999, 1]
        }
        for metric in ["total_counts", "n_genes_by_counts", "pct_counts_mt"]
    }
    filter_audit["gene_detection_quantiles"] = {
        str(q): float(adata.var["n_cells_by_counts"].quantile(q))
        for q in [0, 0.001, 0.01, 0.05, 0.5, 0.95, 0.99, 1]
    }
    return filtered, filter_audit, summaries, retention


def categoricalize_strings(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if pd.api.types.is_string_dtype(result[column]) or result[column].dtype == object:
            result[column] = result[column].astype("category")
    return result


def markdown_table(frame: pd.DataFrame, *, max_rows: int | None = None) -> str:
    if max_rows is not None:
        frame = frame.head(max_rows)
    clean = frame.copy()
    for column in clean:
        clean[column] = clean[column].map(
            lambda value: ""
            if pd.isna(value)
            else str(value).replace("|", "\\|").replace("\n", " ")
        )
    header = "| " + " | ".join(map(str, clean.columns)) + " |"
    rule = "| " + " | ".join(["---"] * len(clean.columns)) + " |"
    rows = ["| " + " | ".join(row) + " |" for row in clean.astype(str).to_numpy()]
    return "\n".join([header, rule, *rows])


def summarize_perturbation_qc(summary: pd.DataFrame) -> pd.DataFrame:
    metrics = ["total_counts_median", "n_genes_median", "pct_counts_mt_median"]
    rows = []
    for metric in metrics:
        low = summary.nsmallest(3, metric)[["sm_name", "n_cells", metric]].copy()
        high = summary.nlargest(3, metric)[["sm_name", "n_cells", metric]].copy()
        for direction, subset in [("lowest", low), ("highest", high)]:
            for _, row in subset.iterrows():
                rows.append(
                    {
                        "metric": metric,
                        "extreme": direction,
                        "sm_name": row["sm_name"],
                        "n_cells": int(row["n_cells"]),
                        "value": float(row[metric]),
                    }
                )
    return pd.DataFrame(rows)


def compact_anndata_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    """Keep the matrix/schema portion of an inspect_anndata result for the concise report."""
    return {
        "shape": inventory["shape"],
        "X": inventory["X"],
        "raw_X": inventory["raw_X"],
        "layers": inventory["layers"],
        "obs_names_unique": inventory["obs_names_unique"],
        "var_names_unique": inventory["var_names_unique"],
        "obs_columns": [column["column"] for column in inventory["obs"]],
        "var_columns": [column["column"] for column in inventory["var"]],
        "uns_keys": inventory["uns_keys"],
    }


def write_report(
    *,
    inventory: dict[str, list[dict[str, Any]]],
    chemical_audit: dict[str, Any],
    identity_audit: dict[str, Any],
    chemical_loss: dict[str, Any],
    gene_audit: dict[str, Any],
    matrix_audit: dict[str, Any],
    initial_inventory: dict[str, Any],
    qc_audit: dict[str, Any],
    qc_summaries: dict[str, pd.DataFrame],
    retention: dict[str, pd.DataFrame],
    selection_audit: dict[str, Any],
    final_inventory: dict[str, Any],
    validation: Any,
    output_sha256: str,
) -> None:
    source_rows = [
        {
            "source": "publication PDF",
            "role": "used: publication evidence",
            "URL": PUBLICATION_URL,
            "SHA-256": PUBLICATION_PDF_SHA256,
        }
    ]
    source_rows.extend(
        {
            "source": source["filename"],
            "role": source["role"],
            "URL": source["url"],
            "SHA-256": source["sha256"],
        }
        for source in SOURCE_FILES.values()
    )
    source_table = markdown_table(pd.DataFrame(source_rows))

    metadata_rows = []
    for source, columns in inventory.items():
        for column in columns:
            metadata_rows.append(
                {
                    "source": source,
                    "column": column["column"],
                    "dtype": column["dtype"],
                    "missing": column["missing"],
                    "cardinality": column["unique"],
                    "representative values": ", ".join(column["examples"][:3]),
                }
            )
    metadata_table = markdown_table(pd.DataFrame(metadata_rows))

    qc_thresholds = qc_audit["decisions"]
    group_tables = []
    for name in ["batch", "cell_type", "timepoint_hr", "dose_uM", "control"]:
        group_tables.append(f"#### By {name}\n\n{markdown_table(qc_summaries[name])}")
    perturbation_extremes = summarize_perturbation_qc(qc_summaries["sm_name"])
    retention_rows = []
    for name, frame in retention.items():
        eligible = frame.loc[frame["n_cells"] >= 50]
        lowest = eligible.nsmallest(1, "retention_fraction").iloc[0] if len(eligible) else None
        retention_rows.append(
            {
                "stratum": name,
                "groups checked": len(frame),
                "minimum retention (groups >=50 cells)": (
                    float(eligible["retention_fraction"].min()) if len(eligible) else np.nan
                ),
                "lowest-retention group": "" if lowest is None else str(lowest[name]),
                "group cells before/after": (
                    ""
                    if lowest is None
                    else f"{int(lowest['n_cells'])}/{int(lowest['cells_retained'])}"
                ),
                "maximum cells removed from one group": int(frame["cells_removed"].max()),
            }
        )

    multicomponent = pd.DataFrame(chemical_audit["preserved_multicomponent"])
    multicomponent_table = (
        markdown_table(multicomponent) if len(multicomponent) else "None."
    )
    q = qc_audit["pre_filter_quantiles"]
    quantile_rows = []
    for metric, values in q.items():
        quantile_rows.append({"metric": metric, **values})

    text = f"""# Ingest report: {DATASET_ID}

## Scope and result

This ingest uses the official processed UMI count matrix and official metadata for the
{EXPECTED_TREATED_COMPOUNDS}-compound sci-Plex 3 large screen ({GEO_ACCESSION}). It does not use FASTQs, rerun
quantification, perform differential expression, split the dataset, train a model, or evaluate a
model.

- Output: `data/processed/{DATASET_ID}.h5ad`
- Output SHA-256: `{output_sha256}`
- Final dimensions: {final_inventory['shape'][0]:,} cells x {final_inventory['shape'][1]:,} genes
- Validation: **{'PASS' if validation.ok else 'FAIL'}**
- Unresolved blockers: **None**

## Evidence and sources

{source_table}

The publication identifies sci-Plex 3 as the large screen of {EXPECTED_TREATED_COMPOUNDS} compounds in A549, K562, and
MCF7 cells and states that the primary 4-dose screen was collected 24 hours after treatment. The
deposited legal-condition table additionally identifies the A549 72-hour subset, which is retained.
The repository was audited at commit `{CODE_COMMIT}` ({CODE_URL}). The GEO record and processing
documentation were read at {GEO_URL}.

### Single-cell protocol and capture orientation

- Chemistry: {PROTOCOL_CONFIG['chemistry']}.
- Assay material: single nuclei; exonic and intronic strand-specific UMIs were included in the
  deposited gene counts.
- Capture orientation: **{PROTOCOL_CONFIG['capture_orientation']}**.
- Evidence: the sci-Plex paper states that polyadenylated hash oligos are captured together with
  endogenous mRNA by sci-RNA-seq3. The cited sci-RNA-seq3 protocol uses an anchored oligo-dT
  reverse-transcription primer, placing transcript capture at the poly(A)/3-prime end
  ({PROTOCOL_URL}).

## Input inspection

The count file is a gzip-compressed, headerless, tab-delimited coordinate matrix rather than a
Matrix Market file. Fields are 1-based `gene_index`, `cell_index`, and positive integer UMI count.
It is genes x cells on deposit and strictly cell-major ordered; ingest transposes it to cells x
genes. Full-stream validation found {matrix_audit['raw_coordinate_rows']:,} coordinate rows,
count range {matrix_audit['raw_count_min']} to {matrix_audit['raw_count_max']}, source dimensions
{matrix_audit['source_shape'][0]:,} genes x {matrix_audit['source_shape'][1]:,} cells, and exact
agreement between matrix column sums and deposited `n.umi`. The constructed pre-QC AnnData
inventory was: `{json.dumps(compact_anndata_inventory(initial_inventory), sort_keys=True)}`.

### Metadata column inventory

Every downloaded tabular metadata file was inspected before use. `hash_sample_sheet` was inspected
but not transformed because decoded assignments and their QC statistics are already in `pData`.

{metadata_table}

## Terminology and mappings

| Source term | Output | Interpretation |
| --- | --- | --- |
| cell annotation `cell` | `obs_names` | Unique combinatorial cell barcode |
| `dose` / `dose_character` | `dose_uM` | Deposited nM values divided by 1,000 |
| `time_point` | `timepoint_hr` | Elapsed treatment hours |
| `cell_type` | `cell_type` | A549, K562, or MCF7 cell line |
| `product_name` | `sm_name_original` | Exact cell-level source perturbation label |
| hash metadata `name` | `sm_name` | Trimmed official chemical label; all vehicles become `control` |
| `vehicle` and `catalog_number == {CONTROL_CATALOG_NUMBER}` | `control` | Required exact boolean control mapping |
| `replicate` | `batch` | Experimental replicate (`rep1` or `rep2`) |
| GENCODE v27 `protein_coding` | retained genes | Exact versioned Ensembl ID match |

Useful source fields are retained with clear provenance, including original plate/well/barcode
assignments, `source_replicate`, `source_total_umis`, `source_size_factor`, source pathway/target
annotations, hash UMI counts, enrichment ratios, p/q-values, catalog number, CAS number, canonical
SMILES, structure status, and InChIKey resolution source. Ambiguous original names are not silently
overwritten because `sm_name_original` is preserved.

## Identity and gene harmonization

- Deposited matrix cells: {identity_audit['cells_in_deposited_matrix']:,}
- Published hash-QC pass: {identity_audit['hash_pass']:,}
- Hash-QC failures: {identity_audit['hash_fail']:,}
- Hash-pass cells lacking any legal deposited condition: {identity_audit['hash_pass_without_legal_condition']:,}
- Cells retained before chemical/QC filtering: {identity_audit['identity_cells_retained']:,}
- Hash criteria: {identity_audit['criteria']}.
- Deposited genes: {gene_audit['deposited_genes']:,} ({gene_audit['human_genes']:,} human;
  {gene_audit['mouse_genes']:,} mouse).
- GENCODE v27 protein-coding IDs: {gene_audit['protein_coding_source_ids']:,}.
- Unique protein-coding symbols before expression QC:
  {gene_audit['unique_protein_coding_symbols_before_expression_qc']:,}.
- Symbols formed by summing multiple source Ensembl IDs:
  {gene_audit['symbols_aggregated_from_multiple_ids']:,}.
- Duplicate symbol coordinate rows summed: {matrix_audit['symbol_duplicate_coordinates_summed']:,}.

## Chemical harmonization

`standardize_smiles` was run on every deposited treated structure and `resolve_compounds` applied
the structure-first resolution order. Recognized small counterions were removed with the helper's
12-heavy-atom and one-half-parent size guards. Preserved mixtures are explicitly flagged in
`obs["multicomponent_structure"]`. The only malformed deposited SMILES was S4246; its exact
deposited CAS `{FALLBACK_CAS_NUMBER}` was resolved through the cached PubChem PUG response and the returned
structure was then desalted with the same RDKit procedure. No name-based fallback was used.

- Treated compounds: {chemical_audit['treated_compounds']}
- Direct deposited-structure statuses: `{chemical_audit['direct_structure_status']}`
- Final statuses: `{chemical_audit['final_resolution_status']}`
- Resolution sources: `{chemical_audit['resolution_sources']}`
- Unresolved treated compounds: `{chemical_loss['unresolved_compounds']}`
- Cells removed by `drop_unresolved_treatments`: {chemical_loss['cells_removed']:,}

### Preserved multicomponent structures

{multicomponent_table}

## Expression QC

QC was computed from `layers["counts"]` with `compute_qc_metrics`. Before filtering,
`summarize_qc` was run by batch, cell type, timepoint, dose, control status, perturbation, and the
batch-by-cell-type interaction.

### Pre-filter quantiles

{markdown_table(pd.DataFrame(quantile_rows))}

### Stratified distributions

{chr(10).join(group_tables)}

### Perturbation-level extremes checked

{markdown_table(perturbation_extremes)}

### Thresholds and losses

- Minimum total protein-coding counts: {qc_thresholds['min_total_counts']} ({qc_thresholds['derivation_total_counts']}).
- Minimum detected protein-coding genes: {qc_thresholds['min_genes_by_counts']} ({qc_thresholds['derivation_n_genes']}).
- Maximum mitochondrial percentage: {qc_thresholds['max_pct_counts_mt']}% ({qc_thresholds['derivation_pct_mt']}).
- Minimum cells expressing a gene: {qc_thresholds['min_cells_by_counts_per_gene']}
  ({qc_thresholds['derivation_gene_cells']}).
- Cells: {qc_audit['cells_before']:,} before, {qc_audit['cells_after']:,} after,
  {qc_audit['cells_removed']:,} removed.
- Genes: {qc_audit['genes_before']:,} before, {qc_audit['genes_after']:,} after,
  {qc_audit['genes_removed']:,} removed.
- No high-count cutoff was applied: high RNA content differs across these cell lines, and there was
  no defensible global upper boundary after stratification.

{markdown_table(pd.DataFrame(retention_rows))}

## Minimum condition size and target subset

The final subset was selected after expression QC with `select_condition_subset`. Conditions use
the exact key `{selection_audit['condition_columns']}`. Every eligible control was retained, and
treated cells were ranked by a stable SHA-256 hash of seed and cell identifier.

- Cells before condition filtering and subsetting: {selection_audit['cells_before']:,}
- Conditions before filtering: {selection_audit['conditions_before']:,}
- Minimum cells per condition: {selection_audit['minimum_condition_size']:,}
- Undersized conditions removed: {selection_audit['undersized_conditions_removed']:,}
- Cells removed with undersized conditions: {selection_audit['undersized_cells_removed']:,}
- Eligible conditions after the minimum-size filter: {selection_audit['eligible_conditions']:,}
- Eligible cells after the minimum-size filter: {selection_audit['eligible_cells']:,}
- Uniform treated-condition cap: {selection_audit['treated_condition_cap']}
- Control cells retained: {selection_audit['control_cells_retained']:,}
- Fixed random seed: {selection_audit['seed']}
- Final conditions: {selection_audit['conditions_after']:,}
- Final cells: {selection_audit['cells_after']:,}
- Smallest final condition: {selection_audit['minimum_final_condition_size']:,} cells
- Requested range: {selection_audit['target_min_cells']:,} to
  {selection_audit['max_cells_exclusive'] - 1:,} cells; target met:
  **{selection_audit['target_met']}**

## Final schema and validation

- `X` is `None`.
- `layers["counts"]` is sparse, finite, nonnegative, and integer-valued.
- Cells are rows; unique protein-coding gene symbols are columns.
- Required dose, time, cell identity, perturbation, full treated InChIKey, batch, and boolean
  control fields are present; only controls lack an InChIKey.
- `uns["single_cell_protocol"]` records chemistry, `{PROTOCOL_CONFIG['capture_orientation']}` orientation, and evidence.
- No `split` column exists.
- Reopened-file inventory:
  `{json.dumps(compact_anndata_inventory(final_inventory), sort_keys=True)}`.
- `validate_ingested_adata` errors: `{validation.errors}`.
- `validate_ingested_adata` warnings: `{validation.warnings}`.

## Unresolved blockers

None.
"""
    REPORT.write_text(text)


def main() -> None:
    log(f"Ingesting {DATASET_ID}")
    paths = download_and_verify_sources()
    frames = read_sources(paths)
    inventory = metadata_inventory(frames)

    resolved, chemical_audit = resolve_chemicals(frames["hash_metadata"], paths["pubchem_cas"])
    obs, identity_audit, chemical_loss = build_obs(frames["pdata"], resolved)
    gene_map, var, gene_audit = build_gene_map(
        frames["gene_annotations"], frames["gencode_bed"]
    )

    cell_position = pd.Series(np.arange(len(obs), dtype=np.int32), index=obs.index)
    cell_map = np.full(len(frames["cell_annotations"]), -1, dtype=np.int32)
    source_cell_position = pd.Series(
        np.arange(len(frames["cell_annotations"]), dtype=np.int32),
        index=frames["cell_annotations"]["cell"],
    )
    retained_source_positions = source_cell_position.loc[obs.index].to_numpy(dtype=np.int32)
    cell_map[retained_source_positions] = cell_position.to_numpy(dtype=np.int32)

    counts, matrix_audit = stream_counts(
        paths["counts"],
        n_source_genes=len(frames["gene_annotations"]),
        n_source_cells=len(frames["cell_annotations"]),
        source_total_umis=frames["pdata"]["n.umi"].to_numpy(dtype=np.int64),
        gene_map=gene_map,
        cell_map=cell_map,
        n_output_cells=len(obs),
        n_output_genes=len(var),
    )

    obs = categoricalize_strings(obs)
    var = categoricalize_strings(var)
    adata = ad.AnnData(X=None, obs=obs, var=var, shape=counts.shape)
    adata.layers["counts"] = counts
    adata.uns["single_cell_protocol"] = {
        "chemistry": str(PROTOCOL_CONFIG["chemistry"]),
        "capture_orientation": str(PROTOCOL_CONFIG["capture_orientation"]),
        "source": (
            f"{PUBLICATION_URL}; anchored oligo-dT sci-RNA-seq3 protocol: {PROTOCOL_URL}"
        ),
    }
    initial_inventory = inspect_anndata(adata)

    adata, qc_audit, qc_summaries, retention = apply_qc(adata)
    del counts
    gc.collect()
    selected, selection_audit = select_condition_subset(
        adata.obs,
        condition_columns=SUBSET_CONFIG["condition_columns"],
        minimum_condition_size=SUBSET_CONFIG["minimum_condition_size"],
        control_column=SUBSET_CONFIG["control_column"],
        max_cells_exclusive=SUBSET_CONFIG["max_cells_exclusive"],
        target_min_cells=SUBSET_CONFIG["target_min_cells"],
        seed=SUBSET_CONFIG["seed"],
    )
    adata = adata[selected].copy()
    adata.uns["ingest_audit"] = {
        "dataset_id": DATASET_ID,
        "geo_accession": GEO_ACCESSION,
        "code_commit": CODE_COMMIT,
        "identity_filter": identity_audit,
        "chemical_loss": chemical_loss,
        "gene_harmonization": gene_audit,
        "matrix": matrix_audit,
        "qc_filter": qc_audit,
        "condition_selection": selection_audit,
        "source_sha256": {key: source["sha256"] for key, source in SOURCE_FILES.items()},
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    log(f"Writing {OUTPUT}")
    adata.write_h5ad(OUTPUT, compression="gzip", compression_opts=4)
    del adata
    gc.collect()

    log("Reopening and validating output")
    reopened = ad.read_h5ad(OUTPUT)
    final_inventory = inspect_anndata(reopened)
    validation = validate_ingested_adata(reopened, INGEST_CONTRACT)
    validation.raise_for_errors()
    output_sha256 = sha256_file(OUTPUT)
    write_report(
        inventory=inventory,
        chemical_audit=chemical_audit,
        identity_audit=identity_audit,
        chemical_loss=chemical_loss,
        gene_audit=gene_audit,
        matrix_audit=matrix_audit,
        initial_inventory=initial_inventory,
        qc_audit=qc_audit,
        qc_summaries=qc_summaries,
        retention=retention,
        selection_audit=selection_audit,
        final_inventory=final_inventory,
        validation=validation,
        output_sha256=output_sha256,
    )
    log(
        f"Complete: {reopened.n_obs:,} cells x {reopened.n_vars:,} genes; "
        f"validation ok={validation.ok}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise
