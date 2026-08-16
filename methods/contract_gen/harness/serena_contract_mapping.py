"""Maps a Serena RepositoryFindings object (methods/serena/harness.py) into model_contract.yaml
cited_field values.

orchestrator.py's stage_synthesize_contract() calls findings_to_contract_fields() when Stage 2 ran
with --comprehension-engine serena, instead of building fields from the heuristic's flat
sc_signals/chemical_signals lists. Every field here traces to a real Finding's file_path/line_range
-- never a guess, same citation discipline as the heuristic path (repo:file:line).

This is deliberately generic -- nothing here is keyed on "scape" or any other specific method name.
The mapping rules (module-level function preferred as entrypoint, DE/pval/lfc-naming implies
de_signature, AnnData/scanpy usage implies single_cell, etc.) are meant to generalize the same way
the Serena harness's own stem lists do -- see harness.py's class docstring and
IMPLEMENTATION_SUMMARY.md's "Recommendations for Next Methods".
"""

from __future__ import annotations

import re
from typing import Any

# Local import kept lazy-free (no package __init__ side effects) -- Finding is a plain data class.
from methods.serena.harness import Finding, RepositoryFindings

_SC_COUNTS_RE = re.compile(r"anndata|AnnData|\.obs\[|sc\.pp\.|setup_anndata", re.I)
_DE_SIGNAL_RE = re.compile(r"log2fc|logfc|l2fc|fold.?change|p.?val|slogpval|differential", re.I)
_SIG_ARG_RE = re.compile(r"(\w+)\s*=\s*(\"[^\"]*\"|'[^']*'|-?\d+\.\d+|-?\d+|True|False|None)")


def _citation(finding: Finding) -> str:
    if finding.line_range and finding.line_range[0] is not None:
        start, end = finding.line_range
        end = end if end is not None else start
        return f"repo:{finding.file_path}:L{start}-L{end}"
    return f"repo:{finding.file_path}:L1"


def _cited(value: Any, citation: str) -> dict:
    return {"value": value, "citation": citation}


def _unknown() -> dict:
    return {"value": "unknown", "citation": None}


def _parse_signature_defaults(signature: str | None) -> dict[str, Any]:
    """Best-effort `name=default` extraction from a signature string (e.g. train's own). Only
    parameters with a literal scalar default are captured -- list/dict defaults and bare
    positional args (no `=`) aren't modeled as hyperparameters/arguments.
    """
    if not signature:
        return {}
    out: dict[str, Any] = {}
    for name, raw in _SIG_ARG_RE.findall(signature):
        if raw == "True":
            out[name] = True
        elif raw == "False":
            out[name] = False
        elif raw == "None":
            continue  # no type to infer an argument/hyperparameter from
        elif raw.startswith(("\"", "'")):
            out[name] = raw[1:-1]
        else:
            out[name] = float(raw) if "." in raw else int(raw)
    return out


def _arg_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "double"
    return "string"


def pick_primary_entrypoint(findings: RepositoryFindings) -> Finding | None:
    """Prefer a module-level function (no '/' in its symbol) over a class method as the intended
    published entrypoint -- a method usually requires the caller to already have an instance,
    which is a level of indirection a "public API" citation shouldn't silently assume. Falls back
    to the first training public_api if none qualify, then any public_api at all.
    """
    training_apis = [f for f in findings.public_apis if f.category == "training"]
    module_level = [f for f in training_apis if f.symbol and "/" not in f.symbol]
    candidates = module_level or training_apis or findings.public_apis
    return candidates[0] if candidates else None


def _dependencies_finding(findings: RepositoryFindings) -> Finding | None:
    for f in findings.all_findings:
        if f.type == "reference" and f.category == "dependencies":
            return f
    return None


def findings_to_contract_fields(findings: RepositoryFindings) -> dict[str, Any]:
    """Translate RepositoryFindings into the subset of model_contract.yaml fields Serena evidence
    can actually speak to: entrypoint, prediction_level, requires_sc_counts, gene_space.n_genes,
    hyperparameters, arguments, dependencies. Fields Serena has no evidence for (chemical/genetic
    perturbation_encoding, checkpoint URLs, compute/vram) are deliberately left out of this dict --
    the caller (orchestrator.py) is responsible for filling those from its own signal scan or
    leaving them `unknown`, exactly as the heuristic path already does.
    """
    result: dict[str, Any] = {}

    entrypoint = pick_primary_entrypoint(findings)
    result["entrypoint_field"] = _cited(entrypoint.symbol, _citation(entrypoint)) if entrypoint else _unknown()

    loaders = findings.data_loaders
    sc_loader = next((f for f in loaders if f.body_snippet and _SC_COUNTS_RE.search(f.body_snippet)), None)
    if sc_loader:
        result["requires_sc_counts_field"] = _cited(True, _citation(sc_loader))
    elif loaders:
        result["requires_sc_counts_field"] = _cited(False, _citation(loaders[0]))
    else:
        result["requires_sc_counts_field"] = _unknown()

    if result["requires_sc_counts_field"]["value"] is True:
        result["prediction_level_field"] = _cited("single_cell", result["requires_sc_counts_field"]["citation"])
    else:
        de_loader = next(
            (f for f in loaders if _DE_SIGNAL_RE.search(f.symbol or "") or _DE_SIGNAL_RE.search(f.description or "")),
            None,
        )
        if de_loader:
            result["prediction_level_field"] = _cited("de_signature", _citation(de_loader))
        elif loaders:
            result["prediction_level_field"] = _cited("pseudobulk", _citation(loaders[0]))
        else:
            result["prediction_level_field"] = _unknown()

    hyperparameters: dict[str, dict] = {}
    arguments: list[dict] = []
    if entrypoint is not None:
        citation = _citation(entrypoint)
        for name, value in _parse_signature_defaults(entrypoint.signature).items():
            hyperparameters[name] = _cited(value, citation)
            arg_name = "--" + name.lower()
            if re.match(r"^--[a-z][a-z0-9_]*$", arg_name):
                arguments.append({
                    "name": arg_name,
                    "arg_type": _arg_type(value),
                    "description": f"Parameter of {entrypoint.symbol} (repo default, not the component's own choice unless re-cited elsewhere)",
                    "value": value,
                    "citation": citation,
                })
    result["hyperparameters"] = hyperparameters
    result["arguments"] = arguments

    preprocessing_selects = [f for f in findings.preprocessing if f.category == "select"]
    if preprocessing_selects and "n_genes" not in hyperparameters:
        sel = preprocessing_selects[0]
        defaults = _parse_signature_defaults(sel.signature)
        if "k" in defaults:
            result["hyperparameters"]["n_genes"] = _cited(defaults["k"], _citation(sel))

    result["gene_space"] = {
        "n_genes": result["hyperparameters"].get("n_genes", _unknown()),
        "id_type": _unknown(),
        "order_sensitive": _unknown(),
    }

    dep_finding = _dependencies_finding(findings)
    dependencies: list[dict] = []
    if dep_finding:
        citation = _citation(dep_finding)
        for raw in dep_finding.dependencies:
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", raw)
            package, spec = (m.group(1), m.group(2)) if m else (raw, "")
            dependencies.append({"package": package, "value": spec or "unknown", "citation": citation})
    result["dependencies"] = dependencies

    checkpoint_saves = [f for f in findings.checkpoints if f.category == "save"]
    result["checkpoint_note"] = (
        f"Model is trained from scratch per invocation ({checkpoint_saves[0].symbol} persists "
        f"config/weights/results locally, not a hosted pretrained checkpoint) -- see {_citation(checkpoint_saves[0])}"
        if checkpoint_saves else None
    )

    return result
