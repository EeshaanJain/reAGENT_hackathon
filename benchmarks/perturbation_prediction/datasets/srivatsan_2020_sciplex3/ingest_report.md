# Ingest report: srivatsan_2020_sciplex3

## Scope and result

This ingest uses the official processed UMI count matrix and official metadata for the
188-compound sci-Plex 3 large screen (GSM4150378). It does not use FASTQs, rerun
quantification, perform differential expression, split the dataset, train a model, or evaluate a
model.

- Output: `data/processed/srivatsan_2020_sciplex3.h5ad`
- Output SHA-256: `627bb0e35303daeb6fee4ada76dd0f7ebf7fb0757052cef42536b4a72f9c78ab`
- Final dimensions: 199,906 cells x 18,413 genes
- Validation: **PASS**
- Unresolved blockers: **None**

## Evidence and sources

| source | role | URL | SHA-256 |
| --- | --- | --- | --- |
| publication PDF | used: publication evidence | https://www.science.org/doi/10.1126/science.aax6234 | d6af84b4a72bf3b15f3fae037bdbe0e7b8901cf50f0b496a8e4ca1c00b6ee19e |
| GSM4150378_sciPlex3_A549_MCF7_K562_screen_UMI.count.matrix.gz | used: deposited UMI counts | https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM4150nnn/GSM4150378/suppl/GSM4150378_sciPlex3_A549_MCF7_K562_screen_UMI.count.matrix.gz | 7d632716aa6ed0fc1780996003d0abc440ff78340609bceaaa4c8ade9345d00a |
| GSM4150378_sciPlex3_A549_MCF7_K562_screen_cell.annotations.txt.gz | used: matrix cell order | https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM4150nnn/GSM4150378/suppl/GSM4150378_sciPlex3_A549_MCF7_K562_screen_cell.annotations.txt.gz | 5db11591747a49f07ceb90a070971d60816591911f1022171adba7d8d032f379 |
| GSM4150378_sciPlex3_A549_MCF7_K562_screen_gene.annotations.txt.gz | used: matrix gene order and symbols | https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM4150nnn/GSM4150378/suppl/GSM4150378_sciPlex3_A549_MCF7_K562_screen_gene.annotations.txt.gz | fbe43028cfb75dc5ebf383cbbbb100da6b51e7be8e2e74f6354f7c59b9fda7c2 |
| GSM4150378_sciPlex3_A549_MCF7_K562_hashTable_metadata.txt.gz | used: legal conditions, structures, and exact identifiers | https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM4150nnn/GSM4150378/suppl/GSM4150378_sciPlex3_A549_MCF7_K562_hashTable_metadata.txt.gz | 98a65191d343d149c5742cf6e7b734d403e853d165da800fa2daea41b978a2ff |
| GSM4150378_sciPlex3_pData.txt.gz | used: cell-level experimental and hash-QC metadata | https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM4150nnn/GSM4150378/suppl/GSM4150378_sciPlex3_pData.txt.gz | 860ba5c21846e2cfe97c39c805895982ef9db4b108cdf8b841a4a91be65024c2 |
| GSM4150378_sciPlex3_hashSampleSheet.txt.gz | inspected, not used: pData already contains decoded hash assignments | https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM4150nnn/GSM4150378/suppl/GSM4150378_sciPlex3_hashSampleSheet.txt.gz | ac66d0dfdcc3c170af9beafe2843d0250a10f753f7bf99968aafe7a2e7279084 |
| gencode.v27.transcripts.bed | used: publication-code GENCODE v27 gene biotypes | https://raw.githubusercontent.com/cole-trapnell-lab/sci-plex/079639c50811dd43a206a779ab2f0199a147c98f/large_screen/bin/gencode.v27.transcripts.bed | ebe49dde9655b025ba52c85f8dadd141c5d863c1a12e607ed4c2907c704094ca |
| pubchem_4548-34-9.json | used: exact-CAS fallback for one malformed deposited structure | https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/4548-34-9/property/IsomericSMILES,InChIKey/JSON | 7163dde8c6b3025ba7a10948b56c8c9c9f72ac8cc2da5b5f4f8df2f35863788f |

The publication identifies sci-Plex 3 as the large screen of 188 compounds in A549, K562, and
MCF7 cells and states that the primary 4-dose screen was collected 24 hours after treatment. The
deposited legal-condition table additionally identifies the A549 72-hour subset, which is retained.
The repository was audited at commit `079639c50811dd43a206a779ab2f0199a147c98f` (https://github.com/cole-trapnell-lab/sci-plex). The GEO record and processing
documentation were read at https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM4150378.

### Single-cell protocol and capture orientation

- Chemistry: sci-Plex nuclear hashing followed by three-level sci-RNA-seq (sci-RNA-seq3).
- Assay material: single nuclei; exonic and intronic strand-specific UMIs were included in the
  deposited gene counts.
- Capture orientation: **3prime**.
- Evidence: the sci-Plex paper states that polyadenylated hash oligos are captured together with
  endogenous mRNA by sci-RNA-seq3. The cited sci-RNA-seq3 protocol uses an anchored oligo-dT
  reverse-transcription primer, placing transcript capture at the poly(A)/3-prime end
  (https://pmc.ncbi.nlm.nih.gov/articles/PMC6434952/#S13).

## Input inspection

The count file is a gzip-compressed, headerless, tab-delimited coordinate matrix rather than a
Matrix Market file. Fields are 1-based `gene_index`, `cell_index`, and positive integer UMI count.
It is genes x cells on deposit and strictly cell-major ordered; ingest transposes it to cells x
genes. Full-stream validation found 1,007,419,688 coordinate rows,
count range 1 to 27373, source dimensions
110,983 genes x 799,317 cells, and exact
agreement between matrix column sums and deposited `n.umi`. The constructed pre-QC AnnData
inventory was: `{"X": {"present": false}, "layers": {"counts": {"dtype": "int32", "present": true, "shape": [649221, 19831], "sparse": true, "type": "csr_matrix"}}, "obs_columns": ["dose_uM", "timepoint_hr", "cell_type", "sm_name", "sm_name_original", "inchikey", "batch", "control", "source_sample", "source_size_factor", "source_total_umis", "hash_umis_W", "pval_W", "qval_W", "top_to_second_best_ratio_W", "top_oligo_W", "hash_umis_P", "pval_P", "qval_P", "top_to_second_best_ratio_P", "top_oligo_P", "rt_well", "lig_well", "pcr_well", "pcr_plate", "culture_plate", "rt_plate", "lig_plate", "Combo", "well_oligo", "plate_oligo", "source_replicate", "source_timepoint_hr", "drug_dose", "catalog_number", "source_vehicle", "dose_pattern", "source_dose_nM", "source_treatment", "pathway_level_1", "pathway_level_2", "source_product_name", "target", "pathway", "inchikey_source", "chemical_status", "canonical_smiles", "desalted", "removed_fragments", "parent_candidate_smiles", "parent_candidate_inchikey", "multicomponent_structure", "CAS.Number"], "obs_names_unique": true, "raw_X": {"present": false}, "shape": [649221, 19831], "uns_keys": ["single_cell_protocol"], "var_columns": ["source_gene_ids", "source_gene_id_count", "chromosomes", "gene_type", "gencode_release"], "var_names_unique": true}`.

### Metadata column inventory

Every downloaded tabular metadata file was inspected before use. `hash_sample_sheet` was inspected
but not transformed because decoded assignments and their QC statistics are already in `pData`.

| source | column | dtype | missing | cardinality | representative values |
| --- | --- | --- | --- | --- | --- |
| cell_annotations | cell | str | 0 | 799317 | A01_E09_RT_BC_100_Lig_BC_147, A01_E09_RT_BC_100_Lig_BC_186, A01_E09_RT_BC_100_Lig_BC_196 |
| cell_annotations | sample | str | 0 | 1 | Chem3_Screen2 |
| gene_annotations | id | str | 0 | 110983 | ENSG00000000003.14, ENSG00000000005.5, ENSG00000000419.12 |
| gene_annotations | gene_short_name | str | 0 | 109161 | TSPAN6, TNMD, DPM1 |
| hash_metadata | well_oligo | str | 0 | 864 | plate2_C6, plate2_C12, plate8_C6 |
| hash_metadata | plate_oligo | str | 0 | 52 | plate49, plate50, plate51 |
| hash_metadata | cell_type | str | 0 | 3 | A549, K562, MCF7 |
| hash_metadata | replicate | str | 0 | 2 | rep1, rep2 |
| hash_metadata | time_point | int64 | 0 | 2 | 72, 24 |
| hash_metadata | drug_dose | str | 0 | 768 | S0001_1, S0001_2, S0001_3 |
| hash_metadata | Combo | str | 0 | 4992 | plate2_C6plate49, plate2_C12plate49, plate8_C6plate50 |
| hash_metadata | catalog_number | str | 0 | 189 | S0000, S1001, S1002 |
| hash_metadata | vehicle | bool | 0 | 2 | True, False |
| hash_metadata | dose_pattern | int64 | 0 | 4 | 1, 2, 3 |
| hash_metadata | dose_character | int64 | 0 | 5 | 0, 10, 100 |
| hash_metadata | dose | int64 | 0 | 5 | 0, 10, 100 |
| hash_metadata | treatment | str | 0 | 189 | S0000, S1001, S1002 |
| hash_metadata | CAS.Number | str | 104 | 189 | <NA>, 923564-51-6, 852808-04-9 |
| hash_metadata | M.w. | float64 | 104 | 186 | <NA>, 974.61, 813.43 |
| hash_metadata | name | str | 104 | 189 | <NA>, Navitoclax (ABT-263), ABT-737 |
| hash_metadata | SMILES | str | 104 | 189 | <NA>, CC1(CCC(=C(C1)CN2CCN(CC2)C3=CC=C(C=C3)C(=O)NS(=O)(=O)C4=CC(=C(C=C4)N[C@H](CCN5CCOCC5)CSC6=CC=CC=C6)S(=O)(=O)C(F)(F)F)C7=CC=C(C=C7)Cl)C, CN(C)CCC(CSC1=CC=CC=C1)NC2=CC=C(C=C2[N+]([O-])=O)[S](=O)(=O)NC(=O)C3=CC=C(C=C3)N4CCN(CC4)CC5=C(C=CC=C5)C6=CC=C(Cl)C=C6 |
| pdata | cell | str | 0 | 799317 | A01_E09_RT_BC_100_Lig_BC_147, A01_E09_RT_BC_100_Lig_BC_186, A01_E09_RT_BC_100_Lig_BC_196 |
| pdata | sample | str | 0 | 1 | Chem3_Screen2 |
| pdata | Size_Factor | float64 | 0 | 19725 | 1.75110435800108, 0.904865559359369, 1.11390845363545 |
| pdata | n.umi | int64 | 0 | 19725 | 2957, 1528, 1881 |
| pdata | hash_umis_W | float64 | 718 | 3169 | 79.0, 117.0, 197.0 |
| pdata | pval_W | float64 | 718 | 77492 | 0.0, 2.04850169072806e-211, 1.2591402273536799e-250 |
| pdata | qval_W | float64 | 718 | 64653 | 0.0, 4.97785910846918e-209, 3.36190440703434e-248 |
| pdata | top_to_second_best_ratio_W | float64 | 718 | 794907 | 5.66505810656352, 69.6512739785954, 64.33309993246 |
| pdata | top_oligo_W | str | 790 | 865 | plate6_A9, plate8_H3, plate3_C2 |
| pdata | hash_umis_P | float64 | 746 | 3224 | 194.0, 111.0, 253.0 |
| pdata | pval_P | float64 | 746 | 321294 | 0.0, 1.50765770523116e-274, 1.0608444371022601e-23 |
| pdata | qval_P | float64 | 746 | 300787 | 0.0, 1.63279329476535e-271, 1.84586932055794e-21 |
| pdata | top_to_second_best_ratio_P | float64 | 746 | 714556 | 274.556876355147, 31.0108953734034, 180.994808376123 |
| pdata | top_oligo_P | str | 751 | 53 | plate44, plate46, plate41 |
| pdata | rt_well | int64 | 0 | 384 | 100, 101, 102 |
| pdata | lig_well | int64 | 0 | 383 | 147, 186, 196 |
| pdata | pcr_well | str | 0 | 96 | A01, A02, A03 |
| pdata | pcr_plate | str | 0 | 2 | E09, F10 |
| pdata | culture_plate | str | 751 | 53 | plate44, plate46, plate41 |
| pdata | rt_plate | int64 | 0 | 4 | 2, 1, 3 |
| pdata | lig_plate | int64 | 0 | 4 | 2, 3, 4 |
| pdata | Combo | str | 0 | 25639 | plate6_A9plate44, plate8_H3plate46, plate3_C2plate41 |
| pdata | well_oligo | str | 36522 | 865 | plate6_A9, plate8_H3, plate3_C2 |
| pdata | plate_oligo | str | 36522 | 53 | plate44, plate46, plate41 |
| pdata | cell_type | str | 36522 | 4 | MCF7, A549, K562 |
| pdata | replicate | str | 36522 | 3 | rep2, rep1, <NA> |
| pdata | time_point | float64 | 36522 | 3 | 24.0, 72.0, <NA> |
| pdata | drug_dose | str | 36522 | 769 | S2718_1, S1143_4, S1090_2 |
| pdata | catalog_number | str | 36522 | 190 | S2718, S1143, S1090 |
| pdata | vehicle | bool | 0 | 2 | False, True |
| pdata | dose_pattern | float64 | 36522 | 5 | 1.0, 4.0, 2.0 |
| pdata | dose_character | float64 | 36522 | 6 | 10000.0, 10.0, 1000.0 |
| pdata | dose | float64 | 36522 | 6 | 10000.0, 10.0, 1000.0 |
| pdata | treatment | str | 36522 | 190 | S2718, S1143, S1090 |
| pdata | pathway_level_1 | str | 36522 | 18 | Tyrosine kinase signaling, Epigenetic regulation, Cell cycle regulation |
| pdata | pathway_level_2 | str | 36522 | 56 | RTK activity, Histone deacetylation, Aurora kinase activity |
| pdata | product_name | str | 36522 | 190 | TAK-901, AG-490 (Tyrphostin B42), Abexinostat (PCI-24781) |
| pdata | target | str | 36522 | 88 | Aurora Kinase, EGFR, HDAC |
| pdata | pathway | str | 36522 | 22 | Cell Cycle, Protein Tyrosine Kinase, Cytoskeletal Signaling |
| hash_sample_sheet | hash_id | str | 0 | 916 | plate2_A1, plate2_B1, plate2_C1 |
| hash_sample_sheet | sequence | str | 0 | 916 | CGGTCAAGAA, CGCTCCTAAC, ATCCATGACT |
| hash_sample_sheet | n_hashes | int64 | 0 | 2 | 1, 2 |
| gencode_bed | chrom | str | 0 | 47 | GL000009.2, GL000194.1, GL000195.1 |
| gencode_bed | start | int64 | 0 | 182230 | 56140, 53590, 53594 |
| gencode_bed | end | int64 | 0 | 182407 | 58376, 115018, 115055 |
| gencode_bed | transcript_id | str | 0 | 200468 | ENST00000618686.1, ENST00000613230.1, ENST00000400754.4 |
| gencode_bed | score | int64 | 0 | 1 | 255 |
| gencode_bed | strand | str | 0 | 2 | -, + |
| gencode_bed | gene_id | str | 0 | 58347 | ENSG00000278704.1, ENSG00000277400.1, ENSG00000274847.1 |
| gencode_bed | gene_symbol | str | 0 | 56648 | BX004987.1, AC145212.2, AC145212.1 |
| gencode_bed | gene_type | str | 0 | 46 | protein_coding, misc_RNA, snRNA |

## Terminology and mappings

| Source term | Output | Interpretation |
| --- | --- | --- |
| cell annotation `cell` | `obs_names` | Unique combinatorial cell barcode |
| `dose` / `dose_character` | `dose_uM` | Deposited nM values divided by 1,000 |
| `time_point` | `timepoint_hr` | Elapsed treatment hours |
| `cell_type` | `cell_type` | A549, K562, or MCF7 cell line |
| `product_name` | `sm_name_original` | Exact cell-level source perturbation label |
| hash metadata `name` | `sm_name` | Trimmed official chemical label; all vehicles become `control` |
| `vehicle` and `catalog_number == S0000` | `control` | Required exact boolean control mapping |
| `replicate` | `batch` | Experimental replicate (`rep1` or `rep2`) |
| GENCODE v27 `protein_coding` | retained genes | Exact versioned Ensembl ID match |

Useful source fields are retained with clear provenance, including original plate/well/barcode
assignments, `source_replicate`, `source_total_umis`, `source_size_factor`, source pathway/target
annotations, hash UMI counts, enrichment ratios, p/q-values, catalog number, CAS number, canonical
SMILES, structure status, and InChIKey resolution source. Ambiguous original names are not silently
overwritten because `sm_name_original` is preserved.

## Identity and gene harmonization

- Deposited matrix cells: 799,317
- Published hash-QC pass: 649,341
- Hash-QC failures: 149,976
- Hash-pass cells lacking any legal deposited condition: 120
- Cells retained before chemical/QC filtering: 649,221
- Hash criteria: both top hashes present; >=5 UMIs on each hash; >=5-fold top/second ratio on each hash; rt_well != 1; complete legal condition metadata.
- Deposited genes: 110,983 (58,347 human;
  52,636 mouse).
- GENCODE v27 protein-coding IDs: 19,865.
- Unique protein-coding symbols before expression QC:
  19,831.
- Symbols formed by summing multiple source Ensembl IDs:
  34.
- Duplicate symbol coordinate rows summed: 8,339.

## Chemical harmonization

`standardize_smiles` was run on every deposited treated structure and `resolve_compounds` applied
the structure-first resolution order. Recognized small counterions were removed with the helper's
12-heavy-atom and one-half-parent size guards. Preserved mixtures are explicitly flagged in
`obs["multicomponent_structure"]`. The only malformed deposited SMILES was S4246; its exact
deposited CAS `4548-34-9` was resolved through the cached PubChem PUG response and the returned
structure was then desalted with the same RDKit procedure. No name-based fallback was used.

- Treated compounds: 188
- Direct deposited-structure statuses: `{'single_component': 159, 'desalted': 25, 'multicomponent_preserved': 4}`
- Final statuses: `{'single_component': 159, 'desalted': 26, 'multicomponent_preserved': 3}`
- Resolution sources: `{'smiles_rdkit': 187, 'pubchem_exact_cas_smiles_rdkit': 1}`
- Unresolved treated compounds: `[]`
- Cells removed by `drop_unresolved_treatments`: 0

### Preserved multicomponent structures

| catalog_number | name | chemical_status | canonical_smiles | inchikey |
| --- | --- | --- | --- | --- |
| S1703 | Divalproex Sodium | multicomponent_preserved | CCCC(CCC)C(=O)O.CCCC(CCC)C(=O)[O-].[Na+] | MSRILKIQRXUYCT-UHFFFAOYSA-M |
| S1776 | Toremifene Citrate | multicomponent_preserved | CN(C)CCOc1ccc(/C(=C(/CCCl)c2ccccc2)c2ccccc2)cc1.O=C(O)CC(O)(CC(=O)O)C(=O)O | IWEQQRMGNVVKQW-OQKDUQJOSA-N |
| S5001 | Tofacitinib (CP-690550) Citrate | multicomponent_preserved | C[C@@H]1CCN(C(=O)CC#N)C[C@@H]1N(C)c1ncnc2[nH]ccc12.O=C(O)CC(O)(CC(=O)O)C(=O)O | SYIKUFDOYJFGBQ-YLAFAASESA-N |

## Expression QC

QC was computed from `layers["counts"]` with `compute_qc_metrics`. Before filtering,
`summarize_qc` was run by batch, cell type, timepoint, dose, control status, perturbation, and the
batch-by-cell-type interaction.

### Pre-filter quantiles

| metric | 0 | 0.001 | 0.01 | 0.05 | 0.5 | 0.95 | 0.99 | 0.999 | 1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| total_counts | 27.0 | 286.0 | 393.0 | 465.0 | 1225.0 | 6133.0 | 11679.0 | 22058.560000000056 | 72603.0 |
| n_genes_by_counts | 16.0 | 214.0 | 325.0 | 390.0 | 910.0 | 3067.0 | 4538.0 | 6211.340000000084 | 9308.0 |
| pct_counts_mt | 0.0 | 0.0 | 0.3766478342749529 | 0.9450171821305842 | 3.9735099337748343 | 9.456928838951312 | 13.398004612991484 | 24.61491506245675 | 97.28260869565217 |

### Stratified distributions

#### By batch

| batch | n_cells | total_counts_median | total_counts_q05 | total_counts_q95 | n_genes_median | n_genes_q05 | n_genes_q95 | pct_counts_mt_median | pct_counts_mt_q95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rep1 | 302538 | 1098.0 | 457.0 | 5228.149999999965 | 831.0 | 384.0 | 2758.0 | 3.8095238095238093 | 9.75991450642258 |
| rep2 | 346683 | 1354.0 | 475.0 | 6838.0 | 988.0 | 397.0 | 3295.0 | 4.091653027823241 | 9.1792656587473 |
#### By cell_type

| cell_type | n_cells | total_counts_median | total_counts_q05 | total_counts_q95 | n_genes_median | n_genes_q05 | n_genes_q95 | pct_counts_mt_median | pct_counts_mt_q95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A549 | 210458 | 997.0 | 446.0 | 3319.149999999994 | 768.0 | 374.0 | 2011.0 | 3.9898670044331856 | 9.368650743442076 |
| K562 | 146752 | 826.0 | 436.0 | 2375.0 | 661.0 | 368.0 | 1578.0 | 2.9254223320972392 | 8.42410381197856 |
| MCF7 | 292011 | 1934.0 | 565.0 | 8523.0 | 1304.0 | 457.0 | 3782.0 | 4.535147392290249 | 9.800715209697687 |
#### By timepoint_hr

| timepoint_hr | n_cells | total_counts_median | total_counts_q05 | total_counts_q95 | n_genes_median | n_genes_q05 | n_genes_q95 | pct_counts_mt_median | pct_counts_mt_q95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 24.0 | 581778 | 1252.0 | 467.0 | 6356.0 | 926.0 | 392.0 | 3140.0 | 4.062742707806811 | 9.517720459040971 |
| 72.0 | 67443 | 1029.0 | 447.0 | 3938.899999999994 | 788.0 | 377.0 | 2265.0 | 3.3553355335533555 | 8.65573668238682 |
#### By dose_uM

| dose_uM | n_cells | total_counts_median | total_counts_q05 | total_counts_q95 | n_genes_median | n_genes_q05 | n_genes_q95 | pct_counts_mt_median | pct_counts_mt_q95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.0 | 14637 | 1185.0 | 462.0 | 5940.799999999985 | 892.0 | 390.0 | 3025.199999999999 | 3.6842105263157894 | 8.912549684695788 |
| 0.01 | 170640 | 1233.0 | 467.0 | 6282.049999999988 | 916.0 | 392.0 | 3117.0 | 3.9156273393692 | 9.163924233354697 |
| 0.1 | 165754 | 1206.0 | 464.0 | 6035.0 | 898.0 | 389.0 | 3032.350000000006 | 3.983006753537844 | 9.359993403155384 |
| 1.0 | 159466 | 1219.0 | 463.0 | 6107.0 | 905.0 | 389.0 | 3058.0 | 3.976435935198822 | 9.457051824448861 |
| 10.0 | 138724 | 1249.5 | 464.0 | 6102.850000000006 | 924.0 | 389.0 | 3059.0 | 4.0685224839400425 | 9.947368421052632 |
#### By control

| control | n_cells | total_counts_median | total_counts_q05 | total_counts_q95 | n_genes_median | n_genes_q05 | n_genes_q95 | pct_counts_mt_median | pct_counts_mt_q95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| False | 634584 | 1226.0 | 465.0 | 6136.849999999977 | 910.0 | 390.0 | 3068.0 | 3.9807222992417195 | 9.466702429788576 |
| True | 14637 | 1185.0 | 462.0 | 5940.799999999985 | 892.0 | 390.0 | 3025.199999999999 | 3.6842105263157894 | 8.912549684695788 |

### Perturbation-level extremes checked

| metric | extreme | sm_name | n_cells | value |
| --- | --- | --- | --- | --- |
| total_counts_median | lowest | YM155 (Sepantronium Bromide) | 770 | 831.5 |
| total_counts_median | lowest | (+)-JQ1 | 4805 | 948.0 |
| total_counts_median | lowest | Flavopiridol HCl | 1407 | 1023.0 |
| total_counts_median | highest | AT9283 | 2380 | 1924.0 |
| total_counts_median | highest | GSK1070916 | 2502 | 1895.5 |
| total_counts_median | highest | AMG-900 | 2710 | 1830.0 |
| n_genes_median | lowest | YM155 (Sepantronium Bromide) | 770 | 659.0 |
| n_genes_median | lowest | (+)-JQ1 | 4805 | 723.0 |
| n_genes_median | lowest | Flavopiridol HCl | 1407 | 765.0 |
| n_genes_median | highest | AT9283 | 2380 | 1317.0 |
| n_genes_median | highest | GSK1070916 | 2502 | 1268.0 |
| n_genes_median | highest | AMG-900 | 2710 | 1244.0 |
| pct_counts_mt_median | lowest | YM155 (Sepantronium Bromide) | 770 | 3.0548092943957226 |
| pct_counts_mt_median | lowest | Navitoclax (ABT-263) | 3030 | 3.147107781939243 |
| pct_counts_mt_median | lowest | Mercaptopurine (6-MP) | 3066 | 3.1604135691312822 |
| pct_counts_mt_median | highest | Flavopiridol HCl | 1407 | 5.377906976744186 |
| pct_counts_mt_median | highest | CUDC-907 | 2417 | 5.11600237953599 |
| pct_counts_mt_median | highest | Quisinostat (JNJ-26481585) 2HCl | 2662 | 5.054548339746896 |

### Thresholds and losses

- Minimum total protein-coding counts: 275 (rounded down 0.1st percentile, floor 100).
- Minimum detected protein-coding genes: 210 (rounded down 0.1st percentile, floor 50).
- Maximum mitochondrial percentage: 20.0% (rounded up 99.9th percentile, bounded to [5, 20] percent).
- Minimum cells expressing a gene: 10
  (lower sparse tail; require detection in at least 10 cells).
- Cells: 649,221 before, 647,840 after,
  1,381 removed.
- Genes: 19,831 before, 18,413 after,
  1,418 removed.
- No high-count cutoff was applied: high RNA content differs across these cell lines, and there was
  no defensible global upper boundary after stratification.

| stratum | groups checked | minimum retention (groups >=50 cells) | lowest-retention group | group cells before/after | maximum cells removed from one group |
| --- | --- | --- | --- | --- | --- |
| batch | 2 | 0.997798623643972 | rep1 | 302538/301872 | 715 |
| cell_type | 3 | 0.9958160706498037 | K562 | 146752/146138 | 614 |
| timepoint_hr | 2 | 0.9978342254261935 | 24.0 | 581778/580518 | 1260 |
| dose_uM | 5 | 0.9969075286179753 | 10.0 | 138724/138295 | 429 |
| control | 2 | 0.9978584395446466 | False | 634584/633225 | 1359 |
| sm_name | 189 | 0.9361179361179361 | Epothilone A | 1221/1143 | 78 |

## Minimum condition size and target subset

The final subset was selected after expression QC with `select_condition_subset`. A condition is
the exact combination of `sm_name`, `timepoint_hr`, `dose_uM`, and `cell_type`. Every eligible
control was retained, and treated cells were ranked by a stable SHA-256 hash of seed and cell ID.

- Cells before condition filtering and subsetting: 647,840
- Conditions before filtering: 2,448
- Minimum cells per condition: 30
- Undersized conditions removed: 22
- Cells removed with undersized conditions: 303
- Eligible conditions after the minimum-size filter: 2,426
- Eligible cells after the minimum-size filter: 647,537
- Uniform treated-condition cap: 77
- Control cells retained: 14,615
- Fixed random seed: 42
- Final conditions: 2,426
- Final cells: 199,906
- Smallest final condition: 34 cells
- Requested range: 195,000 to 199,999 cells; target met: **True**

## Final schema and validation

- `X` is `None`.
- `layers["counts"]` is sparse, finite, nonnegative, and integer-valued.
- Cells are rows; unique protein-coding gene symbols are columns.
- Required dose, time, cell identity, perturbation, full treated InChIKey, batch, and boolean
  control fields are present; only controls lack an InChIKey.
- `uns["single_cell_protocol"]` records chemistry, `3prime` orientation, and evidence.
- No `split` column exists.
- Reopened-file inventory:
  `{"X": {"present": false}, "layers": {"counts": {"dtype": "int32", "present": true, "shape": [199906, 18413], "sparse": true, "type": "csr_matrix"}}, "obs_columns": ["dose_uM", "timepoint_hr", "cell_type", "sm_name", "sm_name_original", "inchikey", "batch", "control", "source_sample", "source_size_factor", "source_total_umis", "hash_umis_W", "pval_W", "qval_W", "top_to_second_best_ratio_W", "top_oligo_W", "hash_umis_P", "pval_P", "qval_P", "top_to_second_best_ratio_P", "top_oligo_P", "rt_well", "lig_well", "pcr_well", "pcr_plate", "culture_plate", "rt_plate", "lig_plate", "Combo", "well_oligo", "plate_oligo", "source_replicate", "source_timepoint_hr", "drug_dose", "catalog_number", "source_vehicle", "dose_pattern", "source_dose_nM", "source_treatment", "pathway_level_1", "pathway_level_2", "source_product_name", "target", "pathway", "inchikey_source", "chemical_status", "canonical_smiles", "desalted", "removed_fragments", "parent_candidate_smiles", "parent_candidate_inchikey", "multicomponent_structure", "CAS.Number", "total_counts", "n_genes_by_counts", "pct_counts_mt"], "obs_names_unique": true, "raw_X": {"present": false}, "shape": [199906, 18413], "uns_keys": ["ingest_audit", "single_cell_protocol"], "var_columns": ["source_gene_ids", "source_gene_id_count", "chromosomes", "gene_type", "gencode_release", "total_counts", "n_cells_by_counts", "mt"], "var_names_unique": true}`.
- `validate_ingested_adata` errors: `[]`.
- `validate_ingested_adata` warnings: `[]`.

## Unresolved blockers

None.
