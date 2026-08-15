"""Backsearch evaluation: would our keyword search find the gold papers?

Benchmark-agnostic. Given a benchmark directory containing keywords.yaml and
gold/{gold_papers,negative_papers}.csv (produced by scripts/extract_gold_set.py),
runs each query through paperclip and scores retrieval against the gold set.

Scoring:
- Only papers that exist in the paperclip corpus (have a doc id) are eligible;
  the rest are corpus-coverage gaps, reported separately.
- recall        = retrieved gold positives / eligible gold positives
- precision_db  = TP / (TP + retrieved known negatives)   <- primary, judged
                  only against papers with a known DB label
- precision_strict = TP / all retrieved                    <- lower bound: every
                  unknown retrieved paper counted as irrelevant
- Unknown retrieved papers are NOT silently treated as false positives: they
  are written out for human review (they may be relevant papers missing from
  the gold DB).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .paperclip_client import SearchHit, llm_filter, merge_sets, search


def norm_title(title: str) -> str:
    """Normalize a title for fuzzy identity matching (bioRxiv often holds
    several versions of one paper under different doc ids)."""
    return "".join(c for c in title.lower() if c.isalnum())


@dataclass
class BacksearchResult:
    queries: list[str]
    eligible_positives: dict[str, str]  # doc_id -> name
    eligible_negatives: dict[str, str]
    coverage_gaps: list[str]            # gold positives not in corpus
    positive_titles: dict[str, str] = field(default_factory=dict)  # norm_title -> name
    negative_titles: dict[str, str] = field(default_factory=dict)
    related_titles: dict[str, str] = field(default_factory=dict)
    retrieved: dict[str, SearchHit] = field(default_factory=dict)
    per_query: dict[str, list[str]] = field(default_factory=dict)

    def _label(self, doc_id: str) -> tuple[str, str | None]:
        """Return (label, gold_name), label in positive/negative/related/unknown.
        Matches by doc id first, then by normalized title."""
        if doc_id in self.eligible_positives:
            return "positive", self.eligible_positives[doc_id]
        if doc_id in self.eligible_negatives:
            return "negative", self.eligible_negatives[doc_id]
        nt = norm_title(self.retrieved[doc_id].title)
        if nt in self.positive_titles:
            return "positive", self.positive_titles[nt]
        if nt in self.negative_titles:
            return "negative", self.negative_titles[nt]
        if nt in self.related_titles:
            return "related", self.related_titles[nt]
        return "unknown", None

    def metrics(self) -> dict:
        tp_names, fp_names, related_names, unknown = set(), set(), set(), set()
        for doc_id in self.retrieved:
            label, name = self._label(doc_id)
            if label == "positive":
                tp_names.add(name)
            elif label == "negative":
                fp_names.add(name)
            elif label == "related":
                related_names.add(name)
            else:
                unknown.add(doc_id)
        retrieved_ids = set(self.retrieved)
        all_pos_names = set(self.eligible_positives.values())
        tp = tp_names
        fn = all_pos_names - tp_names
        fp_known = fp_names
        n_pos = len(all_pos_names)
        recall = len(tp) / n_pos if n_pos else 0.0
        precision_db = len(tp) / (len(tp) + len(fp_known)) if tp or fp_known else 0.0
        precision_strict = len(tp) / (len(tp) + len(fp_known) + len(unknown)) \
            if retrieved_ids else 0.0
        f1_db = (2 * precision_db * recall / (precision_db + recall)
                 if precision_db + recall else 0.0)
        f1_strict = (2 * precision_strict * recall / (precision_strict + recall)
                     if precision_strict + recall else 0.0)
        return {
            "eligible_positives": n_pos,
            "eligible_negatives": len(set(self.eligible_negatives.values())),
            "coverage_gaps": self.coverage_gaps,
            "retrieved_total": len(retrieved_ids),
            "true_positives": sorted(tp),
            "false_negatives": sorted(fn),
            "false_positives_known": sorted(fp_known),
            "related_retrieved": sorted(related_names),
            "unknown_retrieved": {d: self.retrieved[d].title for d in sorted(unknown)},
            "recall": round(recall, 3),
            "precision_db": round(precision_db, 3),
            "precision_strict": round(precision_strict, 3),
            "f1_db": round(f1_db, 3),
            "f1_strict": round(f1_strict, 3),
        }


def load_labeled(csv_path: Path) -> tuple[dict[str, str], list[str], dict[str, str]]:
    """Return ({doc_id: name} for search-reachable papers, [gap names],
    {norm_title: name}).

    A paper is eligible only if it is reachable via the semantic search index
    (column `search_reachable`, produced by scripts/annotate_reachability.py);
    papers missing from the corpus or the index go into the gaps list — no
    keyword query can ever retrieve them.
    """
    with_id, gaps, titles = {}, [], {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            name = row.get("model_name") or row["paper_title"]
            reachable = row.get("search_reachable", "True") == "True"
            if row["paperclip_doc_id"] and reachable:
                with_id[row["paperclip_doc_id"]] = name
                titles[norm_title(row["paper_title"])] = name
            else:
                reason = "not_in_corpus" if not row["paperclip_doc_id"] else "not_in_search_index"
                gaps.append(f"{name} ({reason})")
    return with_id, gaps, titles


def run_backsearch(benchmark_dir: str | Path,
                   queries: list[str] | None = None,
                   n: int | None = None,
                   sources: str | None = None,
                   use_filter: bool = False,
                   filter_criterion: str | None = None) -> BacksearchResult:
    """Two-stage retrieval: broad keyword search, then (optionally) paperclip's
    LLM relevance filter with the benchmark's `relevance_filter` criterion."""
    bench = Path(benchmark_dir)
    kw = yaml.safe_load((bench / "keywords.yaml").read_text())["search"]
    queries = queries if queries is not None else kw["queries"]
    n = n or kw.get("results_per_query", 10)
    sources = sources or kw.get("sources", "pmc,biorxiv,medrxiv")
    filter_criterion = filter_criterion or kw.get("relevance_filter")

    positives, pos_gaps, pos_titles = load_labeled(bench / "gold" / "gold_papers.csv")
    negatives, _, neg_titles = load_labeled(bench / "gold" / "negative_papers.csv")

    related_titles: dict[str, str] = {}
    bench_cfg = yaml.safe_load((bench / "benchmark.yaml").read_text())
    related_csv = bench_cfg.get("gold", {}).get("related_csv")
    if related_csv:
        repo_root = bench.resolve().parents[1]
        with open(repo_root / related_csv) as f:
            for row in csv.DictReader(f):
                related_titles[norm_title(row["paper_title"])] = row["paper_title"]

    # Team-reviewed verdicts on papers found by the agent but absent from the
    # source DB (plus duplicate-version aliases of DB papers).
    reviewed = bench / "gold" / "reviewed_papers.csv"
    if reviewed.exists():
        with open(reviewed) as f:
            for row in csv.DictReader(f):
                target = {"positive": (positives, pos_titles),
                          "negative": (negatives, neg_titles),
                          "related": (None, related_titles)}[row["verdict"]]
                ids, titles = target
                if ids is not None and row["paperclip_doc_id"]:
                    ids[row["paperclip_doc_id"]] = row["name"]
                titles[norm_title(row["paper_title"])] = row["name"]

    result = BacksearchResult(queries, positives, negatives, pos_gaps,
                              pos_titles, neg_titles, related_titles)
    set_ids = []
    for q in queries:
        hits, set_id = search(q, sources=sources, n=n, return_set_id=True)
        result.per_query[q] = [h.doc_id for h in hits]
        if set_id:
            set_ids.append(set_id)
        for h in hits:
            result.retrieved.setdefault(h.doc_id, h)

    backend = kw.get("filter_backend", "paperclip")
    if use_filter and filter_criterion and backend == "claude":
        from .claude_judge import judge
        kept = judge(result.retrieved, filter_criterion,
                     model=kw.get("judge_model"))
        result.retrieved = {d: h for d, h in result.retrieved.items()
                            if d in kept}
        return result

    if use_filter and filter_criterion and set_ids:
        # `paperclip merge` currently fails to find freshly created sets, so
        # filter each query's set separately and union the survivors. The LLM
        # filter is stochastic, so run `filter_repeats` independent rounds
        # (each round needs a fresh search — filter consumes the set) and keep
        # a paper if any round keeps it (union vote, recall-favoring).
        repeats = int(kw.get("filter_repeats", 1))
        kept_ids: set[str] = set()
        kept_titles: set[str] = set()

        def one_round(round_set_ids: list[str]) -> None:
            for set_id in round_set_ids:
                for h in llm_filter(set_id, filter_criterion):
                    kept_ids.add(h.doc_id)
                    kept_titles.add(norm_title(h.title))

        one_round(set_ids)
        for _ in range(repeats - 1):
            fresh = []
            for q in queries:
                _, sid = search(q, sources=sources, n=n, return_set_id=True)
                if sid:
                    fresh.append(sid)
            one_round(fresh)

        result.retrieved = {
            d: h for d, h in result.retrieved.items()
            if d in kept_ids or norm_title(h.title) in kept_titles
        }
    return result


def save_result(result: BacksearchResult, out_path: Path, config: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"config": config, "metrics": result.metrics(),
               "per_query": result.per_query}
    out_path.write_text(json.dumps(payload, indent=2))
