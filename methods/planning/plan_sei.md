# Methods Workstream: Perturbation Model Extraction + Execution

**Owners:** Sei, Frank, Cecilia
**Scope:** two nodes of the §9 pipeline — *sandboxed reproduction agent* and *benchmark adapter generator*. Nothing else.

---

## 1. Contract with the rest of the team

| Boundary | What we need / give | Owner |
|---|---|---|
| **In** | Paper ID + line-numbered full text, code URL, **pinned commit SHA** (not `main`), license, declared modality (chemical/genetic) | Vlad (literature) |
| **In** | `de_train.h5ad`, `de_test.h5ad`, `id_map.csv` in OP3 format; harmonized SMILES (desalted + InChIKey) | Philipp / Lijun |
| **Out** | Viash method component + PR to `EeshaanJain/openproblems` | us |
| **Out** | `MODELSPEC.json`, `DEVIATIONS.md`, agent trajectory, cost/wall-clock | → Eeshan (verifier), Sundial |
| **Out** | Scope rejections (genetic method sent to chemical task) as labeled eval data | → Vlad |
| **Not ours** | Leakage/scientific audit (Eeshan), metric design (Matt), dataset QC (Philipp/Lijun) | — |

---

## 2. Deliverable

One directory per method, PR-ready:

```
src/methods/<method_id>/
  config.vsh.yaml    # __merge__ ../../api/comp_method.yaml + docker setup + resources
  script.py          # adapter: de_train + id_map -> prediction layer
  test.py
  MODELSPEC.json     # every field cites PAPER_ID:Lstart-Lend or repo file:line
  DEVIATIONS.md      # every divergence from the paper's stated protocol
```

**Gate:** `viash ns test --query <method_id>` passes. This is validation external to the agent's own reasoning — reuse it rather than inventing a checker.

**Principle:** the agent is a *compiler*, not an interpreter. It emits a reviewable artifact once; the benchmark then runs deterministically with no LLM in the loop.

---

## 3. Pipeline

| Stage | Tool | Notes |
|---|---|---|
| 0. Ingest | Paperclip output + `git checkout <SHA>` | Vendor a snapshot. Never pull at build time. |
| 1. Environment | **RepoLaunch** | Emits working Docker image + layer-reconstructed Dockerfile + testcase-status map. Feed the Dockerfile through a deterministic transform into `engines.docker.setup`. **The agent never hand-writes the Dockerfile.** |
| 2. Repo comprehension | **Serena** (MCP, LSP) | Run *against the built image* — `find_symbol` only resolves once deps are installed. Prioritize tutorial notebooks and `examples/` over the Methods section. |
| 3. ModelSpec | mini-SWE-agent + Serena + paper text | Typed JSON, every field cited, `unknown` is legal. No guessing. |
| 4. Adapter synthesis | **mini-SWE-agent** | Iterates against a tiny fixture (~200 cells × 500 genes, 3 compounds, 2 cell types). Bash-only loop → readable trajectory = our inspectability artifact. |
| 5. Gauntlet | `viash ns test` | §5 below. |
| 6. Human review → PR | — | No auto-merge. |

---

## 4. ModelSpec (agent output, drives everything downstream)

```yaml
prediction_level: de_signature | pseudobulk | single_cell
input_layer: clipped_sign_log10_pval | logFC | ...
requires_sc_counts: bool          # <- see §6
perturbation_encoding: smiles | ecfp4 | pretrained_embedding | onehot | gene_id
gene_space: {n_genes, id_type, order_sensitive}
handles: {dose, timepoint, unseen_compound, unseen_cell_type}
compute: {gpu, vram_gb, est_runtime_min}
checkpoint: {url, sha256, license}
hyperparameters: {...}            # asserted at runtime; deviations logged
```

`perturbation_encoding: gene_id` → **refuse and return upstream.** We are the second line of scope defense; heroically adapting a genetic method into the chemical task is a failure, not a save.

---

## 5. Gauntlet (as viash tests)

OP3 already prevents the main leak structurally (regular methods never see `de_test`). We own:

1. **Layer/unit conformance.** Top silent killer: model emits `logFC`, metric expects `clipped_sign_log10_pval` (bounded ±4) → garbage scores, zero errors. Assert range, sparsity, sign symmetry.
2. **Exact `id_map` row order + gene space.** Any invocation of the metric's `--resolve_genes` rescue = hard fail.
3. **Perturbation sensitivity.** Shuffle `sm_name` → prediction must change materially. Catches collapse-to-training-mean.
4. **No network at inference.** Blocks a model re-downloading its own copy of the data.
5. **Baselines: use OP3's six existing control methods as-is.** Systema / scArchon / Ahlmann-Eltze all say simple baselines win often — a new method not clearing them is expected, not a bug.

---

## 6. Known blocker, and the plan around it

OP3's method API passes only `de_train` + `id_map`. That works for the six Kaggle-derived methods (native DE space). It **cannot express chemCPA / CPA / biolord**, which need single-cell counts living upstream of `process_dataset`.

- **Demo path:** pick methods that dodge it. **Chem-PerturBridge is ideal** — a pretrained compound representation feeding ridge/MLP → DE is fully API-compatible today.
- **PR path:** propose optional `--sc_train` gated by `requires_sc_counts`, plus a shared benchmark-owned limma lift so models aren't scored on their own DE method. File this as the finding.

---

## 7. Hackathon schedule

| Block | Work |
|---|---|
| 0–3h | **Hand-write one adapter** for an existing OP3 method. Golden reference + we learn the Viash contract. No agent yet. |
| 3–8h | RepoLaunch + Serena + mini-SWE-agent on a **3-paper difficulty ladder**: API-native / needs preprocessing reconstruction / needs single-cell (expected fail). |
| 8–12h | Gauntlet tests + MODELSPEC/DEVIATIONS emission. |
| 12–16h | **K=3 replicate agent runs on one model.** Compare score spread across generated adapters vs. spread between OP3's existing methods. |
| 16h+ | PR + report. |

**Cut:** multi-seed stats, Nextflow scale-out, GPU determinism, multi-dataset, adapter registry.

---

## 8. Headline result we're aiming for

**Adapter-induced variance vs. model-induced variance.** If K=3 agent-generated adapters for the same model spread as widely as the gap between different models, the pipeline is measuring itself, not the science. This is §11 contribution 5 and the most valuable number we can produce in a day.

**Demo the whole ladder, including the failure.** A legible failure beats a hidden success on judging criterion 3, and rung 3 produces the API-gap finding.

---

## 9. Correction to the agent-eval rubric (§9)

Drop *"numerical agreement with the paper"* as a scored metric. Our own §5 explains why: paper numbers differ because of preprocessing, gene panels, splits, and priors. Disagreement is expected and doesn't distinguish a broken harness from a different protocol.

**Score instead: does `DEVIATIONS.md` explain the gap?** Same artifact also blocks the agent from silently "fixing" the model — adding unspecified normalization, cutting epochs to make something finish. Deviations surface as a column in the results table.

---

## 10. Open questions

- Which OP3 method do we hand-write first? (Suggest a control method — fastest path to a working contract.)
- Chem-PerturBridge checkpoint license — usable in a public PR?
- Do we need GPU for the demo, or can the 3-paper ladder stay CPU-only? (Prefer CPU-only; RepoLaunch + CUDA is the biggest schedule risk.)
- Full-text access blocker (Philipp's note) — does it bite us, or only the literature agent?