# Method Integration

Automatically turns a published perturbation-prediction paper into a tested, PR-ready Open
Problems v3 (OP3) benchmark component. Two lanes, one handoff in the middle.

**→ Start here:** [`pipeline_spec.html`](pipeline_spec.html) — the full two-lane architecture,
what each tool does, and a real worked example (CPA).

```
paper repo  ──►  contract_gen/  ──►  model_contract.yaml + Docker image  ──►  benchmark_adapt/  ──►  PR
             (Stage 0-3, Cecilia)         (the handoff)                    (Stage 4-6, Sei)
```

## Layout

| Path | What |
|---|---|
| [`pipeline_spec.html`](pipeline_spec.html) | Full architecture, tool spec, worked CPA example — read this first |
| [`model_contract.schema.json`](model_contract.schema.json) | The shared contract schema both lanes validate against |
| [`requirements.txt`](requirements.txt) | One-shot install for everything except RepoLaunch (which needs its own env — see below) |
| [`contract_gen/`](contract_gen/) | Stage 0–3: ingest → RepoLaunch → repo comprehension → contract synthesis |
| [`serena/`](serena/) | The live Serena MCP client `contract_gen`'s Stage 2 uses when run with `--comprehension-engine serena` — see "How Stage 2 works" below |
| [`benchmark_adapt/`](benchmark_adapt/) | Stage 4–6: adapter synthesis → Gauntlet → PR |
| [`results/`](results/) | Not part of either lane's own `output/` — cross-cutting tools plus where a full end-to-end run's final artifacts (synthesized component + real `prediction.h5ad` + metrics) get collected. `pipeline_status.py` (live run status) and `run_and_evaluate.py` (execute a synthesized component against the fixture and score it) live here. |
| [`planning/`](planning/) | Historical design docs — narrative context, not needed to run anything (see below) |

`planning/` holds the docs that motivated this build, kept out of the top level so the active
pipeline isn't mixed in with background reading: [`plan_unified.md`](planning/plan_unified.md)
(the design doc this implements — role split, open questions), the two source plans it merged
([`plan_sei.md`](planning/plan_sei.md), [`METHOD_INTEGRATION_AGENT.md`](planning/METHOD_INTEGRATION_AGENT.md)),
[`method-integration-todo.html`](planning/method-integration-todo.html) (a build-plan audit
against those two plans), and [`benchmark-agent-pipeline.html`](planning/benchmark-agent-pipeline.html)
(an earlier pipeline-wide visualization).

## How Stage 2 (repo comprehension) works

`contract_gen`'s Stage 2 has two engines, chosen with `--comprehension-engine`:

- **`heuristic`** (default). Zero extra dependencies. Greps the cloned repo for naming
  conventions (`anndata`/`scanpy` → single-cell, `SMILES`/`rdkit` → chemical encoding, `CRISPR`/
  `sgRNA` → genetic encoding, `train.py`/`__main__.py` → entrypoints), every hit cited to a real
  `repo:file:line`. It's real static analysis, not a guess — but it's pattern matching, and it
  can't answer questions that need actual code understanding (`gene_space.n_genes`, the real
  entrypoint's default hyperparameters, what a factory function actually builds and returns).
- **`serena`**. Runs a live [Serena](https://github.com/oraios/serena) MCP session — the same
  semantic-code-navigation tools (`find_symbol`, `get_symbols_overview`, `find_referencing_symbols`,
  ...) an IDE's language server backs — against the cloned repo, and maps the findings straight
  into contract fields with real citations. This is what resolves `model.entrypoint`,
  `prediction_level`, `requires_sc_counts`, `gene_space.n_genes`, `hyperparameters`, `arguments`
  (the viash component's CLI flags), and `dependencies` (its pip/git requirements) from evidence
  instead of leaving them `unknown`. See [`serena/README.md`](serena/README.md) for the full
  9-stage query sequence and [`serena/VALIDATION_SCAPE.md`](serena/VALIDATION_SCAPE.md) for a
  worked validation against the scAPE repo.

Either way, the perturbation-encoding signal (chemical vs. genetic) still comes from the same
heuristic grep — Serena's stages are about the model's training/inference/data-loading code, not
about classifying what kind of perturbation the paper studies.

## What the pipeline's final output actually is

Easy to conflate two different things that both sound like "what level does this operate at":

- **The task's output file format is fixed, for every method, by the task itself** — not decided
  per-method. `task_perturbation_prediction`'s own
  [`file_prediction.yaml`](../task_perturbation_prediction/src/api/file_prediction.yaml) defines it
  once, task-wide: `prediction.h5ad`, a `prediction` layer of doubles, described literally as
  "Predicted differential gene expression". Every method plugged into this benchmark — scAPE, CPA,
  whatever comes next — produces *that* shape: one row per `(cell_type, sm_name)` query in
  `id_map.csv`, one column per gene, values are per-gene differential-expression scores. **Never**
  raw single-cell counts, never a cell-by-gene matrix, regardless of what the underlying model
  internally computes.
- **`model_contract.yaml`'s `prediction_level` field answers a different question**: what level the
  *method itself* naturally trains/predicts at, and by extension what it needs as *input* — not
  what its output file looks like. scAPE resolves to `de_signature` (it trains and predicts
  directly on DE statistics, never touching per-cell data — see the scAPE case below). CPA resolves
  to `single_cell`/`requires_sc_counts: true` — it needs raw counts as *input*, which OP3's
  `de_train`/`id_map` API can't supply. That input mismatch is the actual reason CPA hits the API
  gap in the CPA case below — its *output* would still have to be the same DE-signature shape as
  everyone else's, it just can't get there from the input this task hands it.

So for scAPE specifically: the synthesized component's output is DE-gene-level predicted values,
never single-cell counts. See §3's `run_and_evaluate.py` for where this gets checked and scored.

## Setup

```bash
conda activate reagent
pip install -r methods/requirements.txt          # everything except RepoLaunch, incl. serena-agent + mcp
bash methods/contract_gen/scripts/install_repolaunch.sh   # RepoLaunch, separate Python 3.12+ env

docker info                             # must succeed -- RepoLaunch builds/verifies images with it
serena --help                           # must succeed -- confirms serena-agent installed correctly
```

### Credentials

Three real external LLM/API integrations exist in this pipeline, each with its own key and its own
budget: RepoLaunch's exploratory agent (Stage 1), Serena's MCP server (Stage 2, `serena` engine —
Serena itself doesn't call an LLM, but needs no extra key either; it's a language-server wrapper,
not an agent), and mini-swe-agent (Stage 4, in `benchmark_adapt/`). Only Stage 1 and Stage 4
actually need credentials:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # RepoLaunch's own agent, and mini-swe-agent's default model
export TAVILY_API_KEY="tvly-..."        # RepoLaunch's web-search tool
```

Never commit these. Either export them in your own shell, or drop them in
`methods/contract_gen/.env` (`KEY=value` per line) — the repo's root `.gitignore` already ignores
every `.env` file anywhere in the tree (confirm with `git check-ignore -v methods/contract_gen/.env`
before trusting it with a real key). Source it before running anything that needs it:

```bash
cd methods/contract_gen && set -a && source .env && set +a
```

## Running the pipeline

### 1. contract_gen — paper repo → model_contract.yaml + Docker image

Standard input is a Paperclip literature-agent record — the real upstream format
(`method_name`/`github_candidates`/paper provenance):

```bash
cd methods/contract_gen
python -m harness.orchestrator \
    --paperclip-record fixtures/paperclip_cpa_record.json \
    --repolaunch-config fixtures/repolaunch_config_cpa.json \
    --output output/cpa
```

Add `--comprehension-engine serena` to use live Serena MCP for Stage 2 instead of the grep
heuristic (needs `serena-agent`/`mcp` installed — see Setup above; no extra credentials):

```bash
python -m harness.orchestrator \
    --paperclip-record fixtures/paperclip_scape_record.json \
    --repolaunch-config fixtures/repolaunch_config_scape.json \
    --comprehension-engine serena \
    --output output/scape
```

(`--instance` also accepts a raw RepoLaunch instance dict — `instance_id`/`repo`/`base_commit`/
`language` — directly, as a fallback for a method with no Paperclip record yet. Not used by
anything in `fixtures/` right now; every example here goes through Paperclip.)

A real run can take many minutes (RepoLaunch is itself an exploratory agent) and costs real API
budget — run it in the background if you don't want to block. If you already have a successful
run's `repo_manifest.json` and only need to redo contract synthesis (e.g. with a corrected
Paperclip record), skip the expensive RepoLaunch step entirely:

```bash
python -m harness.orchestrator --paperclip-record fixtures/paperclip_cpa_record.json \
    --output output/cpa --resume-from-manifest output/cpa/repo_manifest.json
```

**Output lands at** `methods/contract_gen/output/<method_id>/`:

| File | Contents |
|---|---|
| `model_contract.yaml` | The contract — validated against `methods/model_contract.schema.json` automatically at emission. Includes a `paper` provenance block when built from a Paperclip record, and a `_serena_findings` audit trail (every finding behind every citation) when built with `--comprehension-engine serena`. |
| `repo_manifest.json` | Resolved commit SHA, RepoLaunch status, the Docker image tag, comprehension findings |
| `execution_log.json` | Every command this lane ran, with status and wall-clock time |

The built Docker image itself is a local Docker image (check `repo_manifest.json`'s
`docker_image` field for its tag) — `docker image inspect <tag>` to confirm it exists.

Narrower smoke test (just the RepoLaunch integration, skips comprehension/contract synthesis):

```bash
python smoke_tests/test_repolaunch_scape.py
cat smoke_tests/results/repolaunch_scape_result.json
```

### 2. benchmark_adapt — model_contract.yaml + image → adapter + Gauntlet result

```bash
cd methods/benchmark_adapt

python fixtures/make_tiny_fixture.py    # once, or whenever fixtures/data/ is missing

python -m harness.synthesize_adapter \
    --contract ../contract_gen/output/cpa/model_contract.yaml \
    --execution-log ../contract_gen/output/cpa/execution_log.json
```

(`--docker-image` is optional — it falls back to the contract's own `environment.image` field,
which is already set from the RepoLaunch handoff.)

Defaults to `--dry-run`: validates the contract, applies the scope gate, and seeds
`output/<method_id>/` with templated `script.py`/`config.vsh.yaml`/`test.py`/`DEVIATIONS.md`/
`MODELSPEC.json` — without calling any model or spending API budget. When the contract carries
Serena-derived `arguments`/`dependencies` (i.e. it was built with `--comprehension-engine serena`),
`config.vsh.yaml` is seeded with a real `arguments:` block and `engines.docker.setup` packages
instead of an empty skeleton. Add `--execute --model <litellm-model-id>` to actually run the
synthesis agent (mini-swe-agent, separate cost from RepoLaunch's) and let it fill in `script.py`
for real, inside the handed-off Docker image.

**Output lands at** `methods/benchmark_adapt/output/<method_id>/`:

| File | Contents |
|---|---|
| `script.py` | The adapter (a `NotImplementedError` stub, with reasoning inline, until synthesis actually runs or a hard API blocker is hit — see the CPA case below) |
| `config.vsh.yaml` | The Viash component config |
| `test.py` | Local Gauntlet-style test entry point |
| `MODELSPEC.json` | Copy of the contract, travels with the component |
| `DEVIATIONS.md` | Divergences from the paper's stated protocol, or a filed API-gap finding when no adapter is possible |
| `synthesis_prompt.md` | The exact prompt handed to the synthesis agent |
| `trajectory.json` | Only present after a real `--execute` run — the agent's full command log |
| `PR_DESCRIPTION.md` | Present only when hand-authored for a specific case (see CPA) — a ready-to-use PR body, not auto-submitted |

Run the Gauntlet against any adapter (the seeded stub, or a completed one):

```bash
scripts/run_gauntlet.sh output/<method_id>/script.py
```

### 3. Running the full pipeline autonomously, end to end

With both API keys set (see Credentials above), nothing in either stage needs a human in the loop
— RepoLaunch really builds the image, Serena really queries the repo, mini-swe-agent really writes
the adapter inside that image:

```bash
cd methods/contract_gen
set -a && source .env && set +a          # or rely on your shell's own exports

python -m harness.orchestrator \
    --paperclip-record fixtures/paperclip_scape_record.json \
    --repolaunch-config fixtures/repolaunch_config_scape.json \
    --comprehension-engine serena \
    --output output/scape
# -- can take up to repolaunch-timeout (default 1800s); RepoLaunch is a real exploratory agent

cd ../benchmark_adapt
python fixtures/make_tiny_fixture.py     # once
python -m harness.synthesize_adapter \
    --contract ../contract_gen/output/scape/model_contract.yaml \
    --execution-log ../contract_gen/output/scape/execution_log.json \
    --execute --model anthropic/claude-sonnet-5 --cost-limit 2.0
```

**Tracking a run in progress:** both stages run for real minutes with no per-step console output
of their own (RepoLaunch's own subprocess call buffers output until it exits; a background `nohup`
invocation writes nothing to your terminal at all). Run `methods/results/pipeline_status.py`
alongside it, from another terminal, to see whether anything is actually running and which stage
it's on — including RepoLaunch's own live agent-turn count and running cost, read straight out of
its workdir (the orchestrator's own log goes quiet during Stage 1 even though real work is
happening):

```bash
python methods/results/pipeline_status.py --method-id scape --watch --interval 10
```

Then actually run the synthesized component against data and score it — a rendered
`config.vsh.yaml`/`script.py` that were never executed against real input aren't a finished
deliverable, they're an untested claim. `methods/results/run_and_evaluate.py` does this: runs
`script.py` through `viash_shim` (the same par/meta substitution `viash build` would do) against
the fixture, checks the OP3 output conventions (`prediction` layer present, `obs_names == id_map
["id"]` in order, finite values — the same assertions as Gauntlet's G1/G2/G6), and scores it with
MRRMSE against the fixture's held-out ground truth:

```bash
cd ../..    # repo root
python methods/results/run_and_evaluate.py scape
```

Writes `methods/results/scape_prediction.h5ad` and `methods/results/scape_metrics.json`. The
output file is an AnnData with one row per `(cell_type, sm_name)` query in `id_map.csv`, one column
per gene, and a `prediction` layer of per-gene differential-expression scores — see "What the
pipeline's final output actually is" above; it is never single-cell counts, for any method in this
task. A real `scape_prediction.h5ad` landing on disk, openable with `anndata.read_h5ad` and scoring
below the zero-prediction baseline, is the actual acceptance bar — not the presence of `script.py`.

Every real RepoLaunch and mini-swe-agent invocation costs API budget and wall-clock — this is not
a fixed-cost operation, and re-running it re-spends both. `execution_log.json` /
`trajectory.json` are where that's logged.

### 4. The CPA case: a real run, end to end

CPA (`theislab/cpa`) has actually been run through this pipeline, driven by a real Paperclip
record ([`contract_gen/fixtures/paperclip_cpa_record.json`](contract_gen/fixtures/paperclip_cpa_record.json)):
RepoLaunch really built its environment (`docker_image: repolaunch/cpa-test:cpa_test_linux`,
status `PASS`), heuristic comprehension found real evidence in the cloned repo
(`requires_sc_counts: true`, cited to `repo:cpa/_api.py:L10`), and `benchmark_adapt` correctly
produced a stub adapter with the API gap explained inline rather than a fabricated working one.

That's the intended, correct outcome for this case — CPA needs raw single-cell counts, and OP3's
`de_train`/`id_map` method API has no way to express that. See
[`benchmark_adapt/output/cpa/DEVIATIONS.md`](benchmark_adapt/output/cpa/DEVIATIONS.md) for the
full evidence trail and [`benchmark_adapt/output/cpa/PR_DESCRIPTION.md`](benchmark_adapt/output/cpa/PR_DESCRIPTION.md)
for the PR this produces — filing the API gap as a finding, with a proposed `--sc_train` /
`requires_sc_counts` extension, rather than silently skipping the method. That PR is drafted, not
submitted — opening a real PR against an external repo needs an explicit go-ahead.

### 5. The scAPE case: live Serena end to end

scAPE (`scapeML/scape`) is the worked example for the `--comprehension-engine serena` path — a
NeurIPS 2023 Kaggle-competition submission already shipped as a real OP3 component at
[`task_perturbation_prediction/src/methods/scape/`](../task_perturbation_prediction/src/methods/scape/),
which makes it a good target to check this pipeline's output against: does independently-derived,
cited evidence actually land close to what a human-authored component looks like?

Run it exactly as in §3 above, using `contract_gen/fixtures/paperclip_scape_record.json` (a real
Paperclip record) and `contract_gen/fixtures/repolaunch_config_scape.json`. A few things worth
checking once it's done:

- `model_contract.yaml`'s `prediction_level` should resolve to `de_signature`, cited to
  `scape/_io.py` (`load_slogpvals`/`load_lfc` operate on grouped differential-expression
  statistics, not raw counts) — not `single_cell`, which a naive grep would get wrong here (the
  *component's* `script.py` imports `anndata`, but scAPE's own library never touches per-cell
  data).
- `arguments` should include `--n_genes` (default `64`) and `--cv_cell` (default `"NK cells"`),
  both traced to `scape/_api.py`'s real `train()` signature — compare against the real component's
  own `--n_genes`/`--cell` arguments in
  [`task_perturbation_prediction/src/methods/scape/config.vsh.yaml`](../task_perturbation_prediction/src/methods/scape/config.vsh.yaml).
- `dependencies` should list `jax`/`jaxlib`/`keras>=3.6`, cited to the repo's own
  `pyproject.toml` — notably *not* `tensorflow`, which is what the existing (older) OP3 component
  pins. The upstream repo has moved to Keras 3 + JAX since that component was authored; this is a
  real, citation-backed finding, not a bug in either component.

The two-pass coarse/enhanced ensemble strategy in the existing OP3 `script.py` (leave-one-drug-out
training, a second pass on a drug-effect-ranked gene/drug subset, an 80/20 blend) is **not**
something repo comprehension of any kind can recover — it's orchestration logic the OP3 team wrote
on top of scAPE's library, not part of `scapeML/scape` itself (its own `train()`/`predict()` train
and score one model). Expect the synthesis agent's `script.py` to differ from the existing one here
unless it's specifically pointed at the existing file as a reference — that's a legitimate
divergence to record in `DEVIATIONS.md`, not a pipeline bug.
