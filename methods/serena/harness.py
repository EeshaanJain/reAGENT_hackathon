"""
Serena Repository Understanding Harness

Portable, repo-agnostic semantic code analysis for method integration.
Uses a live Serena MCP server (mcp_client.py) for symbol-aware, scope-aware repository inspection.

All findings are repository-relative (no absolute paths).
Confidence levels: "confirmed" (fully verified), "partial" (incomplete), "unknown" (not found).
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from .mcp_client import SerenaMCPClient, SerenaUnavailableError


class Finding:
    """A single repository finding with evidence citation."""

    def __init__(
        self,
        type_: str,
        category: str,
        file_path: str,
        line_range: Optional[List[int]] = None,
        symbol: Optional[str] = None,
        description: str = "unknown",
        confidence: str = "unknown",
        evidence: str = "",
        signature: Optional[str] = None,
        body_snippet: Optional[str] = None,
        related_symbols: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ):
        self.type = type_
        self.category = category
        self.file_path = file_path  # Repository-relative, never absolute
        self.line_range = line_range
        self.symbol = symbol
        self.description = description
        self.confidence = confidence
        self.evidence = evidence
        self.signature = signature
        self.body_snippet = body_snippet
        self.related_symbols = related_symbols or []
        self.dependencies = dependencies or []
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "type": self.type,
            "category": self.category,
            "file_path": self.file_path,
            "confidence": self.confidence,
            "description": self.description,
            "evidence": self.evidence,
        }
        if self.line_range:
            result["line_range"] = self.line_range
        if self.symbol:
            result["symbol"] = self.symbol
        if self.signature:
            result["signature"] = self.signature
        if self.body_snippet:
            result["body_snippet"] = self.body_snippet
        if self.related_symbols:
            result["related_symbols"] = self.related_symbols
        if self.dependencies:
            result["dependencies"] = self.dependencies
        if self.notes:
            result["notes"] = self.notes
        return result


class RepositoryFindings:
    """Container for all findings from a repository analysis."""

    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.analysis_timestamp = datetime.now(timezone.utc).isoformat()
        self.serena_status = "not_attempted"
        self.serena_error = None
        self.all_findings: List[Finding] = []

    def add_finding(self, finding: Finding) -> None:
        """Add a finding to the collection."""
        self.all_findings.append(finding)

    @property
    def public_apis(self) -> List[Finding]:
        """All public API entry points (training, inference, etc.)."""
        return [f for f in self.all_findings if f.type == "public_api"]

    @property
    def training_path(self) -> List[Finding]:
        """Training implementation findings."""
        return [
            f for f in self.all_findings
            if f.type == "implementation" and f.category == "training"
        ]

    @property
    def inference_path(self) -> List[Finding]:
        """Inference/prediction implementation findings."""
        return [
            f for f in self.all_findings
            if f.type == "implementation" and f.category == "inference"
        ]

    @property
    def data_loaders(self) -> List[Finding]:
        """Data loading functions and formats."""
        return [f for f in self.all_findings if f.type == "data_loader"]

    @property
    def preprocessing(self) -> List[Finding]:
        """Preprocessing, feature extraction, alignment."""
        return [f for f in self.all_findings if f.type == "preprocessing"]

    @property
    def checkpoints(self) -> List[Finding]:
        """Checkpoint, config, model persistence patterns."""
        return [f for f in self.all_findings if f.type == "checkpoint"]

    @property
    def examples(self) -> List[Finding]:
        """Tests, notebooks, tutorials, examples."""
        return [f for f in self.all_findings if f.type == "example"]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "analysis_timestamp": self.analysis_timestamp,
            "repo_path": self.repo_path,
            "serena_status": self.serena_status,
            "serena_error": self.serena_error,
            "findings": [f.to_dict() for f in self.all_findings],
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        import json

        return json.dumps(self.to_dict(), indent=indent)


class SerenaRepositoryAnalyzer:
    """
    Orchestrates live Serena MCP queries to analyze a Python method repository.

    Runs 8 standardized stages:
    1. Repository overview
    2. API discovery
    3. Training implementation
    4. Inference implementation
    5. Data loading
    6. Preprocessing
    7. Checkpoints/config
    8. Examples

    All findings preserve repository-relative paths and evidence citations. Every query is a real
    call against a `serena start-mcp-server` subprocess (see mcp_client.py) -- there is no
    regex/grep fallback if the MCP connection can't be established; the whole analysis is marked
    serena_status="unavailable" instead (see analyze()).

    None of the stem lists below (API_STEMS, PREPROCESSING_STEMS, ...) are scAPE-specific -- they
    describe common ML-repository naming conventions (train/fit, predict/infer, select_/extract_/
    split_, save/load), not scape's own symbol names. See VALIDATION_SCAPE.md for the repo this was
    validated against, and IMPLEMENTATION_SUMMARY.md's "Recommendations for Next Methods" for how
    these same stems are expected to generalize to a PyTorch/sklearn method.
    """

    EXCLUDE_DIRS = {
        "tests", "test", "docs", "doc", "examples", "notebooks", "scripts",
        ".git", ".github", ".serena", "build", "dist", "__pycache__", ".venv", "venv", "node_modules",
    }
    API_STEMS = ["train", "fit", "predict", "infer"]
    PREPROCESSING_STEMS = ["select_", "extract_", "split_", "align_", "normalize_", "preprocess"]
    LOADER_STEM = "load"
    MAX_OVERVIEW_FILES = 25
    MAX_LOADER_FINDINGS = 8
    MAX_PREPROCESSING_PER_STEM = 4
    MAX_CLASS_CANDIDATES_PER_API = 3
    MAX_FACTORY_CANDIDATES_PER_API = 3

    _SIG_RE = re.compile(r"def\s+\w+\s*\(.*?\)\s*(?:->\s*[^:]+)?:", re.S)
    _CLASS_CALL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(")
    _FACTORY_CALL_RE = re.compile(r"\b((?:create|build|make|get|setup|init)_[a-z_0-9]+)\s*\(")
    _BUILTIN_CLASS_NAMES = {"None", "True", "False", "Exception", "ValueError", "TypeError", "KeyError"}
    _PYPROJECT_DEPS_RE = re.compile(r"^dependencies\s*=\s*\[(.*?)\]", re.S | re.M)
    _SETUP_PY_DEPS_RE = re.compile(r"install_requires\s*=\s*\[(.*?)\]", re.S)
    _QUOTED_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')

    def __init__(self, repo_path: str):
        """
        Initialize analyzer for a repository.

        Args:
            repo_path: Path to cloned repository (can be relative to project root)
        """
        self.repo_path = str(repo_path)
        self.findings = RepositoryFindings(self.repo_path)
        self._client: Optional[SerenaMCPClient] = None
        self._main_package: Optional[str] = None

    def analyze(self) -> RepositoryFindings:
        """
        Run full 8-stage repository analysis against a live Serena MCP server.

        Synchronous facade over `_analyze_async()` -- the whole session (connect, all 8 stages,
        disconnect) runs inside one asyncio.run() call, i.e. one top-level Task, because the
        underlying MCP session's anyio TaskGroup requires __aenter__/every call/__aexit__ to run in
        the same Task it was opened in (see mcp_client.py's module docstring).

        Returns:
            RepositoryFindings object with all discoveries
        """
        import asyncio

        try:
            asyncio.run(self._analyze_async())
            self.findings.serena_status = "success"
        except SerenaUnavailableError as e:
            self.findings.serena_status = "unavailable"
            self.findings.serena_error = str(e)
        finally:
            self._client = None

        return self.findings

    async def _analyze_async(self) -> None:
        async with SerenaMCPClient(self.repo_path) as client:
            self._client = client
            await self._stage_1_repository_overview()
            await self._stage_2_api_discovery()
            await self._stage_3_training_implementation()
            await self._stage_4_inference_implementation()
            await self._stage_5_data_loading()
            await self._stage_6_preprocessing()
            await self._stage_7_checkpoints_config()
            await self._stage_8_examples()
            await self._stage_9_dependencies()

    # ---- helpers ----

    def _is_excluded(self, path: str) -> bool:
        parts = Path(path).parts
        return any(p in self.EXCLUDE_DIRS for p in parts)

    def _extract_signature(self, body: Optional[str]) -> Optional[str]:
        if not body:
            return None
        m = self._SIG_RE.search(body)
        if not m:
            return None
        return re.sub(r"\s+", " ", m.group(0)).strip()[:500]

    def _candidate_class_names(self, body: Optional[str]) -> List[str]:
        if not body:
            return []
        seen: List[str] = []
        for name in self._CLASS_CALL_RE.findall(body):
            if name in self._BUILTIN_CLASS_NAMES or name in seen:
                continue
            seen.append(name)
        return seen[: self.MAX_CLASS_CANDIDATES_PER_API]

    def _candidate_factory_names(self, body: Optional[str]) -> List[str]:
        if not body:
            return []
        seen: List[str] = []
        for name in self._FACTORY_CALL_RE.findall(body):
            if name in seen:
                continue
            seen.append(name)
        return seen[: self.MAX_FACTORY_CANDIDATES_PER_API]

    async def _guess_main_package(self, dirs: List[str]) -> Optional[str]:
        candidates = [d for d in dirs if d not in self.EXCLUDE_DIRS]
        repo_name = Path(self.repo_path).name.replace("-", "_")
        if repo_name in candidates:
            return repo_name
        for d in candidates:
            try:
                sub = await self._client.call("list_dir", relative_path=d, recursive=False)
            except SerenaUnavailableError:
                continue
            # list_dir's "files"/"dirs" are always project-root-relative, never relative to the
            # queried directory -- so "__init__.py" is found as "<d>/__init__.py" here, not bare.
            if isinstance(sub, dict) and f"{d}/__init__.py" in sub.get("files", []):
                return d
        return candidates[0] if candidates else None

    @staticmethod
    def _leading_line_number(line: str) -> Optional[int]:
        # search_for_pattern lines look like "  >  31:class TestDataLoading:" (0-indexed in the
        # tool, reported here 1-indexed same as everywhere else in this harness's output).
        m = re.match(r"^\s*>?\s*(\d+):", line)
        return int(m.group(1)) + 1 if m else None

    # ---- stages ----

    async def _stage_1_repository_overview(self) -> None:
        """Stage 1: discover top-level package structure via list_dir + get_symbols_overview."""
        listing = await self._client.call("list_dir", relative_path=".", recursive=False)
        dirs = listing.get("dirs", []) if isinstance(listing, dict) else []
        self.findings.add_finding(Finding(
            type_="reference", category="repository_structure", file_path=".",
            description=f"Top-level entries: dirs={dirs}", confidence="confirmed",
            evidence="list_dir(relative_path='.', recursive=False)",
        ))

        main_pkg = await self._guess_main_package(dirs)
        self._main_package = main_pkg
        if main_pkg is None:
            return

        try:
            pkg_listing = await self._client.call("list_dir", relative_path=main_pkg, recursive=False)
        except SerenaUnavailableError:
            return
        # "files" here are already project-root-relative (e.g. "scape/_api.py"), not bare
        # filenames -- see mcp_client.py / _guess_main_package's note on list_dir's path semantics.
        py_files = [f for f in pkg_listing.get("files", []) if f.endswith(".py")] if isinstance(pkg_listing, dict) else []

        for rel in py_files[: self.MAX_OVERVIEW_FILES]:
            try:
                overview = await self._client.call("get_symbols_overview", relative_path=rel)
            except SerenaUnavailableError:
                continue
            category = "package_overview" if rel.endswith("__init__.py") else "module_overview"
            self.findings.add_finding(Finding(
                type_="reference", category=category, file_path=rel,
                description=f"Symbols overview: {overview}", confidence="confirmed",
                evidence=f"get_symbols_overview(relative_path='{rel}')",
            ))

    async def _stage_2_api_discovery(self) -> None:
        """Stage 2: discover public training/inference APIs by generic name-stem search."""
        for stem in self.API_STEMS:
            try:
                matches = await self._client.call(
                    "find_symbol", name_path_pattern=stem, substring_matching=False, include_body=True
                )
            except SerenaUnavailableError:
                continue
            category = "training" if stem in ("train", "fit") else "inference"
            for m in matches or []:
                if m.get("kind") not in ("Function", "Method") or self._is_excluded(m.get("relative_path", "")):
                    continue
                body = m.get("body")
                loc = m.get("body_location", {})
                self.findings.add_finding(Finding(
                    type_="public_api", category=category, symbol=m.get("name_path"),
                    file_path=m.get("relative_path"),
                    line_range=[loc.get("start_line"), loc.get("end_line")] if loc else None,
                    description=f"Public {category} API entry point (matched stem '{stem}')",
                    confidence="confirmed",
                    evidence=f"find_symbol(name_path_pattern='{stem}', include_body=True)",
                    signature=self._extract_signature(body),
                    body_snippet=(body or "")[:1200] or None,
                ))

    async def _trace_class(self, cls_name: str, target_category: str, evidence_suffix: str) -> None:
        try:
            matches = await self._client.call("find_symbol", name_path_pattern=cls_name, include_body=False, depth=1)
        except SerenaUnavailableError:
            return
        for m in matches or []:
            if m.get("kind") != "Class" or self._is_excluded(m.get("relative_path", "")):
                continue
            children = m.get("children", {}) or {}
            method_names = [c.get("name") for c in children.get("Method", [])]
            loc = m.get("body_location", {})
            self.findings.add_finding(Finding(
                type_="implementation", category=target_category, symbol=m.get("name_path"),
                file_path=m.get("relative_path"),
                line_range=[loc.get("start_line"), loc.get("end_line")] if loc else None,
                description=f"Class instantiated {evidence_suffix}",
                confidence="confirmed",
                evidence=f"find_symbol(name_path_pattern='{cls_name}', depth=1) -- referenced {evidence_suffix}",
                related_symbols=[f"{cls_name}/{mn}" for mn in method_names if mn],
            ))

    async def _trace_implementation(self, api_findings: List[Finding], target_category: str) -> None:
        """Shared logic for stages 3/4: follow a public API's body to the class/factory it calls,
        one hop further into any factory function's own body -- a `train()` that just calls
        `create_default_model(...)` (a snake_case factory, not a PascalCase constructor) needs its
        factory's body inspected too to find what class it actually builds and returns.
        """
        seen: set = set()
        for api in api_findings:
            body = api.body_snippet
            for cls_name in self._candidate_class_names(body):
                if cls_name in seen:
                    continue
                seen.add(cls_name)
                await self._trace_class(cls_name, target_category, f"in {api.symbol}'s body")

            for fn_name in self._candidate_factory_names(body):
                if fn_name in seen:
                    continue
                seen.add(fn_name)
                try:
                    matches = await self._client.call("find_symbol", name_path_pattern=fn_name, include_body=True)
                except SerenaUnavailableError:
                    continue
                for m in matches or []:
                    if m.get("kind") != "Function" or self._is_excluded(m.get("relative_path", "")):
                        continue
                    fbody = m.get("body")
                    loc = m.get("body_location", {})
                    self.findings.add_finding(Finding(
                        type_="implementation", category=target_category, symbol=m.get("name_path"),
                        file_path=m.get("relative_path"),
                        line_range=[loc.get("start_line"), loc.get("end_line")] if loc else None,
                        description=f"Factory/setup function referenced from the {target_category} API ('{fn_name}')",
                        confidence="confirmed",
                        evidence=f"find_symbol(name_path_pattern='{fn_name}', include_body=True) -- referenced in {api.symbol}'s body",
                        body_snippet=(fbody or "")[:1200] or None,
                    ))
                    for cls_name in self._candidate_class_names(fbody):
                        if cls_name in seen:
                            continue
                        seen.add(cls_name)
                        await self._trace_class(cls_name, target_category, f"in factory '{fn_name}'s body (called from {api.symbol})")

    async def _stage_3_training_implementation(self) -> None:
        """Stage 3: trace the class/factory the training API instantiates."""
        await self._trace_implementation(
            [f for f in self.findings.all_findings if f.type == "public_api" and f.category == "training"],
            target_category="training",
        )

    async def _stage_4_inference_implementation(self) -> None:
        """Stage 4: trace the class/factory the inference API instantiates."""
        await self._trace_implementation(
            [f for f in self.findings.all_findings if f.type == "public_api" and f.category == "inference"],
            target_category="inference",
        )

    async def _stage_5_data_loading(self) -> None:
        """Stage 5: discover data loaders by generic substring search on 'load'."""
        try:
            matches = await self._client.call(
                "find_symbol", name_path_pattern=self.LOADER_STEM, substring_matching=True, include_body=False
            )
        except SerenaUnavailableError:
            return

        count = 0
        for m in matches or []:
            if count >= self.MAX_LOADER_FINDINGS:
                break
            if m.get("kind") != "Function" or self._is_excluded(m.get("relative_path", "")):
                continue
            count += 1
            body = None
            try:
                detail = await self._client.call(
                    "find_symbol", name_path_pattern=m["name_path"], relative_path=m["relative_path"], include_body=True
                )
                if detail:
                    body = detail[0].get("body")
            except (SerenaUnavailableError, KeyError, IndexError):
                pass
            loc = m.get("body_location", {})
            self.findings.add_finding(Finding(
                type_="data_loader", category=m.get("name_path", "").split("/")[-1], symbol=m.get("name_path"),
                file_path=m.get("relative_path"),
                line_range=[loc.get("start_line"), loc.get("end_line")] if loc else None,
                description=f"Data loading function matching '*{self.LOADER_STEM}*'",
                confidence="confirmed" if body else "partial",
                evidence=f"find_symbol(name_path_pattern='{self.LOADER_STEM}', substring_matching=True)",
                signature=self._extract_signature(body) if body else None,
                body_snippet=(body or "")[:800] or None,
            ))

    async def _stage_6_preprocessing(self) -> None:
        """Stage 6: discover feature selection/extraction/alignment functions by generic stems."""
        for stem in self.PREPROCESSING_STEMS:
            try:
                matches = await self._client.call(
                    "find_symbol", name_path_pattern=stem, substring_matching=True, include_body=True
                )
            except SerenaUnavailableError:
                continue
            kept = 0
            for m in matches or []:
                if kept >= self.MAX_PREPROCESSING_PER_STEM:
                    break
                if m.get("kind") != "Function" or self._is_excluded(m.get("relative_path", "")):
                    continue
                kept += 1
                body = m.get("body")
                loc = m.get("body_location", {})
                self.findings.add_finding(Finding(
                    type_="preprocessing", category=stem.rstrip("_"), symbol=m.get("name_path"),
                    file_path=m.get("relative_path"),
                    line_range=[loc.get("start_line"), loc.get("end_line")] if loc else None,
                    description=f"Preprocessing function matching '{stem}*'", confidence="confirmed",
                    evidence=f"find_symbol(name_path_pattern='{stem}', substring_matching=True, include_body=True)",
                    signature=self._extract_signature(body), body_snippet=(body or "")[:800] or None,
                ))

    async def _stage_7_checkpoints_config(self) -> None:
        """Stage 7: discover save/load methods scoped to the implementation class(es) from stage 3."""
        impl_classes = {f.symbol for f in self.findings.all_findings if f.type == "implementation" and f.symbol}
        for stem in ("save", "load"):
            try:
                matches = await self._client.call(
                    "find_symbol", name_path_pattern=stem, substring_matching=True, include_body=False
                )
            except SerenaUnavailableError:
                continue
            for m in matches or []:
                if m.get("kind") != "Method" or self._is_excluded(m.get("relative_path", "")):
                    continue
                name_path = m.get("name_path", "")
                owner = name_path.split("/")[0] if "/" in name_path else None
                if owner not in impl_classes:
                    continue
                loc = m.get("body_location", {})
                self.findings.add_finding(Finding(
                    type_="checkpoint", category=stem, symbol=name_path, file_path=m.get("relative_path"),
                    line_range=[loc.get("start_line"), loc.get("end_line")] if loc else None,
                    description=f"Model {stem} method on implementation class '{owner}'", confidence="confirmed",
                    evidence=f"find_symbol(name_path_pattern='{stem}', substring_matching=True) -- method of '{owner}' (found in stage 3/4)",
                ))

    async def _stage_8_examples(self) -> None:
        """Stage 8: locate test classes and a CLI entry point, if present."""
        try:
            listing = await self._client.call("list_dir", relative_path=".", recursive=False)
        except SerenaUnavailableError:
            return
        dirs = listing.get("dirs", []) if isinstance(listing, dict) else []

        for td in [d for d in dirs if d.lower() in ("tests", "test")]:
            try:
                classes = await self._client.call(
                    "search_for_pattern", substring_pattern="class Test", paths_include_glob=f"{td}/*.py"
                )
            except SerenaUnavailableError:
                continue
            for file_path, lines in (classes or {}).items():
                for line in lines:
                    m = re.search(r"class\s+(\w+)", line)
                    if not m:
                        continue
                    line_no = self._leading_line_number(line)
                    self.findings.add_finding(Finding(
                        type_="example", category="test", symbol=m.group(1), file_path=file_path,
                        line_range=[line_no, line_no] if line_no else None,
                        description="Test class demonstrating a workflow", confidence="partial",
                        evidence=f"search_for_pattern(substring_pattern='class Test', paths_include_glob='{td}/*.py')",
                    ))

        if self._main_package:
            try:
                pkg_listing = await self._client.call("list_dir", relative_path=self._main_package, recursive=False)
            except SerenaUnavailableError:
                pkg_listing = {}
            main_path = f"{self._main_package}/__main__.py"
            if isinstance(pkg_listing, dict) and main_path in pkg_listing.get("files", []):
                self.findings.add_finding(Finding(
                    type_="example", category="entrypoint", symbol="main",
                    file_path=main_path,
                    description="CLI entry point (python -m <package>)", confidence="partial",
                    evidence=f"list_dir(relative_path='{self._main_package}') found __main__.py",
                ))

    async def _stage_9_dependencies(self) -> None:
        """Stage 9 (extension beyond the standard 8 -- explicitly allowed, see the class docstring
        and README.md's "Okay to extend"): read the repo's own dependency manifest.

        The model_contract's `dependencies` field (methods/model_contract.schema.json) needs real
        evidence too, and pyproject.toml/setup.py/requirements.txt are a direct read (via Serena's
        read_file) rather than a guess. Stops at the first manifest that actually yields a
        dependency list -- doesn't double-report the same information from multiple files.
        """
        for manifest, extractor in (
            ("pyproject.toml", self._extract_pyproject_deps),
            ("requirements.txt", self._extract_requirements_txt_deps),
            ("setup.py", self._extract_setup_py_deps),
        ):
            try:
                text = await self._client.call("read_file", relative_path=manifest)
            except SerenaUnavailableError:
                continue
            if not isinstance(text, str) or not text.strip():
                continue
            deps, line_no = extractor(text)
            if not deps:
                continue
            self.findings.add_finding(Finding(
                type_="reference", category="dependencies", file_path=manifest,
                line_range=[line_no, line_no] if line_no else None,
                description=f"Declared dependencies: {deps}", confidence="confirmed",
                evidence=f"read_file(relative_path='{manifest}')",
                dependencies=deps,
            ))
            return

    @classmethod
    def _extract_pyproject_deps(cls, text: str) -> tuple[List[str], Optional[int]]:
        m = cls._PYPROJECT_DEPS_RE.search(text)
        if not m:
            return [], None
        deps = [a or b for a, b in cls._QUOTED_RE.findall(m.group(1))]
        return deps, text[: m.start()].count("\n") + 1

    @staticmethod
    def _extract_requirements_txt_deps(text: str) -> tuple[List[str], Optional[int]]:
        deps = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
        return deps, 1 if deps else None

    @classmethod
    def _extract_setup_py_deps(cls, text: str) -> tuple[List[str], Optional[int]]:
        m = cls._SETUP_PY_DEPS_RE.search(text)
        if not m:
            return [], None
        deps = [a or b for a, b in cls._QUOTED_RE.findall(m.group(1))]
        return deps, text[: m.start()].count("\n") + 1

    def save_findings(self, output_path: str) -> None:
        """
        Save findings to JSON file.

        Args:
            output_path: Where to write the findings JSON
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w") as f:
            f.write(self.findings.to_json())

    def print_summary(self) -> None:
        """Print a human-readable summary of findings."""
        print(f"\n=== Serena Analysis Summary ===")
        print(f"Repository: {self.repo_path}")
        print(f"Status: {self.findings.serena_status}")
        if self.findings.serena_error:
            print(f"Error: {self.findings.serena_error}")
        print(f"Total findings: {len(self.findings.all_findings)}")
        print(f"\nPublic APIs: {len(self.findings.public_apis)}")
        print(f"Training path: {len(self.findings.training_path)} findings")
        print(f"Inference path: {len(self.findings.inference_path)} findings")
        print(f"Data loaders: {len(self.findings.data_loaders)}")
        print(f"Preprocessing: {len(self.findings.preprocessing)}")
        print(f"Checkpoints: {len(self.findings.checkpoints)}")
        print(f"Examples: {len(self.findings.examples)}")
