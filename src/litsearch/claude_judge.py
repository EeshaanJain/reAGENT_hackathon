"""Abstract-based relevance judge using headless Claude (`claude -p`).

Alternative filter backend to `paperclip filter`. paperclip's filter judges
papers from search-result snippets, and arXiv results carry no snippet at all,
so title-only judgments reject relevant papers. This backend reads each
paper's actual title + abstract from its meta.json and classifies all papers
in one batched LLM call.
"""

from __future__ import annotations

import json
import re
import subprocess

from .paperclip_client import SearchHit, run

PROMPT_TEMPLATE = """You are curating papers for a benchmark.

Relevance criterion:
{criterion}

Below are candidate papers, each with an id, title, and abstract. Decide for
each whether it matches the criterion.

Respond with ONLY a JSON object mapping every paper id to true (keep) or
false (drop). No other text.

{papers}"""


def get_abstract(doc_id: str) -> dict:
    """Fetch title + abstract from a paper's meta.json (empty on failure)."""
    out = run(["cat", f"/papers/{doc_id}/meta.json"])
    start = out.find("{")
    end = out.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        meta = json.loads(out[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return {"title": meta.get("title", ""), "abstract": meta.get("abstract", "")}


def judge(retrieved: dict[str, SearchHit], criterion: str,
          model: str | None = None, timeout: int = 900) -> set[str]:
    """Return the doc_ids judged relevant."""
    blocks = []
    for doc_id, hit in retrieved.items():
        meta = get_abstract(doc_id)
        title = meta.get("title") or hit.title
        abstract = (meta.get("abstract") or "").strip()[:2500]
        blocks.append(f"id: {doc_id}\ntitle: {title}\nabstract: {abstract}\n")
    prompt = PROMPT_TEMPLATE.format(criterion=criterion,
                                    papers="\n".join(blocks))

    cmd = ["claude", "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude judge exited {proc.returncode}: "
            f"{proc.stderr.strip()[:500] or proc.stdout.strip()[:500]}")
    out = proc.stdout
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        raise RuntimeError(f"judge returned no JSON: {out[:500]}")
    verdicts = json.loads(m.group())
    return {doc_id for doc_id, keep in verdicts.items() if keep}
