# Role

Ingest a published chemical single-cell perturbation dataset into a validated, analysis-ready AnnData object.

# Input / data sources

- Publication URL: https://www.biorxiv.org/content/10.64898/2026.06.09.731197v1
- Code URL: https://huggingface.co/datasets/tahoebio/EmeraldBay
- Local publication PDF: data/2026.06.09.731197.full.pdf

# Goal

Produce a reproducible dataset-specific ingest script, a harmonized H5AD file, and a concise ingest report.

Use only officially deposited count matrices and metadata.

Never process FASTQs or rerun expression quantification.

Do not perform differential expression, dataset splitting, model training, or evaluation.

## Target subset constraint

**IMPORTANT:** Keep the final H5AD strictly below **200,000 cells**, including controls. Retain all eligible cells if they fit; otherwise, target **195,000-199,999 cells** while maximizing useful biological and experimental coverage. If the complete eligible population contains fewer than **190,000 cells**, retain it and document the shortfall; this alone does not invalidate the dataset.

- During metadata-only preflight, define the eligible population from complete officially deposited metadata, never from a preview or capped index. Honor task-specific constraints; identify the relevant biological and technical axes; and resolve the selected identities, treatments, controls, samples, and technical strata before reading expression data.
- Keep only single-compound perturbations and the matched vehicle controls required for the retained treatments. Derive control-matching strata from the documented study design.
- Define and document a biological sampling-condition key, normally including perturbation, dose, cell identity, timepoint, and any other axis that changes the condition.
- When category selection is required, choose categories that preserve useful coverage and provide enough eligible cells to approach the target.
- Apply expression QC before final subsampling, and allow enough provisional cells for anticipated QC losses. Use a fixed random seed and the same cap for every eligible non-control condition; retain all cells in conditions below the cap without reallocating the unused quota.
- Record available and retained cell counts for every condition.
- Filter at the source and use format-appropriate selective access when supported. If the physical layout prevents selective transfer, make one streamed pass over the required expression payload, retain and persist only eligible cells, record bytes transferred, and avoid a second full pass. Do not substitute a partial-viewer result when the complete payload is needed to reach the target.

# Environment

Use `uv` for all Python dependency management and execution.

Declare dependencies in `pyproject.toml` and update `uv.lock`.

Run Python commands, scripts, and tests with `uv run`.

# Execution strategy

Complete a metadata-only preflight before reading the entire count matrix. Require all of the following to pass:

- Required source columns exist.
- Cell, sample, and gene identifiers are unique where required, normalized consistently, and aligned by both set and order wherever the matrix format depends on annotation order.
- Control, dose, timepoint, batch, and cell-type mappings are complete and unambiguous.
- Gene mapping, protein-coding selection, and duplicate-symbol aggregation are finalized.
- Chemical resolution is complete and anticipated compound and cell losses are known.
- Output column names and dtypes, including all derived flags, are frozen.
- The expression-QC strategy, including its deterministic formulas, floors, caps, and grouping checks, is declared.

For large matrices, use bounded samples to establish the physical format, index base, orientation, count semantics, and parser behavior. Perform the complete integrity audit in the same streamed pass used to construct the sparse matrix; do not run a separate full-file scan unless the construction pass cannot provide the required evidence. Never densify the complete matrix.

Treat explicit matrix headers or matching annotation tables as authoritative for matrix dimensions. Require every observed coordinate to be in bounds, but do not require every annotated row or column to occur among the nonzero coordinates.

Validate all required and derived output-column dtypes before beginning the full matrix build. Persist audit results separately from matrix construction. Generate the report from those audit results and the reopened H5AD so that report-only changes do not trigger matrix reconstruction.

# Evidence and exploration

Read the publication, code repository, and deposited-data documentation before transforming data.

Inventory every downloaded file before choosing an input. Inspect bounded samples of large matrix files during preflight and reserve their complete integrity scan for the streamed construction pass.

Use `psls_tooling.inspect_anndata` to inventory AnnData inputs.

Determine matrix orientation, dimensions, sparsity, count location, and gene identifiers.

Summarize every metadata column by dtype, missingness, cardinality, and representative values.

Reconcile terminology across the publication, code, and deposited files.

Identify the single-cell assay chemistry and transcript-capture orientation.

Classify the orientation as 3′, 5′, full-length, or unknown, and cite the supporting evidence.

Preserve useful source metadata and document its meaning, provenance, and any renaming.

# Cell quality control

Use `psls_tooling.compute_qc_metrics` and `psls_tooling.summarize_qc` to evaluate QC distributions.

Distinguish source-defined identity and QC filters from newly introduced expression QC.

Choose global, deterministic cell and gene QC rules before the final build and record the exact formula, quantile, floor, and cap used by each rule. Do not choose separate thresholds by perturbation, dose, cell type, or batch.

Because treatment toxicity can be biological signal, use broad expression-QC thresholds intended to remove technical failures. Report group-level retention rather than adjusting thresholds to normalize retention across groups.

Check QC behavior across batches, cell types, perturbations, doses, and controls before filtering.

Maintain a loss ledger with cells and genes removed at every applicable stage: source-defined QC, invalid or incomplete metadata, unresolved chemistry, protein-coding filtering, expression QC, and gene-detection filtering.

## Minimum condition size

Unless the task explicitly overrides it, set `MIN_CELLS_PER_CONDITION = 30`.

Define a condition for this filter as the exact combination of harmonized perturbation, time, dose, and cell type: `obs["sm_name"]` × `obs["timepoint_hr"]` × `obs["dose_uM"]` × `obs["cell_type"]`. Do not add batch or other technical fields to this condition key. Apply the same definition to treated and control cells.

After metadata, chemical, and expression-QC filtering, remove every condition with fewer than `MIN_CELLS_PER_CONDITION` cells. Remove the complete condition rather than individual cells. Perform this filtering before final cap-based subsampling, and ensure that subsampling does not reduce any retained condition below the minimum. Recompute condition counts on the final H5AD and fail validation if any retained condition has fewer than the minimum.

Record the threshold, condition key, pre-filter counts, dropped conditions and cells, and final per-condition counts in the audit artifacts and ingest report. Include condition-size removals as a distinct stage in the loss ledger.

# Gene harmonization

Use a gene annotation release compatible with the deposited genome build and gene identifiers, preferring the exact version used by the authors. Pin and report its source, revision, and checksum.

Filter for protein-coding genes. When multiple source gene identifiers map to one gene symbol, sum their counts and retain the complete ordered list of source identifiers in `var`. Never make gene symbols unique by appending arbitrary suffixes.

# Chemical harmonization

Use `psls_tooling.standardize_smiles`, `psls_tooling.resolve_compounds`, and `psls_tooling.drop_unresolved_treatments` for chemical harmonization.

Resolve chemicals from supplied structures or exact identifiers before using name-based lookups.

Standardize treated compounds to full InChIKeys and record the resolution source.

Cache every external registry response used for chemical resolution. Record the query value, identifier namespace, endpoint, retrieval date, response checksum, and selected record. The ingest must replay from cached responses without requiring a live name lookup.

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

The report must list source URLs and checksums, mappings, QC decisions, the minimum-condition-size audit, the complete loss ledger, before-and-after dimensions, chemical-resolution losses, validation results, and unresolved blockers.

Reopen the H5AD file and run `psls_tooling.validate_ingested_adata` before finishing.

Treat the upper bound as an acceptance criterion: validation fails if the reopened H5AD contains 200,000 cells or more. If it contains fewer than 190,000 cells, verify and report that the complete eligible source population could not reach the requested range.

Stop and report a blocker if a required input is missing, no deposited count matrix exists, or a semantic ambiguity could change the biological meaning of the output.
