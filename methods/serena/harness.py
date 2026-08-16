"""
Serena Repository Understanding Harness

Portable, repo-agnostic semantic code analysis for method integration.
Uses Serena MCP for symbol-aware, scope-aware repository inspection.

All findings are repository-relative (no absolute paths).
Confidence levels: "confirmed" (fully verified), "partial" (incomplete), "unknown" (not found).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Note: Actual Serena MCP invocation would happen here
# For now, this is the interface that downstream code would use


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
        self.analysis_timestamp = datetime.utcnow().isoformat() + "Z"
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
        return json.dumps(self.to_dict(), indent=indent)


class SerenaRepositoryAnalyzer:
    """
    Orchestrates Serena MCP queries to analyze a Python method repository.

    Runs 8 standardized stages:
    1. Repository overview
    2. API discovery
    3. Training implementation
    4. Inference implementation
    5. Data loading
    6. Preprocessing
    7. Checkpoints/config
    8. Examples

    All findings preserve repository-relative paths and evidence citations.
    """

    def __init__(self, repo_path: str):
        """
        Initialize analyzer for a repository.

        Args:
            repo_path: Path to cloned repository (can be relative to project root)
        """
        self.repo_path = str(repo_path)
        self.findings = RepositoryFindings(self.repo_path)
        self._serena_available = False

    def analyze(self) -> RepositoryFindings:
        """
        Run full 8-stage repository analysis.

        Returns:
            RepositoryFindings object with all discoveries
        """
        # Check Serena availability
        try:
            self._check_serena_availability()
        except Exception as e:
            self.findings.serena_status = "unavailable"
            self.findings.serena_error = str(e)
            return self.findings

        # Run analysis stages
        self._stage_1_repository_overview()
        self._stage_2_api_discovery()
        self._stage_3_training_implementation()
        self._stage_4_inference_implementation()
        self._stage_5_data_loading()
        self._stage_6_preprocessing()
        self._stage_7_checkpoints_config()
        self._stage_8_examples()

        self.findings.serena_status = "success"
        return self.findings

    def _check_serena_availability(self) -> None:
        """Verify Serena MCP is available (placeholder)."""
        # In actual implementation, this would call Serena's initial_instructions
        # to verify the MCP server is running
        # For now, we mark this as a needed integration point
        pass

    def _stage_1_repository_overview(self) -> None:
        """
        Stage 1: Discover top-level package structure.

        Queries:
        - What are the top-level Python packages/modules?
        - What's in __init__.py for the main package?
        - What are the main submodules?
        """
        # Placeholder - would call Serena to get_symbols_overview
        # on main package (usually named after the method)
        pass

    def _stage_2_api_discovery(self) -> None:
        """
        Stage 2: Discover public APIs (training, inference).

        Queries:
        - Find any function named 'train' with include_info=True
        - Find any function named 'predict' with include_info=True
        - Find classes with .train() and .predict() methods
        - Find 'api', '_api', 'interface' modules with top-level functions
        """
        # Placeholder - would call Serena to find_symbol for:
        # - "train" (module-level function)
        # - "*/train" (method of any class)
        # - "predict" (module-level function)
        # - "*/predict" (method of any class)
        pass

    def _stage_3_training_implementation(self) -> None:
        """
        Stage 3: Trace training implementation.

        Queries (following public training API):
        - Get full body of training function/method
        - Identify what class/model is instantiated
        - Trace dependencies (what modules/functions are called)
        - Find feature extraction, split, training loop
        """
        # Placeholder - would:
        # 1. Call find_symbol with include_body=True for training function
        # 2. Find the main Model/SCAPE class
        # 3. Trace feature extraction and model setup calls
        pass

    def _stage_4_inference_implementation(self) -> None:
        """
        Stage 4: Trace inference/prediction implementation.

        Queries (following public prediction API):
        - Get full body of predict function/method
        - Identify input validation and transformation
        - Trace feature extraction at prediction time
        - Find model.predict() call and output handling
        """
        # Placeholder - would:
        # 1. Call find_symbol with include_body=True for prediction function
        # 2. Trace feature extraction and input mapping
        # 3. Find model.predict() call and output format
        pass

    def _stage_5_data_loading(self) -> None:
        """
        Stage 5: Discover data loaders and input formats.

        Queries:
        - Find any function named 'load*' (load, load_data, load_parquet, etc.)
        - Get signature and first lines of each loader
        - Identify expected input file format (parquet, csv, etc.)
        - Trace what columns/indices are used
        """
        # Placeholder - would:
        # 1. find_symbol for "load*" with substring_matching=True
        # 2. For each loader, get signature and body snippet
        # 3. Identify file format and structure from code
        pass

    def _stage_6_preprocessing(self) -> None:
        """
        Stage 6: Discover preprocessing/feature construction.

        Queries:
        - Find feature extraction functions (extract_features, get_features, etc.)
        - Find gene/feature selection (select_top_variable, select_features, etc.)
        - Find alignment operations (align, match, subset, etc.)
        - Find normalization/scaling functions
        """
        # Placeholder - would:
        # 1. find_symbol for feature extraction functions
        # 2. find_symbol for selection functions
        # 3. find_symbol for alignment operations
        # 4. For each, get signature and trace calls
        pass

    def _stage_7_checkpoints_config(self) -> None:
        """
        Stage 7: Discover checkpoint and config patterns.

        Queries:
        - Find .save() methods (what files are created?)
        - Find .load() methods (what files are read?)
        - Identify serialization format (pickle, keras, etc.)
        - Find where config/setup is stored
        """
        # Placeholder - would:
        # 1. find_symbol for "save" methods on main class
        # 2. find_symbol for "load" methods or functions
        # 3. Trace what gets pickled, saved, or serialized
        pass

    def _stage_8_examples(self) -> None:
        """
        Stage 8: Locate examples, tests, and tutorials.

        Queries:
        - Find test files (test_*.py, *_test.py)
        - Find example notebooks (*.ipynb)
        - Find CLI entry points (__main__.py, scripts/)
        - Get symbols overview of test classes (what workflows do they demonstrate?)
        """
        # Placeholder - would:
        # 1. Search for test files
        # 2. Search for notebooks
        # 3. Find __main__.py or cli functions
        # 4. Extract key test cases that show full workflows
        pass

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
        print(f"Total findings: {len(self.findings.all_findings)}")
        print(f"\nPublic APIs: {len(self.findings.public_apis)}")
        print(f"Training path: {len(self.findings.training_path)} findings")
        print(f"Inference path: {len(self.findings.inference_path)} findings")
        print(f"Data loaders: {len(self.findings.data_loaders)}")
        print(f"Preprocessing: {len(self.findings.preprocessing)}")
        print(f"Checkpoints: {len(self.findings.checkpoints)}")
        print(f"Examples: {len(self.findings.examples)}")
