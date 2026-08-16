#!/usr/bin/env python3
"""Benchmark suite for the literature search agent. Benchmark-agnostic.

Phase 1 — keyword sets: run every query-set YAML found in --query-sets-dir
(each file: `search: {queries: [...]}`) plus the benchmark's current
keywords.yaml, search stage only (no filter), identical n and sources, scored
against the reviewed gold labels.

Phase 2 — filter harnesses: on the best keyword set (by search-stage F1_db,
ties broken by recall), compare relevance-filter backends:
  - none (search only)
  - paperclip filter (snippet-based LLM filter built into paperclip)
  - claude judge (abstract-based batch judge) with each --judge-models model
Each stochastic backend runs --repeats times to capture variance.

Query-set files and results are one-off artifacts and stay out of git
(gitignored); final numbers belong in the eval README / figures.

Writes incremental results to evals/backsearch/results/benchmark_suite.json
after every run, so partial progress survives interruption.

Usage:
    python3 scripts/benchmark_retrieval.py benchmarks/perturbation_prediction \
        [--query-sets-dir evals/backsearch/query_sets] [-n 30] [--repeats 3] \
        [--sources pmc,biorxiv,medrxiv,arxiv] [--judge-models haiku,sonnet,opus]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from litsearch.backsearch import run_backsearch  # noqa: E402


def slim(metrics: dict) -> dict:
    keep = ["eligible_positives", "retrieved_total", "recall", "precision_db",
            "precision_strict", "f1_db", "f1_strict",
            "true_positives", "false_negatives", "false_positives_known"]
    out = {k: metrics[k] for k in keep}
    out["n_unknown"] = len(metrics["unknown_retrieved"])
    out["n_related"] = len(metrics["related_retrieved"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("benchmark_dir")
    ap.add_argument("--query-sets-dir", default="evals/backsearch/query_sets",
                    help="directory of query-set YAMLs to compare (gitignored)")
    ap.add_argument("-n", type=int, default=30, help="results per query")
    ap.add_argument("--repeats", type=int, default=3,
                    help="runs per stochastic filter harness")
    ap.add_argument("--sources", default="pmc,biorxiv,medrxiv,arxiv")
    ap.add_argument("--judge-models", default="haiku,sonnet,opus",
                    help="comma-separated model list for the claude judge")
    args = ap.parse_args()

    bench = Path(args.benchmark_dir)
    repo_root = Path(__file__).resolve().parents[1]
    out_path = (repo_root / "evals" / "backsearch" / "results"
                / "benchmark_suite.json")
    results: dict = {
        "config": {"n": args.n, "sources": args.sources,
                   "repeats": args.repeats},
        "keyword_sets": {}, "filter_harnesses": {},
    }

    def save() -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2))

    # ---- Phase 1: keyword sets ----
    query_sets: dict[str, list[str]] = {}
    for f in sorted(Path(args.query_sets_dir).glob("*.yaml")):
        query_sets[f.stem] = yaml.safe_load(f.read_text())["search"]["queries"]
    current = yaml.safe_load((bench / "keywords.yaml").read_text())["search"]
    query_sets["current_keywords"] = current["queries"]

    for name, queries in query_sets.items():
        t0 = time.time()
        try:
            r = run_backsearch(bench, queries=queries, n=args.n,
                               sources=args.sources, use_filter=False)
            entry = slim(r.metrics())
            entry.update(n_queries=len(queries),
                         seconds=round(time.time() - t0, 1))
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
    for model in args.judge_models.split(","):
        harnesses.append((f"claude_judge_{model}",
                          dict(use_filter=True, filter_backend="claude",
                               judge_model=model, filter_repeats=1)))

    for name, kwargs in harnesses:
        runs = []
        n_runs = 1 if name == "none" else args.repeats
        for i in range(n_runs):
            t0 = time.time()
            try:
                r = run_backsearch(bench, queries=best_queries, n=args.n,
                                   sources=args.sources, **kwargs)
                entry = slim(r.metrics())
                entry["seconds"] = round(time.time() - t0, 1)
                runs.append(entry)
                print(f"[harness] {name} run {i + 1}/{n_runs}: "
                      f"recall={entry['recall']} "
                      f"precision_db={entry['precision_db']} "
                      f"f1_db={entry['f1_db']}", flush=True)
            except Exception:
                runs.append({"error": traceback.format_exc()})
                print(f"[harness] {name} run {i + 1}: ERROR", flush=True)
            results["filter_harnesses"][name] = runs
            save()

    print(f"\ndone -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
