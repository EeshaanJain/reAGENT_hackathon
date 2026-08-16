# Perturbation-prediction datasets

Each dataset has a `dataset.yaml` containing its evidence sources, prompt inputs, validation
contract reference, and subset policy. Benchmark-wide AnnData semantics live in
`../ingest_contract.yaml`; reusable implementation code lives in `src/benchmark_ingest`.

Render a dataset prompt without creating a divergent checked-in copy:

```bash
uv run python scripts/render_ingest_prompt.py \
  benchmarks/perturbation_prediction/datasets/<dataset_id>/dataset.yaml
```

Adding a dataset requires a new config directory, not changes to shared validation or rendering
code. Dataset-specific ingest scripts and final reports belong beside that dataset's config.
