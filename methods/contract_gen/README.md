# contract_gen — Cecilia's lane (Stage 0–3)

This is the upstream half of the method-integration workstream described in
[`../planning/plan_unified.md`](../planning/plan_unified.md) and audited in
[`../planning/method-integration-todo.html`](../planning/method-integration-todo.html). It owns everything up to
the handoff point — given a paper's repo, it produces `model_contract.yaml` + a built Docker
image + `execution_log.json` — and hands that to [`../benchmark_adapt/`](../benchmark_adapt/)
(Sei's lane, Stage 4–6), which turns it into a PR-ready Viash component.

It does **not** synthesize adapters, run the Gauntlet, or open PRs — that's the other lane.

```
paper repo + pinned commit  ──►  [Stage 0] ingest  ──►  [Stage 1] RepoLaunch  ──►  [Stage 2] repo
                                    (this repo)          builds a real Docker      comprehension
                                                          image (this repo)        (this repo --
                                                                                     heuristic grep,
                                                                                     or live Serena
                                                                                     MCP -- see below)
                                                                                        │
                                                                                        ▼
                                                                          [Stage 3] contract synthesis
                                                                                (this repo)
                                                                                        │
                                                                                        ▼
                                                     model_contract.yaml + image + execution_log.json
                                                                    ──► benchmark_adapt/ (Sei's lane)
```

## Layout

```
contract_gen/
  RepoLaunch/                        git submodule, pinned (microsoft/RepoLaunch) -- NOT on PyPI,
                                      vendored + pinned by commit per todo.html item C1. Its own
                                      .venv (Python >= 3.12) lives here too, gitignored by the
                                      submodule's own .gitignore.
  harness/
    orchestrator.py                  Stages 0/2/3 driver: ingest, repo comprehension (heuristic
                                      grep by default, or live Serena MCP with
                                      --comprehension-engine serena), schema-conformant contract
                                      synthesis
    repolaunch_runner.py             Stage 1: real `launch` CLI wrapper, generalized from
                                      Cecilia's original scAPE-only smoke test
    paperclip_intake.py              Parses a Paperclip literature-agent record into a RepoLaunch
                                      instance -- the standard input path (see Quickstart)
    serena_contract_mapping.py       Maps a methods/serena RepositoryFindings object into
                                      model_contract.yaml cited fields (entrypoint,
                                      prediction_level, requires_sc_counts, gene_space,
                                      hyperparameters, arguments, dependencies) -- what
                                      --comprehension-engine serena actually feeds Stage 3
  fixtures/
    paperclip_scape_record.json      scAPE test input -- a real Paperclip record
    repolaunch_config_scape.json     scAPE RepoLaunch run config (model, steps, timeouts --
                                      orthogonal to the paperclip record, always required)
    paperclip_cpa_record.json        CPA test input -- the single-cell-counts test case, a real
                                      Paperclip-format record
    repolaunch_config_cpa.json       CPA RepoLaunch run config
  smoke_tests/
    test_repolaunch_scape.py         narrow test of just the RepoLaunch integration in isolation
    results/                         gitignored -- smoke test output lands here
  docs/
    REPOLAUNCH_SMOKE_TEST.md
  output/                            gitignored -- per-method contract_gen output lands here:
                                      output/<method_id>/{model_contract.yaml, repo_manifest.json,
                                      execution_log.json}
  work/                              gitignored -- scratch clones + RepoLaunch workspaces
```

The shared contract schema (`model_contract.schema.json`) lives one level up, at
`../model_contract.schema.json` — both this lane and `benchmark_adapt/` validate against the same
file, not two copies that could drift.

## Setup

### 1. This lane's own harness code (into the shared `reagent` conda env)

```bash
conda activate reagent
pip install -r requirements.txt
```

### 2. RepoLaunch (separate env — it requires Python >= 3.12, `reagent` is 3.11)

Already done once as part of building this lane, but for a clean checkout:

```bash
cd methods/contract_gen
git submodule update --init RepoLaunch
cd RepoLaunch
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e .
```

Verify: `RepoLaunch/.venv/bin/launch --help`

### 3. Credentials (not committed anywhere)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # RepoLaunch's own internal agent needs an LLM provider
export TAVILY_API_KEY="tvly-..."        # RepoLaunch's web-search tool, required per its own docs
```

Or drop both into `methods/contract_gen/.env` (`KEY=value` per line, `source`d before running) —
the repo's root `.gitignore` ignores every `.env` file in the tree; confirm with `git check-ignore
-v methods/contract_gen/.env` before trusting it with a real key. `--comprehension-engine serena`
needs neither of these -- Serena itself is a language-server wrapper, not an LLM agent.

### 4. Docker

RepoLaunch needs a running Docker daemon to build and verify images:

```bash
docker info   # must succeed
```

## Quickstart

```bash
conda activate reagent
cd methods/contract_gen

# Narrow smoke test: just the RepoLaunch integration, on scAPE
python smoke_tests/test_repolaunch_scape.py
cat smoke_tests/results/repolaunch_scape_result.json

# Full pipeline: ingest -> RepoLaunch -> comprehension -> contract, on CPA (the single-cell-counts
# test case -- see "Known gap this exercises" below), driven by a real Paperclip record
python -m harness.orchestrator \
    --paperclip-record fixtures/paperclip_cpa_record.json \
    --repolaunch-config fixtures/repolaunch_config_cpa.json \
    --output output/cpa
cat output/cpa/model_contract.yaml

# Same, but with live Serena MCP for Stage 2 instead of the grep heuristic (see ../serena/README.md)
python -m harness.orchestrator \
    --paperclip-record fixtures/paperclip_scape_record.json \
    --repolaunch-config fixtures/repolaunch_config_scape.json \
    --comprehension-engine serena \
    --output output/scape
cat output/scape/model_contract.yaml
```

`--instance` also accepts a raw RepoLaunch instance dict directly, as a fallback for a method with
no Paperclip record yet — but every example and fixture here goes through `--paperclip-record`,
which is the standard input.

Every real RepoLaunch invocation costs API budget and can run for many minutes — it's a genuine
exploratory agent figuring out how to build an unfamiliar repo, not a fixed-cost operation. Run it
in the background if you don't want to block on it.

## Known gap this exercises: CPA needs single-cell counts

CPA (`theislab/cpa`) is deliberately the test case here because it's the concrete, real example of
the OP3 API gap discussed at length in the plan docs: it needs raw single-cell counts as input,
not the `de_train`/`id_map` DE-signature interface OP3's method API actually provides (see PR
[openproblems-bio/task_perturbation_prediction#78](https://github.com/openproblems-bio/task_perturbation_prediction/pull/78),
which hit exactly this wall). The heuristic comprehension stage here correctly flags this from real
grep evidence in the actual repo (`requires_sc_counts: true`, cited to `repo:cpa/_api.py:L10`,
found by matching `setup_anndata` — a real single-cell-model convention) — which is exactly the
signal `benchmark_adapt`'s scope/capability handling needs to route this method correctly instead
of silently trying to force-fit it.

## What's real vs. what's a stand-in

- **RepoLaunch (Stage 1) is real.** The vendored, pinned `launch` CLI, actually invoked, actually
  building a Docker image via its own LLM-driven exploration. Not mocked.
- **Repo comprehension (Stage 2) has two real engines**, chosen with `--comprehension-engine`:
  `heuristic` (default) is grep-based signal detection, every match cited to an actual
  `repo:file:line` — real static analysis, but pattern matching, not semantic understanding.
  `serena` opens a live Serena MCP session (`../serena/`, via `serena_contract_mapping.py`) and
  runs real `find_symbol`/`get_symbols_overview`/... queries against the cloned repo — this is no
  longer a stand-in; see `../serena/README.md` and `../serena/VALIDATION_SCAPE.md`. Both engines
  still rely on the same grep pass for chemical/genetic perturbation-encoding signals, which
  neither Serena's stages nor an LLM contract-extraction agent are aimed at.
- **Contract synthesis (Stage 3) is real and schema-validated**, and with `--comprehension-engine
  serena` most of the previously-`unknown` headline fields resolve from cited evidence: `model
  .entrypoint`, `prediction_level`, `requires_sc_counts`, `gene_space.n_genes`, `hyperparameters`,
  `arguments`, `dependencies`. Fields genuinely out of either engine's reach (`checkpoint.url`,
  `compute.vram_gb`, ...) still legitimately come out `"unknown"` — that remains the correct,
  honest output for evidence no static analysis (heuristic or semantic) can produce, not a bug.

## Handoff contract this lane produces

| Output | Schema | Consumed by |
|---|---|---|
| `output/<method_id>/model_contract.yaml` | `../model_contract.schema.json` (validated automatically at emission — see `orchestrator.py`'s `emit_artifacts`) | `benchmark_adapt/harness/contract.py`, `synthesize_adapter.py` |
| Docker image (`docker_image` field in `repo_manifest.json`) | RepoLaunch's own output schema | `benchmark_adapt/synthesize_adapter.py` → `mini --environment-class docker` |
| `output/<method_id>/execution_log.json` | ad hoc (stage/cmd/status/wall_clock_s records) | referenced in `benchmark_adapt`'s rendered synthesis prompt |
