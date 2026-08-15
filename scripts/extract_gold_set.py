#!/usr/bin/env python3
"""Extract a gold-standard paper set for a benchmark from a curated papers CSV.

Benchmark-agnostic: the relevance rule (which columns mark a paper as relevant)
comes from the benchmark's benchmark.yaml. Writes gold_papers.csv (positives)
and negative_papers.csv (in-domain hard negatives) into <benchmark>/gold/,
resolving each paper to a paperclip doc id where possible.

Usage:
    python3 scripts/extract_gold_set.py benchmarks/perturbation_prediction
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from litsearch.paperclip_client import resolve_doc_id  # noqa: E402

KEEP_COLUMNS = [
    "model_name", "paper_title", "bibtex_key", "publication_year", "venue",
    "doi", "doi_url", "paper_url", "github_repositories", "summary",
]


def main(benchmark_dir: str) -> None:
    bench = Path(benchmark_dir)
    config = yaml.safe_load((bench / "benchmark.yaml").read_text())
    gold_cfg = config["gold"]
    repo_root = Path(__file__).resolve().parents[1]

    with open(repo_root / gold_cfg["source_csv"]) as f:
        rows = list(csv.DictReader(f))

    negative_values = set(gold_cfg["negative_values"])

    force_positive = set(gold_cfg.get("force_positive", []))

    def is_positive(row: dict) -> bool:
        if row.get("model_name") in force_positive:
            return True
        return any(
            row.get(col, "") not in negative_values
            for col in gold_cfg["relevance_columns"]
        )

    out_dir = bench / "gold"
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {"positive": 0, "negative": 0, "resolved": 0}

    outputs = {
        "positive": open(out_dir / "gold_papers.csv", "w", newline=""),
        "negative": open(out_dir / "negative_papers.csv", "w", newline=""),
    }
    writers = {}
    fieldnames = [c for c in KEEP_COLUMNS if c in rows[0]] + ["paperclip_doc_id"]
    for label, fh in outputs.items():
        writers[label] = csv.DictWriter(fh, fieldnames=fieldnames)
        writers[label].writeheader()

    doc_id_overrides = gold_cfg.get("doc_id_overrides", {})

    for row in rows:
        label = "positive" if is_positive(row) else "negative"
        doc_id = (doc_id_overrides.get(row.get("model_name"))
                  or resolve_doc_id(row.get("doi"), row.get("paper_title")))
        out_row = {c: row.get(c, "") for c in fieldnames if c != "paperclip_doc_id"}
        out_row["paperclip_doc_id"] = doc_id or ""
        writers[label].writerow(out_row)
        counts[label] += 1
        counts["resolved"] += bool(doc_id)
        print(f"{label:8s} {'OK ' if doc_id else '-- '} {row.get('model_name', row.get('paper_title'))[:40]}")

    for fh in outputs.values():
        fh.close()
    print(f"\npositives={counts['positive']} negatives={counts['negative']} "
          f"resolved_in_corpus={counts['resolved']}/{len(rows)}")


if __name__ == "__main__":
    main(sys.argv[1])
