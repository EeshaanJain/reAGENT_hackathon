from pathlib import Path

import pytest
import yaml

from benchmark_ingest import render_ingest_prompt

DATASET_CONFIGS = sorted(
    Path("benchmarks/perturbation_prediction/datasets").glob("*/dataset.yaml")
)


@pytest.mark.parametrize("path", DATASET_CONFIGS)
def test_rendered_prompts_have_required_contract_and_scope(path: Path) -> None:
    prompt = render_ingest_prompt(path)

    assert "${" not in prompt
    assert "# Input / data sources" in prompt
    assert "Publication URL:" in prompt
    assert "Official deposited-data URL or accession:" in prompt
    assert "Code URL" in prompt
    assert "Local publication PDF" in prompt
    assert "Never process FASTQs" in prompt
    assert "Do not perform differential expression" in prompt
    assert "Use `uv` for all Python dependency management and execution." in prompt
    assert "Run Python commands, scripts, and tests with `uv run`." in prompt
    assert "# AnnData schema" in prompt
    assert "# Cell quality control" in prompt
    assert "# Chemical harmonization" in prompt
    assert "Represent single cells as rows and genes as columns." in prompt
    assert 'layers["counts"]' in prompt
    assert 'obs["dose_uM"]' in prompt
    assert 'obs["inchikey"]' in prompt
    assert 'uns["single_cell_protocol"]' in prompt
    assert '"3prime"' in prompt
    assert '"5prime"' in prompt
    assert "Preserve useful source metadata" in prompt
    assert "benchmark_ingest.inspect_anndata" in prompt
    assert "benchmark_ingest.resolve_compounds" in prompt
    assert "benchmark_ingest.load_ingest_contract" in prompt
    assert "benchmark_ingest.validate_ingested_adata" in prompt
    assert "benchmarks/perturbation_prediction/ingest_contract.yaml" in prompt


@pytest.mark.parametrize("path", DATASET_CONFIGS)
def test_all_rendered_prompts_retain_subset_and_condition_constraints(path: Path) -> None:
    prompt = render_ingest_prompt(path)

    assert "strictly below **200,000 cells**" in prompt
    assert "# Minimum condition size" in prompt
    assert "`MIN_CELLS_PER_CONDITION = 30`" in prompt
    assert (
        '`obs["sm_name"]` × `obs["timepoint_hr"]` × '
        '`obs["dose_uM"]` × `obs["cell_type"]`'
    ) in prompt
    assert "fewer than `MIN_CELLS_PER_CONDITION` cells" in prompt
    assert "fail validation" in prompt


def test_renderer_rejects_missing_dataset_fields(tmp_path: Path) -> None:
    template = tmp_path / "prompt.md.template"
    template.write_text("${dataset_id}\n")
    config = tmp_path / "dataset.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "dataset": {"dataset_id": "incomplete"},
                "prompt_template": template.name,
            }
        )
    )

    with pytest.raises(ValueError, match="missing required prompt fields"):
        render_ingest_prompt(config)
