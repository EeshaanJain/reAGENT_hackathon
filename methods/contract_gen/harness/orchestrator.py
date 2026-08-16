#!/usr/bin/env python3
"""Method Integration Orchestrator: repository intake, real environment reconstruction (RepoLaunch),
generalized repo comprehension, and citation-disciplined model contract synthesis.

This is a generalization of Cecilia's original methods/run_method_integration.py. What changed:
  - Standard input is a real Paperclip literature-agent record (harness/paperclip_intake.py),
    which carries the method_name/github_candidates/paper-provenance shape the literature agent
    actually produces. It's translated internally into RepoLaunch's own instance schema
    (instance_id/repo/base_commit/language/hints) -- the --instance flag still accepts that raw
    shape directly, as a fallback for a method with no Paperclip record yet.
  - Stage "RepoLaunch" is real (harness/repolaunch_runner.py -> the vendored, pinned `launch`
    binary), not step_mock_repolarunch's placeholder.
  - Stage "repo comprehension" is generalized static analysis, not hardcoded to scAPE's specific
    module layout (`scape/__main__.py`, `scape/_api.py`). It's still a heuristic stand-in for real
    Serena MCP analysis, not Serena itself -- see README.md "what's real vs. a stand-in". Every
    field it sets carries a repo:file:line citation to what it actually matched, never a guess.
  - Contract output conforms to ../model_contract.schema.json (the schema shared with
    benchmark_adapt) -- {"value": ..., "citation": ...} per field, "unknown" legal -- instead of a
    flat JSON blob with a separate _evidence_notes field.

Usage:
  python -m harness.orchestrator --paperclip-record fixtures/paperclip_cpa_record.json \\
      --repolaunch-config fixtures/repolaunch_config_cpa.json --output output/cpa

The --instance flag (a raw RepoLaunch instance dict) still works as a fallback for a method with
no Paperclip record yet, but --paperclip-record is the standard path -- see paperclip_intake.py.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import paperclip_intake, repolaunch_runner  # noqa: E402

CONTRACT_GEN_ROOT = Path(__file__).parent.parent
REPO_ROOT = CONTRACT_GEN_ROOT.parent.parent
# Needed for `from methods.serena.harness import ...` (stage_repo_comprehension_serena) and
# `from harness.serena_contract_mapping import ...` (stage_synthesize_contract) -- both resolve
# against the top-level reAGENT_hackathon repo root, not this file's own directory.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCHEMA_PATH = CONTRACT_GEN_ROOT.parent / "model_contract.schema.json"

# Generic entrypoint signals -- not tied to any one method's module layout.
ENTRYPOINT_FILE_PATTERNS = ["__main__.py", "train.py", "predict.py", "inference.py", "run.py", "cli.py"]
SC_SIGNAL_PATTERNS = [
    (r"\banndata\b", "anndata import"),
    (r"\bAnnData\b", "AnnData usage"),
    (r"\bscanpy\b", "scanpy import"),
    (r"\.obs\[", "AnnData .obs indexing"),
    (r"sc\.pp\.", "scanpy preprocessing call"),
    (r"setup_anndata", "setup_anndata call (single-cell-model convention)"),
]
CHEMICAL_SIGNAL_PATTERNS = [(r"\bSMILES\b", "SMILES reference"), (r"\brdkit\b", "rdkit import")]
GENETIC_SIGNAL_PATTERNS = [(r"\bCRISPR\b", "CRISPR reference"), (r"\bguide_rna\b", "guide RNA reference"), (r"\bsgRNA\b", "sgRNA reference")]
# Same exclusion set as methods/serena/harness.py's SerenaRepositoryAnalyzer.EXCLUDE_DIRS, and for
# the same reason: notebooks/docs/examples/tests aren't the shipped model, so a naming-convention
# hit inside them isn't evidence of what the *method* does.
COMPREHENSION_EXCLUDE_DIRS = {
    "tests", "test", "docs", "doc", "examples", "notebooks", "scripts",
    ".git", ".github", ".serena", "build", "dist", "__pycache__", ".venv", "venv", "node_modules",
}


def cited(value: Any, citation: str | None) -> dict:
    return {"value": value, "citation": citation}


def unknown() -> dict:
    return {"value": "unknown", "citation": None}


class MethodIntegrationOrchestrator:
    def __init__(
        self,
        instance: dict,
        output_dir: Path,
        repolaunch_config: dict,
        *,
        repolaunch_timeout_s: int = 1800,
        paperclip_record: dict | None = None,
        paperclip_corpus_root: Path | None = None,
        comprehension_engine: str = "heuristic",
    ):
        self.instance = instance
        self.output_dir = output_dir
        self.repolaunch_config = repolaunch_config
        self.repolaunch_timeout_s = repolaunch_timeout_s
        self.paperclip_record = paperclip_record
        self.comprehension_engine = comprehension_engine
        # cat_full_path etc. in a Paperclip record are relative to Paperclip's OWN corpus root
        # (wherever the literature agent stores downloaded/processed papers) -- a completely
        # different location from self.repo_dir (the cloned *model* repo). Must be configured
        # explicitly; there's no way to derive it from the record itself.
        self.paperclip_corpus_root = paperclip_corpus_root
        self.work_dir = output_dir / "work"
        self.repo_dir: Path | None = None
        self.execution_log: list[dict] = []
        self.artifacts: dict[str, Any] = {}

    def resume_from_manifest(self, manifest_path: Path) -> None:
        """Reconstruct ingest/RepoLaunch/comprehension artifacts from a prior successful run's
        repo_manifest.json, so stage_synthesize_contract can be re-run (e.g. with paperclip
        enrichment, or a corrected method_id) without repeating the expensive RepoLaunch build.
        RepoLaunch bills real API usage per invocation -- reuse a PASS result, don't redo it.
        """
        manifest = json.loads(manifest_path.read_text())
        self.repo_dir = self.work_dir / "repo"
        self.artifacts["repo_url"] = manifest["repo_url"]
        self.artifacts["commit_sha"] = manifest["resolved_commit_sha"]
        self.artifacts["comprehension"] = manifest.get("comprehension", {})
        if manifest.get("docker_image"):
            self.artifacts["repolaunch_result"] = repolaunch_runner.RepoLaunchResult(
                status=manifest.get("repolaunch_status", "PASS"),
                instance_id=self.instance["instance_id"],
                repo=manifest["repo_url"],
                resolved_commit_sha=manifest["resolved_commit_sha"],
                docker_image=manifest["docker_image"],
                docker_image_layers=None,
                setup_commands=None,
                completed=True,
                exception=None,
                cost=None,
                duration_min=None,
                raw_result_path=None,
            )
        self.log_action("resume_from_manifest", str(manifest_path), f"reused docker_image={manifest.get('docker_image')}", status="success")

    def log_action(self, stage: str, cmd: str = "", result: str = "", error: str = "", status: str = "success", wall_clock_s: float | None = None):
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "stage": stage, "cmd": cmd, "status": status}
        if result:
            entry["result"] = result
        if error:
            entry["error"] = error
        if wall_clock_s is not None:
            entry["wall_clock_s"] = wall_clock_s
        self.execution_log.append(entry)
        print(f"[{stage}] {status.upper()}: {result or error or cmd}", flush=True)

    def run_command(self, cmd: list[str], stage: str, cwd: Path | None = None) -> tuple[bool, str]:
        try:
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                self.log_action(stage, " ".join(cmd), result.stdout[:300], status="success")
                return True, result.stdout
            self.log_action(stage, " ".join(cmd), error=result.stderr[:300], status="failure")
            return False, result.stderr
        except Exception as e:
            self.log_action(stage, " ".join(cmd), error=str(e), status="failure")
            return False, str(e)

    # ---- Stage 0: ingest ----
    def stage_ingest(self) -> bool:
        print("\n=== STAGE 0: Ingest ===")
        repo_url = f"https://github.com/{self.instance['repo']}"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.repo_dir = self.work_dir / "repo"
        if self.repo_dir.exists():
            import shutil

            shutil.rmtree(self.repo_dir)

        ok, _ = self.run_command(["git", "clone", repo_url, str(self.repo_dir)], "ingest_clone")
        if not ok:
            return False

        commit = self.instance["base_commit"]
        if commit == "RESOLVED_AT_RUNTIME":
            ok, sha = self.run_command(["git", "rev-parse", "HEAD"], "ingest_resolve_head", cwd=self.repo_dir)
            if not ok:
                return False
            commit = sha.strip()
        else:
            ok, _ = self.run_command(["git", "checkout", commit], "ingest_checkout_pinned", cwd=self.repo_dir)
            if not ok:
                return False

        self.artifacts["commit_sha"] = commit
        self.artifacts["repo_url"] = repo_url
        return True

    # ---- Stage 1: real RepoLaunch ----
    def stage_environment(self) -> repolaunch_runner.RepoLaunchResult:
        print("\n=== STAGE 1: Environment reconstruction (RepoLaunch) ===")
        t0 = datetime.now(timezone.utc)
        result = repolaunch_runner.run(
            self.instance, self.repolaunch_config, workdir=self.output_dir / "repolaunch", timeout_s=self.repolaunch_timeout_s
        )
        wall = (datetime.now(timezone.utc) - t0).total_seconds()
        self.log_action(
            "environment_repolaunch", f"launch instance={self.instance['instance_id']}",
            result=f"status={result.status} image={result.docker_image}", status="success" if result.status == "PASS" else "failure",
            wall_clock_s=wall,
        )
        self.artifacts["repolaunch_result"] = result
        return result

    # ---- Stage 2: generalized repo comprehension ----
    def stage_repo_comprehension(self) -> dict:
        """Dispatches on self.comprehension_engine. "heuristic" (default) is grep/regex static
        analysis -- kept as the zero-dependency fallback and to not change behavior for any
        existing run (e.g. CPA) that doesn't pass --comprehension-engine. "serena" runs a live
        Serena MCP session (methods/serena/harness.py) for the ML-comprehension fields
        (entrypoint/prediction_level/requires_sc_counts/gene_space/hyperparameters/arguments/
        dependencies) and still reuses the heuristic's chemical/genetic grep for
        perturbation_encoding, which Serena's 8(+1)-stage sequence doesn't cover.
        """
        if self.comprehension_engine == "serena":
            return self.stage_repo_comprehension_serena()
        return self.stage_repo_comprehension_heuristic()

    def _scan_chem_genetic_sc_signals(self, *, max_files: int = 200) -> dict:
        """Grep-based signal detection for perturbation_encoding (chemical/genetic) and, for the
        heuristic path only, single-cell usage -- cited to real file:line, never asserted without a
        match. Shared by both comprehension engines; Serena's own stages don't cover this (it's not
        a symbol-level query, just a repo-wide naming-convention scan).

        Skips a match whose own line is a drop/delete/discard (`df.drop(columns=["SMILES", ...])`,
        `del col`) -- a signal name being discarded from the data is evidence the method does *not*
        use it, the opposite of what a bare substring hit would otherwise claim. Generic exclusion,
        not scoped to any one signal name.
        """
        drop_context_re = re.compile(r"\.drop\(|\bdel\s|\.discard\(|\.pop\(")
        findings: dict[str, Any] = {"sc_signals": [], "chemical_signals": [], "genetic_signals": [], "python_files_sampled": 0}
        if not self.repo_dir:
            return findings
        ok, py_files_raw = self.run_command(["find", str(self.repo_dir), "-name", "*.py", "-type", "f"], "comprehension_find_py")
        all_py_files = [Path(f.strip()) for f in py_files_raw.splitlines() if f.strip()] if ok else []
        # Exploratory notebook helpers, docs, and examples aren't the shipped model -- a rdkit
        # import in docs/notebooks/*.py doesn't mean the *method* encodes perturbations by
        # structure. Same exclusion set as methods/serena/harness.py's EXCLUDE_DIRS, applied here
        # for the same reason: only the actual package/library code is evidence of what the model
        # does.
        py_files = [f for f in all_py_files if not (COMPREHENSION_EXCLUDE_DIRS & set(f.relative_to(self.repo_dir).parts))]
        findings["python_files_sampled"] = len(py_files)

        for f in py_files[:max_files]:  # cap for a large repo; this is a heuristic pass, not exhaustive
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            rel = f.relative_to(self.repo_dir)
            for key, patterns in [("sc_signals", SC_SIGNAL_PATTERNS), ("chemical_signals", CHEMICAL_SIGNAL_PATTERNS), ("genetic_signals", GENETIC_SIGNAL_PATTERNS)]:
                for pattern, label in patterns:
                    for m in re.finditer(pattern, text):
                        line_start = text.rfind("\n", 0, m.start()) + 1
                        line_end = text.find("\n", m.end())
                        line = text[line_start : line_end if line_end != -1 else None]
                        if drop_context_re.search(line):
                            continue  # this occurrence is the signal being discarded, not used -- keep scanning
                        line_no = text[: m.start()].count("\n") + 1
                        findings[key].append({"label": label, "citation": f"repo:{rel}:L{line_no}"})
                        break
        return findings

    def stage_repo_comprehension_heuristic(self) -> dict:
        print("\n=== STAGE 2: Repo comprehension (heuristic static analysis -- not real Serena) ===")
        findings: dict[str, Any] = {"entrypoints": [], **self._scan_chem_genetic_sc_signals()}
        if not self.repo_dir:
            return findings

        ok, py_files_raw = self.run_command(["find", str(self.repo_dir), "-name", "*.py", "-type", "f"], "comprehension_find_py")
        py_files = [Path(f.strip()) for f in py_files_raw.splitlines() if f.strip()] if ok else []

        for f in py_files:
            if f.name in ENTRYPOINT_FILE_PATTERNS:
                findings["entrypoints"].append(str(f.relative_to(self.repo_dir)))

        setup_py = self.repo_dir / "setup.py"
        pyproject = self.repo_dir / "pyproject.toml"
        for entry_file, pattern in [(setup_py, r"console_scripts"), (pyproject, r"\[project\.scripts\]")]:
            if entry_file.exists() and re.search(pattern, entry_file.read_text(errors="ignore")):
                findings["entrypoints"].append(f"{entry_file.name} (console_scripts/[project.scripts] declared)")

        self.log_action(
            "repo_comprehension", "",
            f"{len(findings['entrypoints'])} entrypoint(s), {len(findings['sc_signals'])} sc-signal(s), "
            f"{len(findings['chemical_signals'])} chemical-signal(s), {len(findings['genetic_signals'])} genetic-signal(s) "
            f"across {findings['python_files_sampled']} .py files",
            status="success",
        )
        self.artifacts["comprehension"] = findings
        return findings

    def stage_repo_comprehension_serena(self) -> dict:
        print("\n=== STAGE 2: Repo comprehension (LIVE Serena MCP -- symbol-aware, not grep) ===")
        chem_genetic = self._scan_chem_genetic_sc_signals()
        findings: dict[str, Any] = {"entrypoints": [], "sc_signals": [], **chem_genetic}
        if not self.repo_dir:
            return findings

        from methods.serena.harness import SerenaRepositoryAnalyzer

        analyzer = SerenaRepositoryAnalyzer(repo_path=str(self.repo_dir))
        serena_findings = analyzer.analyze()
        self.artifacts["serena_findings"] = serena_findings

        if serena_findings.serena_status != "success":
            self.log_action(
                "repo_comprehension_serena", "",
                error=f"serena_status={serena_findings.serena_status}: {serena_findings.serena_error}",
                status="failure",
            )
            self.artifacts["comprehension"] = findings
            return findings

        self.log_action(
            "repo_comprehension_serena", "",
            f"{len(serena_findings.all_findings)} findings (public_apis={len(serena_findings.public_apis)}, "
            f"data_loaders={len(serena_findings.data_loaders)}, preprocessing={len(serena_findings.preprocessing)}, "
            f"checkpoints={len(serena_findings.checkpoints)}, examples={len(serena_findings.examples)}); "
            f"chemical/genetic/sc signals via {chem_genetic['python_files_sampled']} .py files (grep, not Serena)",
            status="success",
        )
        self.artifacts["comprehension"] = findings
        return findings

    # ---- Stage 3: schema-conformant contract synthesis ----
    def stage_synthesize_contract(self) -> dict:
        print("\n=== STAGE 3: Synthesize model_contract.yaml (schema-conformant) ===")
        comp = self.artifacts.get("comprehension", {})
        repolaunch_result: repolaunch_runner.RepoLaunchResult | None = self.artifacts.get("repolaunch_result")

        sc_signals = list(comp.get("sc_signals", []))
        chem_signals = list(comp.get("chemical_signals", []))
        genetic_signals = list(comp.get("genetic_signals", []))

        if self.paperclip_record:
            if self.paperclip_corpus_root is None:
                self.log_action(
                    "paper_evidence", "", status="success",
                    result="no --paperclip-corpus-root configured -- cat_full_path is relative to Paperclip's own "
                    "corpus directory, not this repo, so paper-text evidence extraction is skipped rather than "
                    "guessed. Repo-side evidence only.",
                )
            else:
                paper_sc = paperclip_intake.find_paper_evidence(self.paperclip_record, SC_SIGNAL_PATTERNS, repo_root=self.paperclip_corpus_root)
                paper_chem = paperclip_intake.find_paper_evidence(self.paperclip_record, CHEMICAL_SIGNAL_PATTERNS, repo_root=self.paperclip_corpus_root)
                paper_genetic = paperclip_intake.find_paper_evidence(self.paperclip_record, GENETIC_SIGNAL_PATTERNS, repo_root=self.paperclip_corpus_root)
                # paper evidence is prepended, not appended -- a citation into the paper's own
                # stated methods is preferred over a code-side grep hit when both exist.
                sc_signals = paper_sc + sc_signals
                chem_signals = paper_chem + chem_signals
                genetic_signals = paper_genetic + genetic_signals
                if not paper_sc and not paper_chem and not paper_genetic:
                    self.log_action(
                        "paper_evidence", "", status="success",
                        result=f"no paper-text evidence extracted (full_text_status={self.paperclip_record.get('full_text_status')!r}, "
                        f"cat_full_status={self.paperclip_record.get('cat_full_status')!r}) -- referenced file not present under "
                        "--paperclip-corpus-root, falling back to repo-only evidence rather than guessing from the abstract",
                    )

        # Serena evidence (entrypoint/requires_sc_counts/prediction_level/gene_space/
        # hyperparameters/arguments/dependencies) supersedes the grep heuristic's version of those
        # same fields when a live Serena run succeeded -- it's symbol-aware ground truth, not a
        # naming-convention guess (see serena_contract_mapping.py's module docstring). Chemical/
        # genetic perturbation_encoding is unaffected: neither engine's own stages cover it, both
        # rely on the same _scan_chem_genetic_sc_signals() grep pass folded into `comp` already.
        serena_findings = self.artifacts.get("serena_findings")
        serena_fields: dict[str, Any] = {}
        if serena_findings is not None and serena_findings.serena_status == "success":
            from harness.serena_contract_mapping import findings_to_contract_fields

            serena_fields = findings_to_contract_fields(serena_findings)

        if serena_fields:
            entrypoint_field = serena_fields["entrypoint_field"]
            requires_sc_counts_field = serena_fields["requires_sc_counts_field"]
            prediction_level_field = serena_fields["prediction_level_field"]
            gene_space = serena_fields["gene_space"]
            hyperparameters = serena_fields["hyperparameters"]
            arguments = serena_fields["arguments"]
            dependencies = serena_fields["dependencies"]
        else:
            entrypoint = comp["entrypoints"][0] if comp.get("entrypoints") else None
            entrypoint_field = cited(entrypoint, f"repo:{entrypoint}:L1") if entrypoint else unknown()
            requires_sc_counts_field = cited(True, sc_signals[0]["citation"]) if sc_signals else unknown()
            prediction_level_field = cited("single_cell", sc_signals[0]["citation"]) if sc_signals else unknown()
            gene_space = {"n_genes": unknown(), "id_type": unknown(), "order_sensitive": unknown()}
            hyperparameters = {}
            arguments = []
            dependencies = []

        if chem_signals:
            perturbation_encoding_field = cited("smiles", chem_signals[0]["citation"])
        elif genetic_signals:
            perturbation_encoding_field = cited("gene_id", genetic_signals[0]["citation"])
        else:
            perturbation_encoding_field = unknown()

        image = repolaunch_result.docker_image if repolaunch_result else None
        # heuristic pass does not inspect the Dockerfile for CUDA base images -- left unknown, not
        # guessed. Two separate unknown() calls, deliberately -- reusing one dict object across
        # two contract fields would make PyYAML emit an anchor/alias pair and leave the two
        # fields silently sharing mutable state.
        gpu_required_field = unknown()
        compute_gpu_field = unknown()

        contract = {
            "schema_version": "1.0",
            "method_id": self.instance["instance_id"],
            "model": {
                "repo": self.artifacts.get("repo_url", ""),
                "commit": self.artifacts.get("commit_sha", "unknown"),
                "entrypoint": entrypoint_field,
            },
            "environment": {
                "image": image or "unknown",
                "dockerfile_source": "repolaunch_layer_reconstruction",
                "gpu_required": gpu_required_field,
            },
            "prediction_level": prediction_level_field,
            "input_layer": unknown(),  # requires reading the model's actual training loop -- out of scope for a static heuristic pass
            "requires_sc_counts": requires_sc_counts_field,
            "perturbation_encoding": perturbation_encoding_field,
            "gene_space": gene_space,
            "handles": {"dose": unknown(), "timepoint": unknown(), "unseen_compound": unknown(), "unseen_cell_type": unknown()},
            "compute": {"gpu": compute_gpu_field, "vram_gb": unknown(), "est_runtime_min": unknown()},
            "checkpoint": {"url": unknown(), "sha256": unknown(), "license": unknown()},
            "arguments": arguments,
            "dependencies": dependencies,
            "hyperparameters": hyperparameters,
        }

        if self.paperclip_record:
            r = self.paperclip_record
            # Not part of the strict per-field cited_field schema (this is provenance about the
            # *source*, not a scientific claim about the *model*) -- the schema doesn't restrict
            # additionalProperties, so this rides alongside without breaking validation.
            contract["paper"] = {
                "id": r.get("id"),
                "title": r.get("title"),
                "authors": r.get("authors"),
                "source": r.get("source"),
                "date": r.get("date"),
                "url": r.get("url"),
                "full_text_status": r.get("full_text_status"),
            }

        if serena_findings is not None:
            # Full findings travel with the contract as an audit trail (IMPLEMENTATION_SUMMARY.md's
            # documented design) -- every cited_field above traces back to one of these. Also not
            # part of the strict schema; rides alongside the same way "paper" does.
            contract["_serena_findings"] = serena_findings.to_dict()

        n_known = sum(
            1 for path in [entrypoint_field, requires_sc_counts_field, perturbation_encoding_field, contract["prediction_level"]]
            if path["value"] != "unknown"
        )
        engine_note = "live Serena MCP + heuristic chem/genetic grep" if serena_fields else "heuristic static analysis only"
        self.log_action("synthesize_contract", "", f"{n_known}/4 headline fields resolved from evidence ({engine_note}); rest 'unknown'", status="success")
        self.artifacts["model_contract"] = contract
        return contract

    def emit_artifacts(self) -> None:
        print("\n=== Emit artifacts ===")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        repolaunch_result: repolaunch_runner.RepoLaunchResult | None = self.artifacts.get("repolaunch_result")

        manifest = {
            "method_id": self.instance["instance_id"],
            "repo_url": self.artifacts.get("repo_url", ""),
            "resolved_commit_sha": self.artifacts.get("commit_sha", "unknown"),
            "repolaunch_status": repolaunch_result.status if repolaunch_result else "not_run",
            "docker_image": repolaunch_result.docker_image if repolaunch_result else None,
            "comprehension": self.artifacts.get("comprehension", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (self.output_dir / "repo_manifest.json").write_text(json.dumps(manifest, indent=2))

        import yaml

        contract = self.artifacts.get("model_contract", {})
        contract_path = self.output_dir / "model_contract.yaml"
        contract_path.write_text(
            "# Model Contract -- every non-'unknown' field cites PAPER_ID:Lstart-Lend or repo:file:line\n"
            "# Validated automatically against ../model_contract.schema.json at emission time.\n\n"
            + yaml.safe_dump(contract, sort_keys=False, default_flow_style=False)
        )

        # Close the loop with the other lane: validate against the exact schema
        # benchmark_adapt/harness/contract.py will use to accept or refuse this handoff. Loaded by
        # file path, not package import -- both lanes have a package literally named `harness`,
        # and a normal `from harness.contract import ...` would silently resolve against whichever
        # one Python cached first in sys.modules (this file's own `harness` package), not
        # benchmark_adapt's.
        try:
            import importlib.util

            contract_module_path = CONTRACT_GEN_ROOT.parent / "benchmark_adapt" / "harness" / "contract.py"
            spec = importlib.util.spec_from_file_location("benchmark_adapt_contract", contract_module_path)
            bench_contract = importlib.util.module_from_spec(spec)
            # Must register before exec_module: contract.py uses `from __future__ import
            # annotations` + @dataclass, whose type resolution looks itself up via
            # sys.modules[cls.__module__] -- if that lookup happens before this line, it finds
            # nothing and raises AttributeError on a None module.
            sys.modules["benchmark_adapt_contract"] = bench_contract
            spec.loader.exec_module(bench_contract)

            loaded = bench_contract.load_contract(contract_path, schema_path=SCHEMA_PATH)
            if loaded.issues:
                self.log_action("emit_contract_validation", "", error=f"{len(loaded.issues)} issue(s): {[i.message for i in loaded.issues[:3]]}", status="failure")
            else:
                self.log_action("emit_contract_validation", "", "model_contract.yaml is schema-valid and citation-clean -- consumable by benchmark_adapt as-is", status="success")
        except Exception as e:
            self.log_action("emit_contract_validation", "", error=f"could not run cross-lane validation: {e}", status="failure")

        exec_log = {
            "method_id": self.instance["instance_id"],
            "commands": self.execution_log,
            "total_wall_clock_s": sum(e.get("wall_clock_s", 0) or 0 for e in self.execution_log),
        }
        (self.output_dir / "execution_log.json").write_text(json.dumps(exec_log, indent=2))

        print(f"Wrote {self.output_dir}/{{repo_manifest.json, model_contract.yaml, execution_log.json}}")

    def run(self) -> bool:
        print("=" * 60)
        print(f"Method Integration Orchestrator: {self.instance['instance_id']}")
        print("=" * 60)

        if not self.stage_ingest():
            self.emit_artifacts()
            return False

        self.stage_environment()  # failure here is logged, not fatal -- we still emit what we learned
        self.stage_repo_comprehension()
        self.stage_synthesize_contract()
        self.emit_artifacts()

        result: repolaunch_runner.RepoLaunchResult | None = self.artifacts.get("repolaunch_result")
        print("\n" + "=" * 60)
        print(f"Done. RepoLaunch: {result.status if result else 'not run'}. Output: {self.output_dir}")
        print("=" * 60)
        return bool(result and result.status == "PASS")

    def run_contract_only(self, resume_manifest_path: Path) -> bool:
        """Re-synthesize the contract (e.g. with fresh paperclip enrichment, or a corrected
        method_id) against an already-successful RepoLaunch result, without repeating Stage 0/1 --
        RepoLaunch bills real API usage per invocation.
        """
        print("=" * 60)
        print(f"Method Integration Orchestrator (contract-only resume): {self.instance['instance_id']}")
        print("=" * 60)
        self.resume_from_manifest(resume_manifest_path)
        self.stage_synthesize_contract()
        self.emit_artifacts()
        print(f"\nDone. Output: {self.output_dir}")
        return True


def main():
    ap = argparse.ArgumentParser(description="Stage 0-3: ingest, RepoLaunch, heuristic comprehension, contract synthesis")
    ap.add_argument("--instance", type=Path, help="Path to a RepoLaunch-style instance JSON")
    ap.add_argument("--paperclip-record", type=Path, help="Path to a Paperclip literature-agent record JSON (alternative to --instance)")
    ap.add_argument("--paperclip-corpus-root", type=Path, default=None, help="Root dir Paperclip's cat_full_path etc. are relative to (omit to skip paper-text evidence)")
    ap.add_argument("--repolaunch-config", type=Path, help="Path to a RepoLaunch config template JSON (required unless --resume-from-manifest)")
    ap.add_argument("--output", required=True, type=Path, help="Output directory for this method")
    ap.add_argument("--repolaunch-timeout", type=int, default=1800)
    ap.add_argument("--resume-from-manifest", type=Path, default=None, help="Skip Stage 0/1/2 -- reuse a prior run's repo_manifest.json and only re-run contract synthesis")
    ap.add_argument(
        "--comprehension-engine", choices=["heuristic", "serena"], default="heuristic",
        help="Stage 2 engine. 'heuristic' (default) is the zero-dependency grep/regex stand-in. "
        "'serena' runs a live Serena MCP session (methods/serena/) -- requires the `serena` CLI "
        "(pip install serena-agent) and a language server for the target repo's language; see "
        "methods/README.md 'Running with live Serena'.",
    )
    args = ap.parse_args()

    if not args.instance and not args.paperclip_record:
        ap.error("one of --instance or --paperclip-record is required")

    paperclip_record = json.loads(args.paperclip_record.read_text()) if args.paperclip_record else None
    if paperclip_record:
        try:
            instance = paperclip_intake.to_repolaunch_instance(paperclip_record)
        except paperclip_intake.PaperclipRecordError as e:
            print(f"REFUSING: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        instance = json.loads(args.instance.read_text())

    repolaunch_config = json.loads(args.repolaunch_config.read_text()) if args.repolaunch_config else {}

    orchestrator = MethodIntegrationOrchestrator(
        instance, args.output, repolaunch_config,
        repolaunch_timeout_s=args.repolaunch_timeout,
        paperclip_record=paperclip_record,
        paperclip_corpus_root=args.paperclip_corpus_root,
        comprehension_engine=args.comprehension_engine,
    )

    if args.resume_from_manifest:
        ok = orchestrator.run_contract_only(args.resume_from_manifest)
    else:
        if not args.repolaunch_config:
            ap.error("--repolaunch-config is required unless --resume-from-manifest is set")
        ok = orchestrator.run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
