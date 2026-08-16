#!/usr/bin/env python3
"""Benchmark suite for the literature search agent.

Phase 1 — keyword sets: run every query set in evals/backsearch/query_sets/
plus the benchmark's current keywords.yaml, search stage only (no filter),
identical n and sources, scored against the fully reviewed gold labels.

Phase 2 — filter harnesses: on the best keyword set (by search-stage F1_db,
ties broken by recall), compare relevance-filter backends:
  - none (search only)
  - paperclip filter (snippet-based LLM filter built into paperclip)
  - claude judge (abstract-based batch judge) with different models
Each stochastic backend runs `REPEATS` times to capture variance.

Writes incremental results to evals/backsearch/results/benchmark_suite.json
after every run, so partial progress survives interruption.

Usage:
    python3 scripts/benchmark_retrieval.py benchmarks/perturbation_prediction
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from litsearch.backsearch import run_backsearch  # noqa: E402

N = 30
SOURCES = "pmc,biorxiv,medrxiv,arxiv"
REPEATS = 3
JUDGE_MODELS = ["haiku", "sonnet", "opus"]


def slim(metrics: dict) -> dict:
    keep = ["eligible_positives", "retrieved_total", "recall", "precision_db",
            "precision_strict", "f1_db", "f1_strict",
            "true_positives", "false_negatives", "false_positives_known"]
    out = {k: metrics[k] for k in keep}
    out["n_unknown"] = len(metrics["unknown_retrieved"])
    out["n_related"] = len(metrics["related_retrieved"])
    return out


def main(benchmark_dir: str) -> None:
    bench = Path(benchmark_dir)
    repo_root = Path(__file__).resolve().parents[1]
    out_path = repo_root / "evals" / "backsearch" / "results" / "benchmark_suite.json"
    results: dict = {"config": {"n": N, "sources": SOURCES, "repeats": REPEATS},
                     "keyword_sets": {}, "filter_harnesses": {}}

    def save() -> None:
        out_path.write_text(json.dumps(results, indent=2))

    # ---- Phase 1: keyword sets ----
    # 5 sets uniformly spanning the tuning history (inlined so the historical
    # versions need not live in the repo): the very first baseline, two
    # intermediates, the 8-query tuned set, and the current keywords.
    query_sets: dict[str, list[str]] = {
        "v1_baseline": [
            "single-cell perturbation response prediction deep learning",
            "predicting transcriptional response to drug perturbation",
            "chemical perturbation prediction gene expression single-cell",
            "generative model cellular response small molecule",
            "out-of-distribution prediction unseen drug single-cell RNA-seq",
        ],
        "v2_chem_focus": [
            "predicting single-cell transcriptional response to drug perturbation",
            "chemical perturbation response prediction single-cell RNA-seq",
            "drug-induced gene expression change prediction deep learning",
            "in silico prediction of compound effect on gene expression",
            "generative model single-cell drug response prediction",
            "dose-dependent chemical perturbation gene expression model",
            "optimal transport single-cell perturbation response",
        ],
        "v3_families9": [
            "single-cell perturbation response prediction deep learning",
            "predicting transcriptional response to drug perturbation",
            "chemical perturbation prediction gene expression single-cell",
            "generative model cellular response small molecule",
            "out-of-distribution prediction unseen drug single-cell RNA-seq",
            "diffusion model predicting cellular responses to perturbations",
            "flow matching generative model single-cell perturbation",
            "transferring perturbation responses across cell contexts",
            "statistical baseline drug response prediction single-cell",
        ],
        "v4_tuned8": [
            "single-cell perturbation response prediction deep learning",
            "predicting transcriptional response to drug perturbation",
            "chemical perturbation prediction gene expression single-cell",
            "out-of-distribution prediction unseen drug single-cell RNA-seq",
            "diffusion model predicting cellular responses to perturbations",
            "flow matching generative model single-cell perturbation",
            "transferring perturbation responses across cell contexts",
            "statistical baseline drug response prediction single-cell",
        ],
    }
    current = yaml.safe_load((bench / "keywords.yaml").read_text())["search"]
    query_sets["current_keywords"] = current["queries"]

    for name, queries in query_sets.items():
        t0 = time.time()
        try:
            r = run_backsearch(bench, queries=queries, n=N, sources=SOURCES,
                               use_filter=False)
            entry = slim(r.metrics())
            entry.update(n_queries=len(queries), seconds=round(time.time() - t0, 1))
            results["keyword_sets"][name] = entry
            print(f"[keywords] {name}: recall={entry['recall']} "
                  f"f1_db={entry['f1_db']}", flush=True)
        except Exception:
            results["keyword_sets"][name] = {"error": traceback.format_exc()}
            print(f"[keywords] {name}: ERROR", flush=True)
        save()

    ok_sets = {k: v for k, v in results["keyword_sets"].items() if "f1_db" in v}
    best = max(ok_sets, key=lambda k: (ok_sets[k]["f1_db"], ok_sets[k]["recall"]))
    results["best_keyword_set"] = best
    best_queries = query_sets[best]
    print(f"\nbest keyword set: {best}\n", flush=True)
    save()

    # ---- Phase 2: filter harnesses on the best keyword set ----
    harnesses = [("none", {})]
    harnesses.append(("paperclip_filter",
                      dict(use_filter=True, filter_backend="paperclip",
                           filter_repeats=1)))
    for model in JUDGE_MODELS:
        harnesses.append((f"claude_judge_{model}",
                          dict(use_filter=True, filter_backend="claude",
                               judge_model=model)))

    for name, kwargs in harnesses:
        runs = []
        n_runs = 1 if name == "none" else REPEATS
        for i in range(n_runs):
            t0 = time.time()
            try:
                r = run_backsearch(bench, queries=best_queries, n=N,
                                   sources=SOURCES, **kwargs)
                entry = slim(r.metrics())
                entry["seconds"] = round(time.time() - t0, 1)
                runs.append(entry)
                print(f"[harness] {name} run {i + 1}/{n_runs}: "
                      f"recall={entry['recall']} precision_db={entry['precision_db']} "
                      f"f1_db={entry['f1_db']}", flush=True)
            except Exception:
                runs.append({"error": traceback.format_exc()})
                print(f"[harness] {name} run {i + 1}: ERROR", flush=True)
            results["filter_harnesses"][name] = runs
            save()

    print(f"\ndone -> {out_path}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
