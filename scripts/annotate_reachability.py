#!/usr/bin/env python3
"""Annotate gold CSVs with whether each paper is reachable via semantic search.

A paper can be in the corpus (readable by doc id) yet absent from the semantic
search index (observed: the index covers roughly late-2024 onward). Such papers
can never be retrieved by any keyword query, so the backsearch eval must treat
them as coverage gaps rather than query failures.

Reachability probe: search the paper's own exact title; if the paper (by doc id
or normalized title) appears in the top results, it is reachable.

Usage:
    python3 scripts/annotate_reachability.py benchmarks/perturbation_prediction
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from litsearch.backsearch import norm_title  # noqa: E402
from litsearch.paperclip_client import search  # noqa: E402


def annotate(csv_path: Path) -> None:
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    if "search_reachable" not in fieldnames:
        fieldnames.append("search_reachable")

    for row in rows:
        if not row["paperclip_doc_id"]:
            row["search_reachable"] = "False"
            continue
        hits, _ = search(row["paper_title"], n=5)
        reachable = any(
            h.doc_id == row["paperclip_doc_id"]
            or norm_title(h.title) == norm_title(row["paper_title"])
            for h in hits
        )
        row["search_reachable"] = str(reachable)
        name = row.get("model_name") or row["paper_title"]
        print(f"{'OK ' if reachable else '-- '} {name[:50]}")

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    bench = Path(sys.argv[1])
    for name in ("gold_papers.csv", "negative_papers.csv"):
        print(f"--- {name}")
        annotate(bench / "gold" / name)
