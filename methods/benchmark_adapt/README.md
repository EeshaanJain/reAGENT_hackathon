# benchmark_adapt — Sei's lane (Stage 4–6)

This is the downstream half of the method-integration workstream described in
[`plan_unified.md`](../planning/plan_unified.md) and audited in
[`method-integration-todo.html`](../planning/method-integration-todo.html). It picks up exactly at the
handoff point — `model_contract.yaml` / `MODELSPEC.json` + a built Docker image +
`execution_log.json` — and turns that into a PR-ready [Viash](https://viash.io) component
(Viash: the build tool Open Problems uses to package a script + config into a runnable, testable
unit — see [`tools_spec.html`](tools_spec.html) for what that means in practice).

It does **not** build the environment, run RepoLaunch, or run Serena — that's Cecilia's lane
(Stages 0–3). Everything here assumes the Docker image and the model contract already exist.

**→ New to this folder? Read [`tools_spec.html`](tools_spec.html) first.** It explains what each
tool does (mini-swe-agent, Docker, Viash, pytest, AnnData, JSON Schema), defines every
agentic-development term it uses along the way, and has the one diagram worth seeing before the
code: the same `script.py` gets executed four different ways during verification, and it helps to
know that going in.

```
model_contract.yaml  ─┐
built Docker image    ├──►  [Stage 4] adapter synthesis  ──►  [Stage 5] Gauntlet  ──►  [Stage 6] PR
execution_log.json   ─┘         (this repo)                     (this repo)          (human, this repo)
```

## Layout

```
benchmark_adapt/
  tools_spec.html                      what each tool below does + jargon glossary — read first
  schemas/model_contract.schema.json   structural + citation-discipline schema (A5)
  harness/
    contract.py                        load + validate a model_contract.yaml (A5)
    synthesize_adapter.py              Stage 4 driver: renders a prompt, invokes mini-swe-agent
                                        against the handed-off Docker image (F1, F2)
    viash_shim.py                      runs a raw VIASH-style script.py locally, without a full
                                        `viash build`, by injecting `par`/`meta` (see caveat below)
    prompts/adapter_synthesis.md.j2    the task prompt template handed to mini-swe-agent
  fixtures/
    make_tiny_fixture.py               the frozen fixture from A2: de_train.h5ad, de_test.h5ad,
                                        id_map.csv, gene order pinned by SHA256
  gauntlet/                            Stage 5 — the checks from plan_unified.md §6 / todo block G,
                                        written as pytest so they run standalone today and drop
                                        into `test.py` once `viash` is available
    checks.py                          pure assertion functions, reusable per method
    test_layer_unit_conformance.py     G1
    test_id_map_gene_space.py          G2
    test_output_sanity.py              G6
    test_perturbation_sensitivity.py   G3
    test_no_network.py                 G4
    test_stochastic_tolerance.py       G7 (deliberately unresolved — see below)
  component_template/                  config.vsh.yaml / script.py / test.py / DEVIATIONS.md
                                        skeletons that synthesize_adapter.py fills in
  examples/
    model_contract.example.yaml        a filled-in example contract (Chem-PerturBridge-style,
                                        API-native — ladder rung 1)
    golden_adapter/script.py           a correct, hand-written adapter against the fixture —
                                        this is the A1 "golden reference", toy-sized
    broken_adapter/script.py           deliberately wrong (emits `logFC` instead of the declared
                                        layer) — exists so G1/G6 have a failing case to catch
    broken_adapter_collapsed_mean/script.py  deliberately wrong a different way (ignores sm_name)
                                        — so G3 has a failing case distinct from G1's
  scripts/
    build_fixture.sh
    run_gauntlet.sh
    synthesize.sh
```

## Setup

Dependencies installed into the `reagent` conda env (not a fresh venv, per project convention):

```bash
conda activate reagent
pip install anndata numpy pandas scipy pyyaml jsonschema pytest jinja2 mini-swe-agent
```

All of the above is already installed as of this writing. `mini-swe-agent` (2.4.6) provides
`mini`/`mini-extra` on `$PATH`; its `docker` **environment class** (the object that decides where
an agent's shell commands actually execute — a plain subprocess locally, or, as used here, inside
a container) takes an `image:` field directly — that's the hook `synthesize_adapter.py` uses to
point the agent at Cecilia's built image.

**Side effect worth knowing about:** installing `anndata` downgraded `pandas` in the `reagent` env
from 3.0.5 to 2.3.3 (anndata's current release pins `pandas<3`). If anything else in this shared
env depends on pandas 3.x behavior, that's a real conflict, not a hypothetical one — check before
assuming it's fine.

## Quickstart

All commands run from `methods/benchmark_adapt/`, with the `reagent` conda env active.

```bash
conda activate reagent
cd methods/benchmark_adapt

python fixtures/make_tiny_fixture.py                                    # writes fixtures/data/, prints the gene-order SHA256

# The Gauntlet -- run against each example adapter to see it actually discriminate:
scripts/run_gauntlet.sh examples/golden_adapter/script.py                # 5 passed, 1 skipped (G7 unconfigured)
scripts/run_gauntlet.sh examples/broken_adapter/script.py                # G1/G6 fail: wrong layer name ("logFC")
scripts/run_gauntlet.sh examples/broken_adapter_collapsed_mean/script.py # G3 fails only: ignores sm_name

# Stage 4 driver -- dry-run by default (renders the prompt and prints the exact `mini` command
# without calling any model or spending API budget), and seeds
# output/<method_id>/{script.py,config.vsh.yaml,test.py,DEVIATIONS.md,MODELSPEC.json}:
python -m harness.synthesize_adapter --contract examples/model_contract.example.yaml \
    --execution-log examples/execution_log.example.json

# Contract validation + scope gate on their own:
python -m harness.contract examples/model_contract.example.yaml
```

## What's real vs. what's a stand-in

- **The Gauntlet (`gauntlet/`) is real and runs today** — no external dependency beyond what's
  pip-installed. It operates on the output of `viash_shim.py`, which mimics how a compiled Viash
  component would be invoked (injecting real values into the script's `par`/`meta` placeholders,
  the same substitution `viash build` does), so the checks don't have to change once `viash`
  itself is on the machine — only `test.py`'s call site does (a subprocess call into the built
  executable instead of `viash_shim.run_component()`).
- **`synthesize_adapter.py` is a real, working driver against `mini`** (verified against a live
  install: `mini --help`, and `DockerEnvironmentConfig` read directly from
  `minisweagent/environments/docker.py`) but defaults to `--dry-run`. Actually executing synthesis
  needs a model id and API credentials (`--model`, plus [litellm](https://docs.litellm.ai/)-style
  environment variables — litellm is the library `mini` uses to talk to any model provider through
  one interface) and the `--execute` flag. Do not flip that on without checking C2's cost-logging
  plan first — RepoLaunch and mini-swe-agent are now *two* separate LLM integrations, each with
  its own budget to track.
- **`test_stochastic_tolerance.py` (G7) is deliberately left unresolved.** The to-do doc flags
  that no document anywhere defines the tolerance number. Rather than invent one silently, the
  test calls `pytest.skip(...)` until someone sets `--stochastic-tol`. Don't quietly delete that
  skip; replace it with a decided number.
- **`test_perturbation_sensitivity.py` (G3) ships a literal default threshold** (5% median
  relative change) so the harness is runnable end-to-end today, but per the to-do doc this is a
  "pick a number before you need it" placeholder, not a validated one — override via
  `--min-change-frac` or revisit before it gates a real PR.

## Handoff contract this lane assumes

| Input | Produced by | Consumed here by |
|---|---|---|
| `model_contract.yaml` (≡ `MODELSPEC.json`) | Cecilia's Stage 3 | `harness/contract.py`, `harness/synthesize_adapter.py` |
| Built Docker image (tag/ref) | Cecilia's Stage 1 (RepoLaunch) | `synthesize_adapter.py` → `mini --environment-class docker` |
| `execution_log.json` | Cecilia's Stages 1–3 | referenced in the rendered prompt so the agent knows what already failed/worked |

If any of the three is missing, `synthesize_adapter.py` refuses to run rather than guessing — see
each tool's "Missing it" line in `tools_spec.html` §3 for what specifically breaks without it.
