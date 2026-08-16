# Serena Repository Understanding Harness

Reusable, repo-agnostic semantic code analysis for method integration.

## Purpose

Extract machine-readable findings about a perturbation-prediction method repository:
- Public training and inference APIs
- Data loading and preprocessing
- Checkpoint/configuration patterns
- Prediction output structure
- Example workflows

**Serena is NOT responsible for:**
- Scientific benchmark validity
- OP3 API compatibility assessment
- Adapter generation
- Literature discovery
- Dataset preparation

## How It Works

The `SerenaRepositoryAnalyzer` class runs a standardized 8-stage query sequence against a cloned repository using Serena MCP (semantic code understanding tool).

### Stages

1. **Repository Overview** - Discover top-level package structure and symbols
2. **API Discovery** - Locate training and inference entry points
3. **Training Implementation** - Trace training code, model class, setup
4. **Inference Implementation** - Trace prediction/inference path
5. **Data Loading** - Identify data loaders, file formats, input structures
6. **Preprocessing** - Find feature extraction, gene selection, alignment operations
7. **Checkpoint/Config** - Discover model saving/loading patterns
8. **Examples** - Locate tests, notebooks, and tutorials that show full workflows

### Output Format

All findings are returned as structured objects with evidence citations:

```json
{
  "finding_type": "public_api",
  "category": "training",
  "symbol": "train",
  "file_path": "scape/_api.py",
  "line_range": [2, 41],
  "description": "Main training entry point",
  "confidence": "confirmed",
  "evidence": "Full function body obtained via Serena"
}
```

**Every non-placeholder finding includes:**
- `file_path` - Repository-relative path (no absolute paths)
- `line_range` - [start_line, end_line] (0-indexed for Serena, 1-indexed in output)
- `symbol` - Python symbol name (class/function/method) if applicable
- `confidence` - "confirmed", "partial", or "unknown"
- `evidence` - Citation/reference to how finding was obtained

## Usage

### Basic

```python
from methods.serena.harness import SerenaRepositoryAnalyzer

# Analyze a cloned repository
analyzer = SerenaRepositoryAnalyzer(repo_path="work/repo")
findings = analyzer.analyze()

# Access findings by category
print(findings.public_apis)      # training/inference entry points
print(findings.training_path)    # training implementation trace
print(findings.inference_path)   # prediction implementation trace
print(findings.data_loaders)     # data I/O functions
print(findings.preprocessing)    # feature engineering functions
print(findings.checkpoints)      # model save/load patterns
print(findings.examples)         # tests, notebooks, tutorials
```

### Integration with contract_gen

```python
from methods.serena.harness import SerenaRepositoryAnalyzer
import json

# Called during contract_gen Stage 3 (comprehension)
analyzer = SerenaRepositoryAnalyzer(repo_path=resolved_repo_path)
findings = analyzer.analyze()

# Findings feed into contract synthesis
contract = {
    "model": {
        "entrypoint": findings.public_apis.training.symbol,
        # ... other contract fields
    },
    "_serena_findings": findings.to_dict(),  # Store full findings for audit trail
}
```

## Design Principles

### Generic (Not Scoped to scAPE)

The query sequence contains NO scAPE-specific assumptions:
- No hardcoded function names (searches generically for `train()`, `predict()`)
- No hardcoded file paths (discovers structure dynamically)
- No method-specific gene lists or dataset names
- No hardcoded dependencies on specific modules

### Portable Artifacts

All output uses repo-relative paths:
- ✓ `scape/_api.py:241` 
- ✗ `/Users/...Documents/reAGENT_hackathon/methods/scape/work/repo/scape/_api.py`

### Honest About Limitations

Uses `unknown` and `pending` for genuine uncertainty:
- "unknown" = function not found or couldn't be analyzed
- "pending" = partially analyzed (e.g., symbol found but body not retrieved yet)
- No fabricated findings

### MCP-Based (Not Regex/Grep)

Uses Serena's semantic understanding (via MCP), not pattern matching:
- Symbol-aware queries
- Scope-aware search (find methods vs. module-level functions)
- Type-aware reference tracing
- Not subject to false positives from strings/comments

## Schema

See `schema.json` for the full finding object schema.

Key types:
- `public_api` - Discovered entry points (train, predict, etc.)
- `implementation` - Code bodies, implementation details
- `data_loader` - Data loading functions and formats
- `preprocessing` - Feature extraction, selection, alignment
- `checkpoint` - Model persistence patterns
- `example` - Tests, notebooks, tutorials
- `reference` - Cross-file references and dependencies

## Constraints

**Do not modify:**
- Stage query sequence (unless a stage genuinely doesn't apply)
- Evidence citation format (always include file_path and line_range)
- Confidence levels (confirmed/partial/unknown only)
- Use of portable paths

**Okay to extend:**
- Additional stages (beyond 8) if the repository requires novel queries
- New finding categories (beyond the 7 listed above)
- Confidence signals (e.g., "high", "medium", "low" alongside confirmed/partial/unknown)

## Serena MCP Connection

This harness relies on Serena being available as an MCP server with the project's language server active.

If Serena is not available or misconfigured:
- Findings will be marked as status `not_attempted` or `serena_unavailable`
- The harness does not fall back to grep/regex (maintains clean separation of concerns)
- Error handling will be explicit (no silent failures)

See `methods/contract_gen/harness/serena_utils.py` (or similar) for the actual MCP interface bindings.

## Example Output

See `fixtures/serena_findings_template.yaml` for a complete example of the findings structure (with placeholder values, to be populated by the analyzer).
