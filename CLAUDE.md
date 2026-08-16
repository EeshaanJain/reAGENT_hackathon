# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

This is an agentic-hackathon project (reAGENT): build an **automated agentic system for maintaining Open Problems benchmarks** (openproblems.bio) so that leaderboards for computational methods in single-cell biology stay up to date without manual curation. Today a new method takes months to get independently evaluated; the goal is agent-based integration into Open Problems within days of a paper appearing.

## Core design rule

**Agent code must be benchmark-agnostic.** Nothing in agent logic may be hardcoded to a specific benchmark. All benchmark-specific information (task description, keywords, existing methods/datasets/metrics, next-step instructions) lives in per-benchmark configuration under that benchmark's directory in this repo. Adding support for a new benchmark must mean adding a config, not changing code.

## Agent pipeline vision

Three pipelines, all following the pattern *literature agent → verifier/analysis agent → contributor agent*:

- **New methods**: a literature agent finds a relevant new paper and extracts metadata plus the code link; a verifier agent reproduces the paper's core results; a contributor agent opens a PR to Open Problems adding the method.
- **New metrics**: same flow, plus a comparison stage: does the new metric correlate with existing ones, does it distinguish edge cases, where does it disagree with other metrics, is it worth adding? End result is a report and (if warranted) a PR.
- **New datasets**: literature agent finds the dataset; a data-analysis agent runs QC, reprocessing, and train/test splitting; a contributor agent opens a PR with the dataset.

## Literature search agent (current focus)

Requirements:

1. **Benchmark awareness**: know which benchmarks exist in Open Problems, what tasks they cover, and which methods, datasets, and metrics each already includes. This information is scraped from the Open Problems GitHub organization (https://github.com/openproblems-bio) and cached in this repo; there must be tools to refresh it.
2. **Scheduled search**: run on a configurable cadence (daily / weekly / monthly). Each benchmark directory contains the list of search keywords for that benchmark.
3. **Extraction**: for each relevant paper found, extract:
   - paper link and full text
   - the methods section
   - preprocessing / input assumptions
   - code link
   - a description of what to do next (e.g. "Integrate this method into Open Problems benchmark X")

Paper search and full-text access go through the `paperclip` CLI (`.claude/skills/paperclip/`) — run `paperclip skill` first to load its documentation.

**Validation approach (backsearch)**: the literature agent is evaluated against a gold-standard set of known-relevant papers (see `db/`): if those papers were new, would the agent find them, and would it avoid finding irrelevant ones? Keyword sets and search parameters are tuned to maximize F1 against the gold set, and the same setup serves as a benchmark for comparing harnesses/models on this retrieval task. If a search result sounds relevant but is missing from the gold DB, do not silently treat it as a false positive — flag it to the user for review. See `evals/backsearch/README.md` for methodology, corpus-coverage caveats (always search with `--all` — the default window silently drops older papers and all of arXiv), and tuning lessons.

**Retrieval architecture**: broad keyword queries tuned for 100% recall (one query per subtopic vocabulary family), followed by an LLM relevance filter (`paperclip filter`) for precision. What matters is end-to-end F1, not keyword precision.

Workflow commands (benchmark dir as argument — works for any benchmark):

```bash
python3 scripts/extract_gold_set.py benchmarks/<id>      # gold set from db CSV per benchmark.yaml rule
python3 scripts/annotate_reachability.py benchmarks/<id> # mark papers reachable via search index
python3 scripts/run_backsearch.py benchmarks/<id> <run_name> --filter  # eval, writes evals/backsearch/results/
python3 scripts/run_search.py benchmarks/<id> [--since YYYY-MM-DD]     # production search -> <id>/results/latest_search.json
```

The production output (`<benchmark>/results/latest_search.json`, format
documented in `scripts/run_search.py`) is one record per retrieved paper —
doc id, title, DOI, URL (always present), source, matched queries, filter
verdict, gold label — and IS committed: downstream agents and other people
consume it.

## Repository contents

- `db/` — curated CSVs of papers (models and benchmarks) with bibliographic metadata, GitHub links, and per-task capability annotations (`task_*_status` columns with values like `not_established`, `scope_only`, `explicitly_evaluated`; paired `task_*_evidence` text). Used as gold-standard data for validating the literature agent. The `local_*_path` / `metrics-db/` columns are provenance pointers to an upstream pipeline **not present in this repo** — don't try to read those paths.
- Per-benchmark directories (configs, keywords, cached Open Problems state) — benchmark-specific details belong here, not in code.

## Open Problems technical structure (for contributor agents)

Open Problems task repos (github.com/openproblems-bio/task_*) are built on **Viash** (component management) and **Nextflow** (workflow orchestration):

- Components live under `src/`: `methods/`, `control_methods/`, `metrics/`, `process_dataset/`; each component has a Viash config plus a script.
- Data is exchanged as **AnnData `.h5ad`** files with task-specific required layers/slots.
- Typical commands in a task repo: `scripts/download_resources.sh`, `viash ns build --parallel --setup cachedbuild`, `viash ns test --parallel`, `scripts/run_benchmark.sh`; new methods follow `scripts/add_a_method.sh`.

## Conventions

- Code in this repo is Python (`.gitignore` is already set up for it).
- During the hackathon: no full-scale benchmark runs; work on data subsets.
- **Never commit one-off artifacts**: throwaway scripts (plot generation,
  one-time data munging), non-final results, eval run outputs, intermediate
  tuning files, or data dumps. Put throwaway scripts in the scratchpad, keep
  run outputs gitignored, and record final numbers in READMEs/figures. Only
  reusable code, configs, gold data, and documentation belong in git.
