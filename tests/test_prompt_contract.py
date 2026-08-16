from pathlib import Path


def test_prompt_has_required_evidence_and_scope_boundaries() -> None:
    prompt = Path("psls_prompts/data_ingest_v1.md").read_text()

    assert "# Input / data sources" in prompt
    assert "Publication URL:" in prompt
    assert "Code URL:" in prompt
    assert "Local publication PDF:" in prompt
    assert "Never process FASTQs" in prompt
    assert "Do not perform differential expression" in prompt
    assert "Use `uv` for all Python dependency management and execution." in prompt
    assert "Run Python commands, scripts, and tests with `uv run`." in prompt
    assert "sc_counts_reannotated_with_counts.h5ad" not in prompt
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
    assert "control_tag" not in prompt
    assert "Preserve useful source metadata" in prompt
    assert "psls_tooling.inspect_anndata" in prompt
    assert "psls_tooling.resolve_compounds" in prompt
    assert "psls_tooling.validate_ingested_adata" in prompt
