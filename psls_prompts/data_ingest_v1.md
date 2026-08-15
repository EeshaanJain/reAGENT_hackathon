# Role

Ingest a published chemical single-cell perturbation dataset into a validated, analysis-ready AnnData object.

# Input / data sources

- Publication URL: https://www.science.org/doi/10.1126/science.aax6234
- Code URL: https://github.com/cole-trapnell-lab/sci-plex
- Local publication PDF: `data/Srivatsan et al. - 2020 - Massively multiplex chemical transcriptomics at single-cell resolution.pdf`

# Goal

Produce a reproducible dataset-specific ingest script, a harmonized H5AD file, and a concise ingest report.

Use only officially deposited count matrices and metadata.

Never process FASTQs or rerun expression quantification.

Do not perform differential expression, dataset splitting, model training, or evaluation.

# Environment

Use `uv` for all Python dependency management and execution.

Declare dependencies in `pyproject.toml` and update `uv.lock`.

Run Python commands, scripts, and tests with `uv run`.

# Evidence and exploration

Read the publication, code repository, and deposited-data documentation before transforming data.

Inspect every downloaded file before choosing an input.

Use `psls_tooling.inspect_anndata` to inventory AnnData inputs.

Determine matrix orientation, dimensions, sparsity, count location, and gene identifiers.

Summarize every metadata column by dtype, missingness, cardinality, and representative values.

Reconcile terminology across the publication, code, and deposited files.

Identify the single-cell assay chemistry and transcript-capture orientation.

Classify the orientation as 3′, 5′, full-length, or unknown, and cite the supporting evidence.

Preserve useful source metadata and document its meaning, provenance, and any renaming.

# Cell quality control

Use `psls_tooling.compute_qc_metrics` and `psls_tooling.summarize_qc` to evaluate QC distributions.

Choose cell and gene QC thresholds from this dataset's distributions.

Check QC behavior across batches, cell types, perturbations, doses, and controls before filtering.

# Gene harmonization

Filter for protein-coding genes.

# Chemical harmonization

Use `psls_tooling.standardize_smiles`, `psls_tooling.resolve_compounds`, and `psls_tooling.drop_unresolved_treatments` for chemical harmonization.

Resolve chemicals from supplied structures or exact identifiers before using name-based lookups.

Standardize treated compounds to full InChIKeys and record the resolution source.

Desalt only recognized small counterions.

Preserve and flag a multicomponent structure when a removed fragment has more than 12 heavy atoms or more than half the retained parent's heavy-atom count.

Drop unresolved treated compounds and report the compounds and cells removed.

# AnnData schema

- Represent single cells as rows and genes as columns.
- Use unique cell identifiers as `obs_names`.
- Set `X=None`.
- Store sparse, finite, nonnegative, integer-valued raw counts in `layers["counts"]`.
- Store the applied dose in numeric `obs["dose_uM"]`.
- Store the elapsed treatment time in numeric `obs["timepoint_hr"]`.
- Store the harmonized cell identity in `obs["cell_type"]`.
- Store the harmonized perturbation label in `obs["sm_name"]`.
- Map every valid control to `sm_name="control"`.
- Store the full standardized parent InChIKey in `obs["inchikey"]`.
- Store the experimental batch identifier in `obs["batch"]`.
- Store control status as a boolean in `obs["control"]`.
- Allow a missing InChIKey only when `control` is true.
- Preserve original perturbation labels in `obs["sm_name_original"]`.
- Use unique gene symbols as `var_names` and retain source gene identifiers in `var`.
- Store the assay chemistry, capture orientation (`"3prime"`, `"5prime"`, `"full_length"`, or `"unknown"`), and evidence source in `uns["single_cell_protocol"]`.
- Do not create a `split` column.

# Completion criteria

Write the ingest script to `data_ingest/<dataset_id>/ingest.py`.

Write the H5AD file to `data/processed/<dataset_id>.h5ad`.

Write the report to `data_ingest/<dataset_id>/ingest_report.md`.

The report must list source URLs and checksums, mappings, QC decisions, before-and-after dimensions, chemical-resolution losses, validation results, and unresolved blockers.

Reopen the H5AD file and run `psls_tooling.validate_ingested_adata` before finishing.

Stop and report a blocker if a required input is missing, no deposited count matrix exists, or a semantic ambiguity could change the biological meaning of the output.
