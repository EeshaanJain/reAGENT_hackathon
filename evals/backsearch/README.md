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

These papers can never be retrieved regardless of keywords; the eval reports
them as coverage gaps and excludes them from retrieval metrics:

- paperclip's full-text corpus is **PMC + bioRxiv + medRxiv only. arXiv is
  listed in the docs but its index is empty** — 9/24 gold positives are
  arXiv-only, plus 1 paywalled (Cell) and 1 with an unresolvable DOI.
- the semantic search index only covers papers from roughly **late 2024
  onward**: 4 older gold positives (Biolord, CPA, CellOT, scVIDR) are readable
  by doc id but invisible to every search query.

Net eligible gold set: 9 positives, 22 hard negatives.

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

Results land in `evals/backsearch/results/<run_name>.json`; alternative query
sets tried during tuning live in `evals/backsearch/query_sets/`.
