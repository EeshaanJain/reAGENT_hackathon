"""Parses a Paperclip-format literature-agent record -- the real upstream input from the
literature agent (Vlad's lane, not built here) -- into a RepoLaunch instance dict, and separately
extracts PAPER_ID-cited evidence from the paper's own full text when it's actually available
locally.

Real record shape (one JSON object per candidate method, as handed off by the literature agent):

    title, authors, id (e.g. "PMC10258562" -- this becomes the PAPER_ID used in citations),
    source, date, url, abstract, method_name, method_folder, source_folder,
    metadata_status, metadata_path, full_text_status, raw_full_text_path, clean_full_text_path,
    full_text_validation_path, cat_full_status, cat_full_path (line-numbered full text, matching
    Paperclip's own content.lines convention), code_evidence_path, github_flag,
    github_candidates (a URL, not an owner/repo slug), pdf_status, pdf_path

`full_text_status: "needs_review"` / `pdf_status: "unavailable"` are legitimate real states from
the literature agent, not errors -- see B3 in method-integration-todo.html ("decide the
full-text-unavailable degradation path... the answer should be 'affected contract fields become
unknown', never 'the agent infers them'"). This module follows that rule: if the referenced
full-text file isn't actually present, paper-side evidence extraction returns nothing rather than
guessing from the abstract alone.
"""

from __future__ import annotations

import re
from pathlib import Path


class PaperclipRecordError(Exception):
    """Raised when a record can't be turned into a RepoLaunch instance -- e.g. no usable
    github_candidates. This is a refusal, not a guess: see scope_gate()'s sibling philosophy in
    benchmark_adapt/harness/contract.py.
    """


def parse_repo_slug(github_candidates: str) -> str:
    """'https://github.com/theislab/cpa' -> 'theislab/cpa'. Raises on anything that isn't a plain
    GitHub repo URL -- github_candidates can in principle hold something else (a comment, a
    not-found marker); do not silently mis-parse it into a bogus owner/repo.
    """
    m = re.search(r"github\.com[:/]+([^/\s]+/[^/\s?#]+?)(?:\.git)?/?$", github_candidates.strip())
    if not m:
        raise PaperclipRecordError(f"could not parse an owner/repo slug from github_candidates={github_candidates!r}")
    return m.group(1)


def to_repolaunch_instance(record: dict, *, base_commit: str = "RESOLVED_AT_RUNTIME", language: str = "python") -> dict:
    """Derive RepoLaunch's own instance schema (instance_id/repo/base_commit/language/hints) from
    a Paperclip record. `base_commit` defaults to letting repolaunch_runner resolve current HEAD;
    pass a real pinned SHA once one is known (e.g. from code_evidence_path, if that names one).
    """
    if record.get("github_flag") != "candidate_found" or not record.get("github_candidates"):
        raise PaperclipRecordError(
            f"record for {record.get('method_name', '?')!r} has no usable github_candidates "
            f"(github_flag={record.get('github_flag')!r}) -- refuse rather than guess a repo"
        )

    repo = parse_repo_slug(record["github_candidates"])
    hint_parts = [record.get("title", ""), record.get("abstract", "")]
    hints = " -- ".join(p for p in hint_parts if p) or None

    date = record.get("date", "")
    created_at = f"{date}T00:00:00Z" if date else None

    instance = {
        "instance_id": record.get("method_name") or repo.split("/")[-1],
        "repo": repo,
        "base_commit": base_commit,
        "language": language,
    }
    if created_at:
        instance["created_at"] = created_at
    if hints:
        instance["hints"] = hints
    return instance


def paper_id(record: dict) -> str:
    return record.get("id", "unknown")


def paper_citation_prefix(record: dict) -> str:
    """PAPER_ID:<id> -- the prefix every citation into this paper's text uses."""
    return f"PAPER_ID:{paper_id(record)}"


def find_paper_evidence(record: dict, patterns: list[tuple[str, str]], *, repo_root: Path) -> list[dict]:
    """Grep the paper's own full text (if the file Paperclip's record points at is actually
    present) for the same kind of signal patterns used against the repo -- e.g. single-cell vs.
    chemical vs. genetic language -- citing PAPER_ID:Lline-Lline on a hit.

    Returns [] (not a guess) when the file is missing -- true whenever full_text_status is
    "needs_review"/"unavailable" and no local copy has actually been fetched, which is expected
    for a Paperclip record this pipeline doesn't itself produce.
    """
    text_path_str = record.get("cat_full_path") or record.get("clean_full_text_path")
    if not text_path_str:
        return []
    text_path = repo_root / text_path_str
    if not text_path.exists():
        return []

    pid = paper_id(record)
    lines = text_path.read_text(errors="ignore").splitlines()
    evidence = []
    for pattern, label in patterns:
        for i, line in enumerate(lines, start=1):
            if re.search(pattern, line):
                evidence.append({"label": label, "citation": f"PAPER_ID:{pid}:L{i}-L{i}"})
                break  # first hit per pattern only -- same discipline as the repo-side scan
    return evidence


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Parse a Paperclip record into a RepoLaunch instance dict")
    ap.add_argument("record_path", type=Path)
    args = ap.parse_args()

    record = json.loads(args.record_path.read_text())
    try:
        instance = to_repolaunch_instance(record)
    except PaperclipRecordError as e:
        print(f"REFUSING: {e}")
        raise SystemExit(1)

    print(json.dumps(instance, indent=2))
    print(f"\npaper citation prefix: {paper_citation_prefix(record)}")
    print(f"full_text_status={record.get('full_text_status')!r}, cat_full_status={record.get('cat_full_status')!r}")
