"""Thin wrapper around the paperclip CLI.

All literature search goes through paperclip. This module is benchmark-agnostic:
it knows nothing about which benchmark or keywords are being used.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

DOC_ID_RE = re.compile(r"\b(PMC\d+|bio_[0-9a-f]+|med_[0-9a-f]+|arx_[\w.]+|oa_W\d+)\b")
RESULT_SET_RE = re.compile(r"\[(s_[0-9a-f]+)\]|saved to (s_[0-9a-f]+)")
ARXIV_DOI_RE = re.compile(r"10\.48550/arXiv\.(\d{4}\.\d{4,5})", re.IGNORECASE)

DEFAULT_SOURCES = "pmc,biorxiv,medrxiv,arxiv"


def run(args: list[str], timeout: int = 120) -> str:
    """Run a paperclip command and return combined stdout+stderr.

    A nonzero exit is loudly logged (not raised: several paperclip commands
    exit nonzero on ordinary no-match results) — a crashed or misconfigured
    CLI must not silently parse as "zero hits".
    """
    proc = subprocess.run(
        ["paperclip", *args], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        print(f"WARNING: paperclip {' '.join(args[:2])}... exited "
              f"{proc.returncode}: {proc.stderr.strip()[:300]}",
              file=sys.stderr)
    return proc.stdout + proc.stderr


@dataclass
class SearchHit:
    doc_id: str
    title: str
    rank: int


def _parse_hits(out: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    current_rank = None
    current_title = ""
    for line in out.splitlines():
        m = re.match(r"^\s*(\d+)\.\s+(.*)", line)
        if m:
            current_rank = int(m.group(1))
            current_title = m.group(2).strip()
            continue
        m = DOC_ID_RE.search(line)
        if m and current_rank is not None:
            hits.append(SearchHit(m.group(1), current_title, current_rank))
            current_rank = None
    return hits


def _parse_result_set_id(out: str) -> str | None:
    ids = [a or b for a, b in RESULT_SET_RE.findall(out)]
    return ids[-1] if ids else None


def search(query: str, sources: str = DEFAULT_SOURCES, n: int = 10,
           since: str | None = None,
           search_all: bool = True) -> tuple[list[SearchHit], str | None]:
    """Run `paperclip search`; returns (ranked hits, saved result-set id).

    CAUTION: without --all, paperclip silently restricts results to recent
    papers, and an over-filtered search is indistinguishable from an empty
    corpus. We therefore pass --all by default; scheduled new-paper runs
    should pass `since` instead.
    """
    args = ["search", query, "-s", sources, "-n", str(n)]
    if since:
        args += ["--since", since]
    elif search_all:
        args += ["--all"]
    out = run(args)
    return _parse_hits(out), _parse_result_set_id(out)


def llm_filter(set_id: str, criterion: str,
               timeout: int = 600) -> list[SearchHit]:
    """Run paperclip's LLM relevance filter on a saved result set.

    `filter` updates the set in place and prints only a summary, so the
    surviving papers are read back with `results`.

    Note: filtering the union of several sets in one call is blocked upstream —
    `paperclip merge` fails to find freshly created result sets — so callers
    filter per set and union the survivors themselves.
    """
    run(["filter", "--from", set_id, criterion], timeout=timeout)
    out = run(["results", set_id], timeout=timeout)
    return _parse_hits(out)


def resolve_doc_id(doi: str | None, title: str | None) -> str | None:
    """Resolve a paper to a paperclip doc id.

    arXiv papers are NOT in paperclip's lookup/search indexes, but their full
    texts are in the corpus under deterministic ids (arx_<arxiv_id>), so for
    arXiv DOIs we construct the id and verify the document exists."""
    if doi:
        m = ARXIV_DOI_RE.search(doi)
        if m:
            doc_id = f"arx_{m.group(1)}"
            out = run(["ls", f"/papers/{doc_id}/"])
            if "content.lines" in out:
                return doc_id
    for field, value in (("doi", doi), ("title", title)):
        if not value:
            continue
        out = run(["lookup", field, value])
        m = DOC_ID_RE.search(out)
        if m:
            return m.group(1)
    return None
