"""Load and validate model_contract.yaml / MODELSPEC.json.

This is the handoff artifact from Cecilia's lane (Stage 3). Two things are enforced here that
schemas/model_contract.schema.json can't express on its own:

1. Citation discipline: every field wrapped as a cited_field must either be "unknown", or carry a
   citation matching PAPER_ID:...:Lstart-Lend or repo:path:Lline. A confident-looking value with no
   citation is treated as a validation error, not a warning -- per A5's acceptance criterion, and
   per the design principle discussed upstream: a confident wrong value here silently corrupts
   every score downstream, so the burden of proof is on the field, not on the reviewer.
2. The scope gate (E2): perturbation_encoding == "gene_id" means this is a genetic-perturbation
   method routed at a chemical-perturbation task. Refuse and return upstream rather than adapt it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

SCHEMA_PATH = Path(__file__).parent.parent.parent / "model_contract.schema.json"  # shared with contract_gen

_CITATION_RE = re.compile(
    r"^(PAPER_ID:[A-Za-z0-9_.:-]+:L[0-9]+-L?[0-9]+|repo:[^:]+:L?[0-9]+(-L?[0-9]+)?)$"
)


class ContractValidationError(Exception):
    """Raised when a contract fails structural validation or citation discipline."""


class ScopeRejection(Exception):
    """Raised by scope_gate() when a method is out of scope for this task and must go back upstream."""

    def __init__(self, reason: str, eval_record: dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.eval_record = eval_record


@dataclass
class ContractIssue:
    path: str
    message: str


@dataclass
class LoadedContract:
    raw: dict[str, Any]
    path: Path
    issues: list[ContractIssue] = field(default_factory=list)

    def get(self, *keys: str, default: Any = "unknown") -> Any:
        """Walk a dotted path of cited_field wrappers and return the .value, or default."""
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        if isinstance(node, dict) and "value" in node and "citation" in node:
            return node["value"]
        return node


def _walk_cited_fields(node: Any, path: str = "$") -> list[tuple[str, dict]]:
    """Find every dict that looks like a cited_field ({"value": ..., "citation": ...})."""
    found: list[tuple[str, dict]] = []
    if isinstance(node, dict):
        if set(node.keys()) >= {"value", "citation"}:
            found.append((path, node))
        else:
            for k, v in node.items():
                found.extend(_walk_cited_fields(v, f"{path}.{k}"))
    return found


def _check_citation_discipline(raw: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    for path, cited in _walk_cited_fields(raw):
        value = cited.get("value")
        citation = cited.get("citation")
        if value == "unknown":
            continue  # always legal, per A5
        if citation is None:
            issues.append(ContractIssue(path, "value is not 'unknown' but citation is null — no guessing allowed"))
            continue
        if not _CITATION_RE.match(citation):
            issues.append(ContractIssue(path, f"citation '{citation}' does not match PAPER_ID:...:Lx-Ly or repo:...:Lx"))
    return issues


def resolve_citation(citation: str, *, paper_pack_dir: Path | None = None, repo_dir: Path | None = None) -> tuple[bool, str]:
    """Best-effort check that a citation actually points at real material.

    Without paper_pack_dir / repo_dir this only validates the citation's *syntax* (already done in
    _check_citation_discipline) and says so explicitly -- it does not silently pass a citation off
    as verified when it wasn't.
    """
    if citation.startswith("repo:"):
        _, rest = citation.split(":", 1)
        file_part = rest.split(":L", 1)[0]
        if repo_dir is None:
            return True, "syntax-only: no repo_dir provided to resolve against"
        target = repo_dir / file_part
        return target.exists(), f"repo file {'found' if target.exists() else 'MISSING'}: {target}"
    if citation.startswith("PAPER_ID:"):
        if paper_pack_dir is None:
            return True, "syntax-only: no paper_pack_dir provided to resolve against"
        parts = citation.split(":")
        paper_id = parts[1]
        target = paper_pack_dir / f"{paper_id}.content.lines"
        return target.exists(), f"paper pack {'found' if target.exists() else 'MISSING'}: {target}"
    return False, "unrecognized citation scheme"


def load_contract(path: str | Path, *, schema_path: Path = SCHEMA_PATH) -> LoadedContract:
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) if path.suffix in (".yaml", ".yml") else json.loads(path.read_text())

    schema = json.loads(schema_path.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    issues = [ContractIssue("$." + ".".join(str(p) for p in e.path), e.message) for e in validator.iter_errors(raw)]
    issues += _check_citation_discipline(raw)

    return LoadedContract(raw=raw, path=path, issues=issues)


def require_valid(contract: LoadedContract) -> LoadedContract:
    if contract.issues:
        lines = "\n".join(f"  - {i.path}: {i.message}" for i in contract.issues)
        raise ContractValidationError(
            f"{contract.path} failed validation ({len(contract.issues)} issue(s)):\n{lines}"
        )
    return contract


def scope_gate(contract: LoadedContract) -> None:
    """E2: refuse a method whose perturbation_encoding resolves to gene_id.

    We are the second line of scope defense -- heroically adapting a genetic method into the
    chemical task is a failure that looks like a save. Raises ScopeRejection with an eval_record
    shaped for Vlad's scope classifier, rather than returning a bool, so a caller can't accidentally
    ignore the rejection and proceed to synthesize an adapter anyway.
    """
    encoding = contract.get("perturbation_encoding")
    if encoding == "gene_id":
        eval_record = {
            "method_id": contract.raw.get("method_id", "unknown"),
            "repo": contract.get("model", "repo"),
            "commit": contract.get("model", "commit"),
            "rejected_field": "perturbation_encoding",
            "rejected_value": "gene_id",
            "reason": "genetic-perturbation method routed at a chemical-perturbation task",
        }
        raise ScopeRejection(
            f"perturbation_encoding=gene_id for method_id={eval_record['method_id']} — refusing, returning upstream",
            eval_record,
        )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Validate a model_contract.yaml / MODELSPEC.json")
    ap.add_argument("contract_path")
    args = ap.parse_args()

    c = load_contract(args.contract_path)
    if c.issues:
        print(f"INVALID — {len(c.issues)} issue(s):")
        for i in c.issues:
            print(f"  - {i.path}: {i.message}")
        raise SystemExit(1)

    print(f"OK — {args.contract_path} is structurally valid and citation-clean.")
    try:
        scope_gate(c)
        print(f"scope: PASS (perturbation_encoding={c.get('perturbation_encoding')!r})")
    except ScopeRejection as e:
        print(f"scope: REJECTED — {e.reason}")
        print(json.dumps(e.eval_record, indent=2))
        raise SystemExit(2)
