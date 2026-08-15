# Method Integration Agent

## Scope

Automatically adapt a published perturbation model to an **already-defined benchmark**. Inputs are a paper/repository plus benchmark dataset/splits/metrics; outputs are a reproducible method wrapper and valid benchmark predictions.

This component **does not design datasets, splits, or metrics**.

## Recommended Tool Stack

| Tool | Link | Ability | Responsibility in our workflow |
|---|---|---|---|
| **mini-SWE-agent** | https://github.com/SWE-agent/mini-swe-agent | Lightweight coding-agent control loop with shell execution | Main reasoning/orchestration loop: inspect → act → run → debug → retry |
| **Serena (MCP)** | https://github.com/oraios/serena | Semantic repository navigation/editing via language-server symbols | Understand unfamiliar repos: find entrypoints, data loaders, preprocessing, inference, config, checkpoint usage |
| **RepoLaunch** | https://github.com/microsoft/RepoLaunch | Automatically builds/tests repositories and produces reproducible container environments | Dependency/environment reconstruction; capture build/test commands and reusable Docker image |
| **SWE-ReX** | https://github.com/SWE-agent/SWE-ReX | Sandboxed command execution across local/cloud backends | Safe execution abstraction for generated commands, tests, training/inference, and parallel runs |
| **Modal** *(optional)* | https://github.com/modal-labs/modal-client | Cloud containers/GPU execution | Scale expensive or GPU-based benchmark runs without changing the agent logic |

### Useful Alternatives / Supplements

| Tool | Link | When useful |
|---|---|---|
| **Aider Repo Map** | https://github.com/Aider-AI/aider | Cheap first-pass overview of large repositories before deeper Serena inspection |
| **OpenHands** | https://github.com/OpenHands/openhands | More complete coding-agent platform if we later want an integrated alternative to the lightweight stack |
| **E2B** | https://github.com/e2b-dev/E2B | Alternative hosted sandbox/runtime for untrusted repository execution |

## Proposed Workflow

```text
paper + GitHub repo
benchmark dataset contract
split + metric contract
        |
        v
1. Context extraction
   - Methods / preprocessing / inference details
   - README, examples, configs, source code
        |
        v
2. Repository understanding                [Serena]
   - locate train/inference entrypoints
   - trace data loaders and preprocessing
   - locate checkpoints/configs
        |
        v
3. Model contract extraction                [mini-SWE-agent]
   - required input representation
   - gene set/order
   - perturbation/context encoding
   - normalization/preprocessing
   - training vs pretrained inference
   - expected output semantics
        |
        +-----------------------+
        |                       |
        v                       v
4a. Environment build       4b. Dataset adapter
    [RepoLaunch]                [our code/agent]
    - dependencies              benchmark schema
    - build/test                     ->
    - Docker image              model-required schema
        |                       |
        +-----------+-----------+
                    v
5. Smoke test + validation               [SWE-ReX]
   - tiny dataset slice
   - schema/shape checks
   - NaN/Inf checks
   - no hidden-test access
                    |
                    v
6. Benchmark execution                  [SWE-ReX / Modal]
                    |
                    v
prediction.h5ad + adapter + environment + provenance
```

## Required Intermediate Artifact: `model_contract.yaml`

The agent should produce a machine-readable contract before generating an adapter.

```yaml
model:
  repo: owner/repo
  commit: <sha>
  entrypoint: <train-or-inference-command>

environment:
  image: <reproducible-image>
  gpu_required: false

input:
  representation: <counts|normalized|pseudobulk_de|...>
  genes: <requirements>
  gene_order_fixed: false
  perturbation_encoding: <compound_id|smiles|embedding|...>
  context_fields: [cell_type]

preprocessing:
  normalization: <required procedure>

output:
  representation: <expression|delta_expression|distribution>
```

## Upstream Contract

Upstream components should provide:

- paper text/PDF and official repository URL;
- exact repository commit when available;
- benchmark `train/validation/test` split definition;
- standardized dataset schema and visible fields;
- hidden-test access policy;
- metric specification;
- allowed external priors/resources.

For the current OpenProblems perturbation task, the final wrapper should target the existing typed method/prediction API rather than inventing a parallel interface.

## Outputs

```text
model_contract.yaml      # recovered scientific/software requirements
adapter.py               # benchmark dataset -> model input
container/environment    # reproducible execution environment
prediction.h5ad          # benchmark-compatible predictions
execution_log.json       # commands, failures, retries
validation_report.json   # automated checks and provenance
```

## Robustness Checks

The integration is successful only if **software execution and scientific semantics are both correct**.

- **Environment:** clean rebuild succeeds; dependencies and commit are pinned.
- **Input compatibility:** correct normalization, gene universe/order, perturbation/context encoding.
- **Output compatibility:** expected rows/genes, units/representation, no NaN/Inf.
- **Evaluation integrity:** model never accesses hidden test labels or test-derived preprocessing statistics.
- **Reproducibility:** repeated runs are identical or within an explicitly defined stochastic tolerance.
- **Scientific fidelity:** adapter does not silently change what the original method predicts.
- **Security:** run unfamiliar repositories in a sandbox/container with restricted credentials/filesystem access.

## Experiments to Run

1. Compare **README-only** repo understanding vs **Serena + paper context**.
2. Compare manual agent dependency installation vs **RepoLaunch**.
3. Test on repositories with increasing difficulty: simple baseline → custom preprocessing → checkpoint/external-resource model → messy research repo.
4. Compare generated `model_contract.yaml` and adapter against a human-reviewed gold implementation.
5. Track integration success rate, human corrections, runtime/cost, retries, and reproducibility.

## MVP Recommendation

Use:

```text
mini-SWE-agent
    + Serena MCP
    + RepoLaunch
    + SWE-ReX (Docker locally)
```

Add Modal only when GPU/cloud scaling is required.

The main project-specific contribution should be **model-contract extraction + dataset adaptation + validation**, not rebuilding generic coding-agent or container infrastructure.
