# Serena Repository Understanding Harness

Reusable, repo-agnostic semantic code analysis for method integration, backed by a **live Serena
MCP server** — not a placeholder, not a regex fallback.

## Purpose

Extract machine-readable findings about a perturbation-prediction method repository:
- Public training and inference APIs
- Data loading and preprocessing
- Checkpoint/configuration patterns
- Declared dependencies (pip/git)
- Prediction output structure
- Example workflows

**Serena is NOT responsible for:**
- Scientific benchmark validity
- OP3 API compatibility assessment
- Adapter generation
- Literature discovery
- Dataset preparation
- Classifying chemical vs. genetic perturbation encoding (contract_gen's own grep pass handles
  that — see `../contract_gen/harness/orchestrator.py`'s `_scan_chem_genetic_sc_signals`)

## How It Works

`SerenaRepositoryAnalyzer.analyze()` (`harness.py`) opens one live MCP session against a cloned
repository — spawning `serena start-mcp-server --transport stdio --project <repo>` as a subprocess
and talking the real Model Context Protocol to it (`mcp_client.py`, using the `mcp` Python SDK) —
and runs a standardized 9-stage query sequence over it.

### Stages

1. **Repository Overview** — `list_dir` + `get_symbols_overview` to discover top-level package
   structure and per-file symbols
2. **API Discovery** — `find_symbol` for generic name stems (`train`, `fit`, `predict`, `infer`)
   to locate training/inference entry points, with full bodies
3. **Training Implementation** — trace the training API's body for the class it instantiates or
   the factory function it calls (one hop into the factory's own body too, since `train() →
   create_default_model() → return SomeClass(...)` is a common pattern a single-hop trace misses)
4. **Inference Implementation** — same trace, from the inference API
5. **Data Loading** — `find_symbol(name_path_pattern="load", substring_matching=True)` to find
   `load_*`/`*_load*` functions, with signatures and bodies
6. **Preprocessing** — same substring-search pattern over `select_`/`extract_`/`split_`/`align_`/
   `normalize_`/`preprocess` stems
7. **Checkpoint/Config** — `save`/`load` methods, scoped to the class(es) found in stage 3/4 (so a
   generic data loader named `load_something` doesn't get double-counted as a checkpoint method)
8. **Examples** — test classes (`search_for_pattern` for `class Test` under a `tests/`-like dir)
   and a `__main__.py` CLI entry point, if present
9. **Dependencies** — `read_file` on `pyproject.toml` (falling back to `requirements.txt`, then
   `setup.py`), regex-extracting the declared dependency list. An explicit extension beyond the
   original 8 stages (see "Okay to extend" below) — the `model_contract.schema.json` `dependencies`
   field needs real evidence too, and a manifest file is a direct read, not a guess.

### Output Format

All findings are returned as structured objects with evidence citations:

```json
{
  "finding_type": "public_api",
  "category": "training",
  "symbol": "train",
  "file_path": "scape/_api.py",
  "line_range": [2, 41],
  "description": "Public training API entry point (matched stem 'train')",
  "confidence": "confirmed",
  "evidence": "find_symbol(name_path_pattern='train', include_body=True)"
}
```

**Every non-placeholder finding includes:**
- `file_path` - Repository-relative path (no absolute paths)
- `line_range` - [start_line, end_line], 1-indexed
- `symbol` - Python symbol name (class/function/method) if applicable
- `confidence` - "confirmed", "partial", or "unknown"
- `evidence` - The exact MCP tool call that produced the finding

## Usage

### Basic

```python
from methods.serena.harness import SerenaRepositoryAnalyzer

# Analyze a cloned repository (opens and closes one live MCP session)
analyzer = SerenaRepositoryAnalyzer(repo_path="work/repo")
findings = analyzer.analyze()

analyzer.print_summary()
analyzer.save_findings("findings.json")

# Access findings by category
print(findings.public_apis)      # training/inference entry points
print(findings.training_path)    # training implementation trace
print(findings.inference_path)   # prediction implementation trace
print(findings.data_loaders)     # data I/O functions
print(findings.preprocessing)    # feature engineering functions
print(findings.checkpoints)      # model save/load patterns
print(findings.examples)         # tests, notebooks, tutorials
```

`analyze()` is a synchronous facade — internally it runs the whole session (connect, all 9 stages,
disconnect) inside a single `asyncio.run()` call. See `mcp_client.py`'s module docstring for why
that matters: the underlying MCP session's `anyio` `TaskGroup` requires `__aenter__`/every
call/`__aexit__` to happen in the *same* asyncio Task it was opened in, which a naive "new event
loop, one `run_until_complete()` per call" wrapper violates by construction.

If `serena_status != "success"` after `analyze()`, no findings were collected — check
`findings.serena_error` (usually: `serena` CLI not on `PATH`, or the MCP handshake itself failed).

### Integration with contract_gen

```bash
cd methods/contract_gen
python -m harness.orchestrator \
    --paperclip-record fixtures/paperclip_scape_record.json \
    --repolaunch-config fixtures/repolaunch_config_scape.json \
    --comprehension-engine serena \
    --output output/scape
```

Internally (`orchestrator.py`'s `stage_repo_comprehension_serena`):

```python
from methods.serena.harness import SerenaRepositoryAnalyzer

analyzer = SerenaRepositoryAnalyzer(repo_path=str(self.repo_dir))
serena_findings = analyzer.analyze()
self.artifacts["serena_findings"] = serena_findings
```

Then `stage_synthesize_contract` calls `harness.serena_contract_mapping.findings_to_contract_fields`
(in `contract_gen/harness/`, not here — that's the part that knows about `model_contract.yaml`'s
shape) to turn findings into cited contract fields, and stores the full `RepositoryFindings.to_dict()`
under `contract["_serena_findings"]` as an audit trail.

## Design Principles

### Generic (Not Scoped to scAPE)

The query sequence contains NO scAPE-specific assumptions:
- No hardcoded function names (searches generically for `train()`, `predict()`, ...)
- No hardcoded file paths (discovers structure dynamically via `list_dir`)
- No method-specific gene lists or dataset names
- No hardcoded dependencies on specific modules

`VALIDATION_SCAPE.md` documents the scAPE-specific run that validated this; the stem lists
(`API_STEMS`, `PREPROCESSING_STEMS`, ...) in `harness.py` are the only thing method-specific
findings come from, and they're all generic naming conventions, not scAPE's own symbol names.

### Portable Artifacts

All output uses repo-relative paths:
- ✓ `scape/_api.py:2-41`
- ✗ `/Users/.../work/repo/scape/_api.py:2-41`

### Honest About Limitations

Uses `unknown`/`partial` for genuine uncertainty — a stage that finds nothing simply adds no
findings for that category; nothing is fabricated to fill a gap.

### MCP-Based (Not Regex/Grep)

Every finding here comes from Serena's semantic understanding via the real MCP protocol — symbol-
aware queries, scope-aware search (a method vs. a module-level function with the same name),
type-aware reference tracing. Not subject to false positives from strings/comments the way a grep
pass is (see `methods/README.md`'s "How Stage 2 works" for a concrete example: the heuristic path
sees `import anndata` in scAPE's *shipped OP3 component* and would guess `single_cell`; Serena
traces the actual library and finds `load_slogpvals`/`load_lfc` operate on grouped DE statistics).

## Schema

See `schema.json` for the full finding object schema.

## Constraints

**Do not modify:**
- Stage query sequence (unless a stage genuinely doesn't apply)
- Evidence citation format (always include file_path and line_range)
- Confidence levels (confirmed/partial/unknown only)
- Use of portable paths

**Okay to extend:**
- Additional stages (beyond 9) if the repository requires novel queries — stage 9
  (dependencies) is itself an example of exercising this: it wasn't in the original design, but
  `model_contract.yaml`'s `dependencies` field needed real evidence from somewhere.
- New finding categories (beyond the 7 `type` values in `schema.json`)
- Confidence signals (e.g., "high", "medium", "low" alongside confirmed/partial/unknown)

## Serena MCP Connection

This harness needs `serena-agent` (provides the `serena` CLI) and `mcp` installed in the active
Python environment — both are in `../requirements.txt`. Verify with:

```bash
serena --help                 # confirms serena-agent is installed and its CLI resolves
python -c "import mcp"        # confirms the MCP client SDK is importable
```

`mcp_client.py` spawns `serena start-mcp-server --transport stdio --project <repo> --context agent
--enable-web-dashboard False --open-web-dashboard False` per analysis and talks to it as a real MCP
client (`mcp.ClientSession` over `mcp.client.stdio.stdio_client`) — the same mechanism an IDE or
agent host uses when Serena is registered as an MCP server, just driven from Python instead of a
chat client. No separate language-server install is needed for Python repositories (`multilspy`,
one of `serena-agent`'s own dependencies, manages that automatically); other languages may need
their own language server available, per Serena's own docs.

If `serena` isn't on `PATH` or the handshake fails, `SerenaMCPClient.__aenter__` raises
`SerenaUnavailableError`; `SerenaRepositoryAnalyzer.analyze()` catches it, sets
`findings.serena_status = "unavailable"`, and returns zero findings rather than falling back to
grep/regex (see "MCP-Based" above — that's a deliberate line this harness does not cross).

## Example Output

See `fixtures/serena_findings_scape.json` for hand-validated example output (see
`VALIDATION_SCAPE.md`), and `fixtures/serena_findings_scape_live.json` for the output of an actual
live `analyze()` run against the real `scapeML/scape` repo — 35 findings, reproducing (and in a few
places exceeding — e.g. `SCAPE/save`/`SCAPE/load` checkpoint findings the original validation round
missed) the hand-validated set.
