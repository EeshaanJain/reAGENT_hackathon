# Perturbation-prediction datasets

One prompt template serves every dataset
(`../prompts/data_ingest.md.template`). The only thing that changes per dataset are
the inputs — publication URL, local PDF, and optionally a deposited-data URL, a code
repository, an accession, or anything else worth telling the agent.

## Ingesting a dataset

```bash
uv run python scripts/run_ingest.py \
  --dataset-id emerald_bay_2026 \
  --publication-url https://www.biorxiv.org/content/10.64898/2026.06.09.731197v1 \
  --pdf data/2026.06.09.731197.full.pdf \
  --data-url https://huggingface.co/datasets/tahoebio/EmeraldBay
```

That writes `datasets/<dataset_id>/dataset.yaml`, renders the shared prompt, runs
`codex exec` unattended, keeps the full agent trace, and then independently reopens the
resulting H5AD and validates it against `../ingest_contract.yaml`. Re-run an existing
dataset with `--config datasets/<dataset_id>/dataset.yaml`.

Useful flags: `--code-url`, `--extra KEY=VALUE` (repeatable; becomes an extra prompt
bullet), `--prepare-only` (render and print the command, run nothing), `--model`,
`--reasoning-effort`, `--timeout` (default 6h), `--resume <session_id>`.

To render a prompt on its own:

```bash
uv run python scripts/render_ingest_prompt.py datasets/<dataset_id>/dataset.yaml
```

## What is committed, and what is not

Committed, per dataset:

| file | author | contents |
| --- | --- | --- |
| `dataset.yaml` | driver or hand | uniform prompt inputs, subset policy, template/contract refs |
| `ingest_params.yaml` | agent | facts discovered during ingest: source URLs and checksums, control mapping, assay chemistry, pinned annotation release |
| `ingest.py` | agent | rerunnable ingest reading both YAML files; no hardcoded URLs or labels |
| `ingest_report.md` | agent | sources, mappings, QC decisions, loss ledger, validation results |

Everything else is scratch and gitignored:

```
data_ingest/<dataset_id>/work/            preflight audits, chunk shards, cached lookups
data_ingest/<dataset_id>/runs/<stamp>/    prompt.md, events.jsonl, stderr.log,
                                          command.json, last_message.md,
                                          rollout.jsonl, run.json
```

`run.json` records the resolved codex binary and version, model, sandbox, exit code,
session id, SHA-256 of the prompt/template/contract/config, the repo revision, and the
independent artifact verification.

## Keeping prose and contract in step

The subset numbers in the prompt (cell cap, target, condition minimum, condition key)
are **not** written in the template — they are injected from each `dataset.yaml`'s
`subset:` block, and rendering fails if that block contradicts
`../ingest_contract.yaml` (`limits.max_obs_exclusive`, `obs.group_size_rules`). Change a
limit in one place and the mismatch surfaces before any agent time is spent.

Adding a dataset requires a new config directory, not changes to shared validation or
rendering code.
