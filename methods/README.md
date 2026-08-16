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
| [`benchmark_adapt/`](benchmark_adapt/) | Stage 4–6: adapter synthesis → Gauntlet → PR |
| [`planning/`](planning/) | Historical design docs — narrative context, not needed to run anything (see below) |

`planning/` holds the docs that motivated this build, kept out of the top level so the active
pipeline isn't mixed in with background reading: [`plan_unified.md`](planning/plan_unified.md)
(the design doc this implements — role split, open questions), the two source plans it merged
([`plan_sei.md`](planning/plan_sei.md), [`METHOD_INTEGRATION_AGENT.md`](planning/METHOD_INTEGRATION_AGENT.md)),
[`method-integration-todo.html`](planning/method-integration-todo.html) (a build-plan audit
against those two plans), and [`benchmark-agent-pipeline.html`](planning/benchmark-agent-pipeline.html)
(an earlier pipeline-wide visualization).

## Setup

```bash
conda activate reagent
pip install -r methods/requirements.txt          # everything except RepoLaunch
bash methods/contract_gen/scripts/install_repolaunch.sh   # RepoLaunch, separate Python 3.12+ env

export ANTHROPIC_API_KEY="sk-ant-..."   # your own shell, never committed
export TAVILY_API_KEY="tvly-..."        # RepoLaunch's web-search tool
docker info                             # must succeed
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
| `model_contract.yaml` | The contract — validated against `methods/model_contract.schema.json` automatically at emission. Includes a `paper` provenance block when built from a Paperclip record. |
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
`MODELSPEC.json` — without calling any model or spending API budget. Add `--execute --model
<litellm-model-id>` to actually run the synthesis agent (separate cost from RepoLaunch's).

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

### 3. The CPA case: a real run, end to end

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
