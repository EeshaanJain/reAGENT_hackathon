#!/usr/bin/env python3
"""Run the literature search for a benchmark and emit structured per-paper
records — the agent's production output, consumed by downstream stages
(verifier/contributor agents) and by humans reviewing candidates.

Benchmark-agnostic: queries, sources, and the relevance-filter criterion come
from the benchmark's keywords.yaml; gold labels (if present) enrich the output.

Output JSON shape (one record per retrieved paper):
    {
      "run": {date, benchmark, queries, sources, n, filter_backend,
              judge_model},
      "papers": [{
        "doc_id":          paperclip document id (PMC…, bio_…, arx_…),
        "title":           paper title (from meta.json when available),
        "doi":             DOI if known,
        "url":             best link (DOI url, PMC page, or arXiv abs page),
        "source":          pmc | biorxiv | medrxiv | arxiv,
        "pub_date":        publication date from meta.json,
        "paperclip_path":  /papers/<doc_id>/ (full text, sections, figures),
        "best_rank":       best rank across matching queries,
        "matched_queries": which keyword queries retrieved it,
        "kept_by_filter":  survived the LLM relevance filter,
        "gold_label":      positive | negative | related | unknown
                           (vs the benchmark's gold/reviewed labels),
        "gold_name":       model/paper name in the gold data, if labeled
      }]
    }

Usage:
    python3 scripts/run_search.py benchmarks/perturbation_prediction \
        [-o output.json] [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from litsearch.backsearch import load_labeled, norm_title  # noqa: E402
from litsearch.claude_judge import judge  # noqa: E402
from litsearch.paperclip_client import get_meta, search  # noqa: E402


def paper_url(doc_id: str, doi: str | None) -> str:
    """Always returns a URL: DOI when known, else a source page derived from
    the doc id, else paperclip's public citation page as last resort."""
    if doi:
        return f"https://doi.org/{doi}"
    if doc_id.startswith("PMC"):
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{doc_id}/"
    if doc_id.startswith("arx_"):
        return f"https://arxiv.org/abs/{doc_id[4:]}"
    return f"https://paperclip.gxl.ai/citations/papers/{doc_id}"


def load_gold_labels(bench: Path) -> tuple[dict[str, tuple[str, str]],
                                           dict[str, tuple[str, str]]]:
    """Return ({doc_id: (label, name)}, {norm_title: (label, name)})."""
    by_id: dict[str, tuple[str, str]] = {}
    by_title: dict[str, tuple[str, str]] = {}
    for fname, label in (("gold_papers.csv", "positive"),
                         ("negative_papers.csv", "negative")):
        path = bench / "gold" / fname
        if not path.exists():
            continue
        ids, _, titles = load_labeled(path)
        for doc_id, name in ids.items():
            by_id[doc_id] = (label, name)
        for nt, name in titles.items():
            by_title[nt] = (label, name)
    reviewed = bench / "gold" / "reviewed_papers.csv"
    if reviewed.exists():
        with open(reviewed) as f:
            for row in csv.DictReader(f):
                entry = (row["verdict"], row["name"])
                if row["paperclip_doc_id"]:
                    by_id[row["paperclip_doc_id"]] = entry
                by_title[norm_title(row["paper_title"])] = entry
    return by_id, by_title


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("benchmark_dir")
    ap.add_argument("-o", "--output", default=None,
                    help="output path (default: <benchmark>/results/"
                         "latest_search.json)")
    ap.add_argument("--since", default=None,
                    help="only papers since this date (scheduled-run mode); "
                         "default searches the full corpus")
    ap.add_argument("-k", "--keywords", default="keywords.yaml",
                    help="keywords file inside the benchmark dir; a benchmark "
                         "may ship several search configs (e.g. keywords.yaml "
                         "for methods, keywords_datasets.yaml for datasets)")
    args = ap.parse_args()

    bench = Path(args.benchmark_dir)
    kw_path = bench / args.keywords
    kw = yaml.safe_load(kw_path.read_text())["search"]
    queries = kw["queries"]
    sources = kw.get("sources", "pmc,biorxiv,medrxiv,arxiv")
    n = kw.get("results_per_query", 20)
    criterion = kw.get("relevance_filter")

    retrieved: dict[str, dict] = {}
    hits_by_id = {}
    for q in queries:
        hits, _ = search(q, sources=sources, n=n, since=args.since)
        for h in hits:
            hits_by_id[h.doc_id] = h
            rec = retrieved.setdefault(h.doc_id, {"best_rank": h.rank,
                                                  "matched_queries": []})
            rec["matched_queries"].append(q)
            rec["best_rank"] = min(rec["best_rank"], h.rank)
    print(f"retrieved {len(retrieved)} unique papers "
          f"from {len(queries)} queries", file=sys.stderr)

    kept: set[str] = set()
    if criterion:
        kept = judge(hits_by_id, criterion,
                     model=kw.get("judge_model"))
        print(f"filter kept {len(kept)}/{len(retrieved)}", file=sys.stderr)

    by_id, by_title = load_gold_labels(bench)
    papers = []
    for doc_id, rec in retrieved.items():
        meta = get_meta(doc_id)
        title = meta.get("title") or hits_by_id[doc_id].title
        doi = meta.get("doi")
        label, name = by_id.get(doc_id) or by_title.get(norm_title(title)) \
            or ("unknown", None)
        papers.append({
            "doc_id": doc_id,
            "title": " ".join(title.split()),
            "doi": doi,
            "url": paper_url(doc_id, doi),
            "source": meta.get("source", ""),
            "pub_date": meta.get("pub_date", ""),
            "paperclip_path": f"/papers/{doc_id}/",
            "best_rank": rec["best_rank"],
            "matched_queries": rec["matched_queries"],
            "kept_by_filter": doc_id in kept,
            "gold_label": label,
            "gold_name": name,
        })
    papers.sort(key=lambda p: (not p["kept_by_filter"], p["best_rank"]))

    out = {
        "run": {
            "date": date.today().isoformat(),
            "benchmark": bench.name,
            "queries": queries,
            "sources": sources,
            "n_per_query": n,
            "since": args.since,
            "keywords_file": args.keywords,
            "filter_backend": kw.get("filter_backend", "paperclip"),
            "judge_model": kw.get("judge_model"),
        },
        "papers": papers,
    }
    # Non-default keywords files get their own output, e.g.
    # keywords_datasets.yaml -> latest_search_datasets.json.
    suffix = kw_path.stem.removeprefix("keywords").lstrip("_")
    default_name = f"latest_search{'_' + suffix if suffix else ''}.json"
    out_path = Path(args.output) if args.output else (
        bench / "results" / default_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    csv_path = write_csv(out, out_path.with_suffix(".csv"))
    print(f"wrote {len(papers)} papers -> {out_path} and {csv_path}",
          file=sys.stderr)


def write_csv(out: dict, csv_path: Path) -> Path:
    """Flatten the search output to CSV (matched_queries joined with '; ')."""
    fields = ["doc_id", "title", "doi", "url", "source", "pub_date",
              "paperclip_path", "best_rank", "matched_queries",
              "kept_by_filter", "gold_label", "gold_name"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for p in out["papers"]:
            row = dict(p)
            row["matched_queries"] = "; ".join(p["matched_queries"])
            w.writerow(row)
    return csv_path


if __name__ == "__main__":
    main()
