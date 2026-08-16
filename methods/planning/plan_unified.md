# Method Integration Workstream — Unified Plan

**Owners:** Sei, Cecilia (Frank supports both lanes as needed)
**Scope:** two nodes of the master pipeline's §9 architecture — *sandboxed reproduction agent* and *benchmark adapter generator*. We do not design datasets, splits, or metrics.

This merges [plan_sei.md](plan_sei.md) and [METHOD_INTEGRATION_AGENT.md](METHOD_INTEGRATION_AGENT.md). The seam between the two source plans is `model_contract.yaml` (Cecilia's artifact) / `MODELSPEC.json` (Sei's artifact) — we treat these as the same object and the handoff point between the two roles below.

---

## 1. Contract with the rest of the team

| Boundary | What we need / give | Owner |
|---|---|---|
| **In** | Paper ID + line-numbered full text, code URL, **pinned commit SHA** (never `main`), license, declared modality (chemical/genetic) | Vlad (literature) |
| **In** | `de_train.h5ad`, `de_test.h5ad`, `id_map.csv` in OP3 format; harmonized SMILES (desalted + InChIKey) | Philipp / Lijun |
| **Out** | Viash method component + PR to `EeshaanJain/openproblems` | us |
| **Out** | `MODELSPEC.json` / `model_contract.yaml`, `DEVIATIONS.md`, agent trajectory, cost/wall-clock | → Eeshan (verifier), Sundial |
| **Out** | Scope rejections (genetic method sent to chemical task) as labeled eval data | → Vlad |
| **Not ours** | Leakage/scientific audit (Eeshan), metric design (Matt), dataset QC (Philipp/Lijun) | — |

**Principle:** the agent is a *compiler*, not an interpreter. It emits a reviewable artifact once; the benchmark then runs deterministically with no LLM in the loop.

---

## 2. Tool stack

| Tool | Ability | Responsibility |
|---|---|---|
| **RepoLaunch** | Builds/tests repos, produces reproducible container + layer-reconstructed Dockerfile + testcase-status map | Environment reconstruction. The agent never hand-writes the Dockerfile. |
| **Serena (MCP)** | LSP-backed symbol navigation (`find_symbol`, `find_referencing_symbols`, diagnostics) | Locate entrypoints, data loaders, preprocessing, checkpoints. **Run against the built image only** — pre-build resolution is degraded and produces confidently wrong entrypoint guesses. |
| **mini-SWE-agent** | Minimal bash-only coding-agent loop | Main reasoning/orchestration — used twice, for two different jobs (§5). Its linear trajectory *is* our inspectability artifact. |
| **SWE-ReX** | Sandboxed command execution, local/cloud | Safe execution abstraction for exploratory commands, tests, training/inference. |
| **Modal** *(optional)* | Cloud containers/GPU | Only if a ladder rung needs GPU. Prefer CPU-only for the hackathon demo. |

Supplements: Aider Repo Map (cheap first-pass overview before Serena), OpenHands (heavier alternative if the minimal stack proves insufficient), E2B (alternate sandbox to SWE-ReX).

---

## 3. Deliverable

One directory per method, PR-ready:

```
src/methods/<method_id>/
  config.vsh.yaml    # __merge__ ../../api/comp_method.yaml + docker setup + resources
  script.py          # adapter: de_train + id_map -> prediction layer
  test.py
  MODELSPEC.json     # == model_contract.yaml, extended; every field cites PAPER_ID:Lstart-Lend or repo file:line
  DEVIATIONS.md       # every divergence from the paper's stated protocol
```

Plus, as intermediate/provenance artifacts: `execution_log.json` (commands, failures, retries) and `validation_report.json` (automated checks).

**Gate:** `viash ns test --query <method_id>` passes — validation external to the agent's own reasoning, reusing infrastructure that already exists rather than inventing a checker.

---

## 4. Pipeline

```text
paper + GitHub repo + pinned commit SHA
        |
        v
0. Ingest                                    [Paperclip output + git checkout <SHA>]
   Vendor a snapshot. Never pull at build time.
        |
        v
========================= CECILIA'S LANE =========================
1. Environment build                          [RepoLaunch]
   deps + build + Docker image + testcase-status map
        |
        v
2. Repository understanding                   [Serena, against the BUILT image]
   entrypoints, data loaders, preprocessing, checkpoint usage
   (prioritize tutorial notebooks / examples/ over the Methods section)
        |
        v
3. Model contract extraction                  [mini-SWE-agent #1 + Serena + paper text]
   typed, cited, "unknown" is legal — no guessing
        |
        v
   >>> HANDOFF: model_contract.yaml / MODELSPEC.json (draft) <<<
        |
========================= SEI'S LANE ==============================
        v
4. Adapter synthesis                          [mini-SWE-agent #2]
   iterates against a tiny fixture (~200 cells x 500 genes, 3 compounds, 2 cell types)
   targets the OP3 comp_method.yaml API
        |
        v
5. Gauntlet (viash ns test)                   [§6]
        |
        v
6. Human review -> PR                          [no auto-merge]
====================================================================
```

---

## 5. Model contract / ModelSpec (shared schema, the handoff object)

```yaml
# software / environment (Cecilia extracts)
model:
  repo: owner/repo
  commit: <sha>
  entrypoint: <train-or-inference-command>
environment:
  image: <reproducible-image>
  gpu_required: false

# scientific interface (Cecilia extracts, Sei consumes)
prediction_level: de_signature | pseudobulk | single_cell
input_layer: clipped_sign_log10_pval | logFC | ...
requires_sc_counts: bool          # see §7 blocker
perturbation_encoding: smiles | ecfp4 | pretrained_embedding | onehot | gene_id
gene_space: {n_genes, id_type, order_sensitive}
handles: {dose, timepoint, unseen_compound, unseen_cell_type}
compute: {gpu, vram_gb, est_runtime_min}
checkpoint: {url, sha256, license}
hyperparameters: {...}             # asserted at runtime; deviations logged
```

`perturbation_encoding: gene_id` → **Sei's adapter stage refuses and returns upstream.** We are the second line of scope defense; heroically adapting a genetic method into the chemical task is a failure, not a save. Every rejection is also labeled eval data for Vlad's scope classifier.

---

## 6. Gauntlet (as viash tests) — Sei's lane

OP3 already prevents the main leak structurally (regular methods never see `de_test`). We own:

1. **Layer/unit conformance.** Top silent killer: model emits `logFC`, metric expects `clipped_sign_log10_pval` (bounded ±4) → garbage scores, zero errors. Assert range, sparsity, sign symmetry.
2. **Exact `id_map` row order + gene space.** Any invocation of the metric's `--resolve_genes` rescue = hard fail.
3. **Perturbation sensitivity.** Shuffle `sm_name` → prediction must change materially. Catches collapse-to-training-mean.
4. **No network at inference.** Blocks a model re-downloading its own copy of the data.
5. **Baselines: use OP3's six existing control methods as-is.** Systema / scArchon / Ahlmann-Eltze all say simple baselines win often — a new method not clearing them is expected, not a bug.

General robustness checks that apply across both lanes (environment rebuild succeeds; no NaN/Inf; reproducible within stochastic tolerance; sandboxed execution with restricted credentials) are covered structurally by RepoLaunch + SWE-ReX in Cecilia's lane and don't need separate viash tests.

---

## 7. Known blocker, and the plan around it

OP3's method API passes only `de_train` + `id_map`. That works for the six Kaggle-derived methods (native DE space). It **cannot express chemCPA / CPA / biolord**, which need single-cell counts living upstream of `process_dataset`.

- **Demo path:** pick methods that dodge it. **Chem-PerturBridge is ideal** — a pretrained compound representation feeding ridge/MLP → DE is fully API-compatible today.
- **PR path:** propose optional `--sc_train` gated by `requires_sc_counts`, plus a shared benchmark-owned limma lift so models aren't scored on their own DE method. File this as the finding, not a failure.

---

## 8. Difficulty ladder & experiments

3-paper ladder, chosen to expose the §7 blocker deliberately:

1. **API-native** (Chem-PerturBridge-style compound representation) — expected pass, full pipeline.
2. **Mid** (needs preprocessing reconstruction) — tests Cecilia's contract-extraction fidelity.
3. **Hard** (needs single-cell input, e.g. chemCPA-class) — expected fail, produces the API-gap finding.

Supporting experiments (from Cecilia's plan, run opportunistically):
- README-only repo understanding vs. Serena + paper context.
- Manual dependency install vs. RepoLaunch.
- Generated contract/adapter vs. a human-reviewed gold implementation.
- Track success rate, human corrections, runtime/cost, retries, reproducibility.

**Demo the whole ladder, including the failure.** A legible, explained failure scores better on judging criterion 3 than a hidden success, and rung 3 produces the API-gap finding.

---

## 9. Headline result

**Adapter-induced variance vs. model-induced variance.** K=3 replicate agent runs on one model, generating 3 independent adapters. Compare score spread across those 3 adapters against the spread between OP3's existing methods. If they're comparable, the pipeline is measuring itself, not the science. This is the single most valuable number we can produce in a day (ties to the master doc's §11 contribution 5).

---

## 10. Correction to the agent-eval rubric (master doc §9)

Drop *"numerical agreement with the paper"* as a scored metric — preprocessing, gene panels, splits, and priors legitimately differ across studies, so disagreement doesn't distinguish a broken harness from a different protocol.

**Score instead: does `DEVIATIONS.md` explain the gap?** Same artifact also blocks the agent from silently "fixing" the model — adding unspecified normalization, cutting epochs to make something finish.

---

## 11. Hackathon schedule

| Block | Work | Lane |
|---|---|---|
| 0–3h | Hand-write one adapter for an existing OP3 method (golden reference, learn the Viash contract) | Both, together |
| 3–8h | RepoLaunch + Serena + contract extraction on the 3-paper ladder | Cecilia |
| 3–8h | (in parallel, once first contract lands) Adapter synthesis against fixture | Sei |
| 8–12h | Gauntlet tests + MODELSPEC/DEVIATIONS emission | Sei |
| 12–16h | K=3 replicate agent runs on one model; compare variance | Both |
| 16h+ | PR + report | Sei (drafts), Cecilia (environment/repro appendix) |

**Cut:** multi-seed stats, Nextflow scale-out, GPU determinism, multi-dataset, adapter registry.

---

## 12. Role split

### Cecilia — Repository Understanding & Contract Extraction (upstream)
- Own stages 0–3: ingest, RepoLaunch environment build, Serena repo comprehension, `mini-SWE-agent` model-contract extraction.
- Own the environment side of the tool stack: RepoLaunch, SWE-ReX, Modal (if a rung needs GPU).
- Enforce the ordering constraint: **build before comprehend** — Serena runs only against the built image.
- Deliverable / handoff to Sei: `model_contract.yaml` (draft `MODELSPEC.json`) + built Docker image + `execution_log.json`, all fields cited to `PAPER_ID:Lstart-Lend` or `repo:file:line`, `unknown` where evidence is absent.
- Runs the difficulty-ladder comparison experiments (README-only vs. Serena+paper; manual vs. RepoLaunch install).

### Sei — Adapter Synthesis, Gauntlet & PR (downstream)
- Own stages 4–6: consume the contract, synthesize the adapter via `mini-SWE-agent` against the OP3 `comp_method.yaml` API, run the Gauntlet, produce the Viash component directory, write `DEVIATIONS.md`, open the PR.
- Own the OP3-specific blocker (§7): decide demo-path method, draft the `--sc_train`/`requires_sc_counts` PR proposal.
- Own scope defense: reject `gene_id`-encoded contracts, report rejections to Vlad as eval data.
- Own the headline K=3 replicate-variance experiment and the rubric pushback (§10).
- Owns the team-boundary contract (§1) with Vlad/Eeshan/Philipp/Lijun/Matt.

### Shared
- Block 0–3h hand-written reference adapter (both need the Viash contract fluent before delegating to agents).
- Difficulty-ladder rung selection and the K=3 experiment.
- Final PR + report review.

---

## 13. Open questions

- Which OP3 method do we hand-write first? (Suggest a control method — fastest path to a working contract.)
- Chem-PerturBridge checkpoint license — usable in a public PR?
- Do we need GPU for the demo, or can the 3-paper ladder stay CPU-only? (Prefer CPU-only; RepoLaunch + CUDA is the biggest schedule risk.)
- Full-text access blocker (Philipp's note) — does it bite Cecilia's contract-extraction stage, or only the literature agent?
