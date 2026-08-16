#!/usr/bin/env python3
"""Run the backsearch evaluation for a benchmark and print/save metrics.

Usage:
    python3 scripts/run_backsearch.py benchmarks/perturbation_prediction [run_name]
Optional flags:
    --queries-file FILE   YAML file with an alternative `search:` block to test
    -n INT                override results_per_query
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from litsearch.backsearch import run_backsearch, save_result  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("benchmark_dir")
    ap.add_argument("run_name", nargs="?", default="default")
    ap.add_argument("--queries-file")
    ap.add_argument("-n", type=int, default=None)
    ap.add_argument("--filter", action="store_true",
                    help="apply the benchmark's LLM relevance_filter stage")
    args = ap.parse_args()

    queries = None
    if args.queries_file:
        queries = yaml.safe_load(Path(args.queries_file).read_text())["search"]["queries"]

    result = run_backsearch(args.benchmark_dir, queries=queries, n=args.n,
                            use_filter=args.filter)
    metrics = result.metrics()

    repo_root = Path(__file__).resolve().parents[1]
    out = repo_root / "evals" / "backsearch" / "results" / f"{args.run_name}.json"
    save_result(result, out, {
        "benchmark": args.benchmark_dir,
        "queries": result.queries,
        "n": args.n,
        "filter": args.filter,
    })
    print(json.dumps(metrics, indent=2))
    print(f"\nsaved to {out}", file=sys.stderr)
    if metrics["coverage_gaps"]:
        print(f"note: {len(metrics['coverage_gaps'])} gold papers cannot be "
              f"retrieved by any query (corpus/index coverage gap, not a "
              f"search failure)", file=sys.stderr)


if __name__ == "__main__":
    main()
