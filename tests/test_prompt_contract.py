from pathlib import Path

PROMPT_PATHS = sorted(Path("psls_prompts").glob("*.md"))


def test_prompts_have_required_evidence_and_scope_boundaries() -> None:
    assert PROMPT_PATHS

    for path in PROMPT_PATHS:
        prompt = path.read_text()

        assert "# Input / data sources" in prompt, path
        assert "Publication URL:" in prompt, path
        assert "Code URL" in prompt, path
        assert "Local publication PDF" in prompt, path
        assert "Never process FASTQs" in prompt, path
        assert "Do not perform differential expression" in prompt, path
        assert "Use `uv` for all Python dependency management and execution." in prompt, path
        assert "Run Python commands, scripts, and tests with `uv run`." in prompt, path
        assert "sc_counts_reannotated_with_counts.h5ad" not in prompt, path
        assert "# AnnData schema" in prompt, path
        assert "# Cell quality control" in prompt, path
        assert "# Chemical harmonization" in prompt, path
        assert "Represent single cells as rows and genes as columns." in prompt, path
        assert 'layers["counts"]' in prompt, path
        assert 'obs["dose_uM"]' in prompt, path
        assert 'obs["inchikey"]' in prompt, path
        assert 'uns["single_cell_protocol"]' in prompt, path
        assert '"3prime"' in prompt, path
        assert '"5prime"' in prompt, path
        assert "control_tag" not in prompt, path
        assert "Preserve useful source metadata" in prompt, path
        assert "psls_tooling.inspect_anndata" in prompt, path
        assert "psls_tooling.resolve_compounds" in prompt, path
        assert "psls_tooling.validate_ingested_adata" in prompt, path


def test_all_prompts_require_a_minimum_condition_size() -> None:
    for path in PROMPT_PATHS:
        prompt = path.read_text()

        assert "# Minimum condition size" in prompt, path
        assert "`MIN_CELLS_PER_CONDITION = 30`" in prompt, path
        assert (
            '`obs["sm_name"]` × `obs["timepoint_hr"]` × '
            '`obs["dose_uM"]` × `obs["cell_type"]`'
        ) in prompt, path
        assert "fewer than `MIN_CELLS_PER_CONDITION` cells" in prompt, path
        assert "fail validation" in prompt, path
