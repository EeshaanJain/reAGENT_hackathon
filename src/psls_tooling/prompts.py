"""Strict rendering for benchmark-local ingest prompt templates."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from string import Template

import yaml

REQUIRED_DATASET_FIELDS = (
    "dataset_id",
    "publication_url",
    "data_url_or_accession",
    "code_url",
    "local_pdf_path",
)


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def render_ingest_prompt(config_path: str | Path) -> str:
    """Render one dataset prompt from its YAML config and benchmark template."""
    path = Path(config_path).resolve()
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, Mapping):
        raise ValueError(f"Dataset config must be a mapping: {path}")
    dataset = data.get("dataset")
    if not isinstance(dataset, Mapping):
        raise ValueError(f"Dataset config is missing a 'dataset' mapping: {path}")
    missing = [field for field in REQUIRED_DATASET_FIELDS if field not in dataset]
    if missing:
        raise ValueError(f"Dataset config is missing required prompt fields: {missing}")
    template_value = data.get("prompt_template")
    if not isinstance(template_value, str) or not template_value.strip():
        raise ValueError(f"Dataset config is missing prompt_template: {path}")
    template_path = (path.parent / template_value).resolve()
    contract_value = data.get("ingest_contract")
    if not isinstance(contract_value, str) or not contract_value.strip():
        raise ValueError(f"Dataset config is missing ingest_contract: {path}")
    contract_path = (path.parent / contract_value).resolve()
    context = {field: str(dataset[field]) for field in REQUIRED_DATASET_FIELDS}
    context["dataset_config_path"] = _display_path(path)
    context["ingest_contract_path"] = _display_path(contract_path)
    try:
        return Template(template_path.read_text()).substitute(context)
    except KeyError as error:
        raise ValueError(f"Prompt template references unknown field {error.args[0]!r}") from error
