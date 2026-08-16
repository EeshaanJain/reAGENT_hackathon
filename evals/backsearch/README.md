# Backsearch evaluation

Validates the literature search agent by asking: **if the papers we already
know are relevant had just been published, would our search find them — and
would it avoid finding irrelevant ones?**

## Setup

Gold labels come from the curated DB (`db/perturbation_model_papers.csv`):

- **positives** — papers relevant to the benchmark (per the relevance rule in
  the benchmark's `benchmark.yaml`, plus manual `force_positive` overrides)
- **negatives** — in-domain hard negatives (perturbation-modeling papers with
  no established chemical applicability)
- **related** — papers from `db/perturbation_benchmark_papers.csv` (benchmark
  papers, not methods): retrieving them counts as neither TP nor FP
- **unknown** — retrieved papers absent from both DBs: written out for human
  review, never silently counted as false positives

## Pipeline being evaluated

Two stages (both configured in the benchmark's `keywords.yaml`):

1. **Broad keyword search** — `paperclip search` over pmc,biorxiv,medrxiv with
   several queries covering the benchmark's subtopic vocabulary. Tuned for
   recall 1.0.
2. **LLM relevance filter** — `paperclip filter` with the benchmark's
   `relevance_filter` criterion, applied per query result set; a paper
   survives if any set keeps it. Restores precision.

## Corpus-coverage caveats (measured 2026-08)

- **Without `--all` (or an explicit `--year`/`--since`), `paperclip search`
  silently restricts to recent papers (~late 2024 onward) and returns nothing
  for arXiv.** An over-filtered search is indistinguishable from an empty
  corpus — always pass `--all` for backsearch, or `--since` for scheduled
  new-paper runs.
- With `--all`, coverage by source (probed by year): PMC ≥1980→present,
  arXiv ≥2006→present, bioRxiv 2014→present, medRxiv 2019→present.
  arXiv ingestion lags ~1–2 months (June 2026 present, July 2026 absent).
- arXiv papers have deterministic doc ids (`arx_<arxiv_id>`, constructible
  from `10.48550/arXiv.*` DOIs) but are absent from `lookup` and unreliable in
  `sql` — resolve them by constructing the id and verifying with `ls`.
- Some papers are still unreachable per-document (not ingested, or paywalled
  with no PMC/preprint version) — the eval reports them as coverage gaps and
  excludes them from retrieval metrics.

## Results (perturbation_prediction)

| run | queries | filter | recall | precision_db | F1_db |
|-----|---------|--------|--------|--------------|-------|
| baseline_v1 | 5 generic | no | 0.50 | 0.36 | 0.42 |
| v2_chem_focus | 7 chemical-heavy | no | 0.17 | 0.20 | 0.18 |
| v4_families | +method-family queries | no | 1.00 | 0.42 | 0.59 |
| v7/v9 (final) | 8 tuned | yes | **1.00** | 0.75–0.89 | **0.86–0.94** |

`precision_db` judges only papers with a known DB label. The LLM filter is
stochastic — precision varies a few points between runs; the range above is
from repeated runs of the same config.

Lessons that transfer to other benchmarks:

- semantic search is highly phrasing-sensitive: over-specific queries (v2)
  lose recall catastrophically; one query per subtopic vocabulary family
  (generative-model type, transfer setting, baseline methods, task phrasing)
  is what reached full recall
- broad search + LLM filter beats trying to make keywords precise
- match retrieved papers by normalized title, not just doc id (bioRxiv holds
  several versions of one paper under different ids)

## Reproducing

```bash
python3 scripts/extract_gold_set.py benchmarks/perturbation_prediction
python3 scripts/annotate_reachability.py benchmarks/perturbation_prediction
python3 scripts/run_backsearch.py benchmarks/perturbation_prediction <run_name> --filter
```

Results land in `evals/backsearch/results/<run_name>.json` (gitignored —
one-off run outputs stay out of git; final numbers are summarized here and in
the benchmark figure). Historical keyword-set versions are inlined in
`scripts/benchmark_retrieval.py`, which compares them and the filter
harnesses (paperclip filter vs claude judge per model) in one suite.
