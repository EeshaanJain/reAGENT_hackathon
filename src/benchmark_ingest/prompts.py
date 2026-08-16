"""Strict rendering for benchmark-local ingest prompt templates.

One template serves every dataset. Per-dataset variation is limited to the
``dataset:`` inputs (publication URL, local PDF, and optional extras such as an
accession or a code repository) plus the ``subset:`` policy, which is injected
into the prompt so the prose and the machine-readable ingest contract cannot
drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from string import Template

import yaml

from .adata import IngestContract, load_ingest_contract

# Inputs the prompt cannot be written without.
REQUIRED_DATASET_FIELDS = ("dataset_id", "publication_url")
# Inputs the prompt always names, rendering a placeholder when they are absent.
OPTIONAL_DATASET_FIELDS = ("data_url_or_accession", "code_url", "local_pdf_path")
MISSING_VALUE = "not provided"

# ``subset:`` keys the template interpolates.
REQUIRED_SUBSET_FIELDS = (
    "condition_columns",
    "minimum_condition_size",
    "target_min_cells",
    "minimum_acceptable_cells",
    "max_cells_exclusive",
)

# Extra ``dataset:`` keys are passed through as bullets, except provenance
# digests, which are recorded in config but are noise in a prompt.
_EXTRA_SUPPRESSED_SUFFIXES = ("_sha256",)
_EXTRA_LABEL_OVERRIDES = {
    "code_commit": "Code commit",
}
_EXTRA_LABEL_ACRONYMS = {"url", "id", "doi", "pdf", "hf", "geo", "sra", "ena", "api"}


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _extra_label(key: str) -> str:
    if key in _EXTRA_LABEL_OVERRIDES:
        return _EXTRA_LABEL_OVERRIDES[key]
    return " ".join(
        word.upper() if word in _EXTRA_LABEL_ACRONYMS else word.capitalize()
        for word in key.split("_")
    )


def _render_additional_sources(dataset: Mapping) -> str:
    """Render dataset keys beyond the canonical five as extra prompt bullets."""
    known = set(REQUIRED_DATASET_FIELDS) | set(OPTIONAL_DATASET_FIELDS)
    lines = []
    for key, value in dataset.items():
        if key in known or any(key.endswith(suffix) for suffix in _EXTRA_SUPPRESSED_SUFFIXES):
            continue
        if value is None or str(value).strip() == "":
            continue
        lines.append(f"- {_extra_label(key)}: `{value}`")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _render_condition_key(columns: list) -> str:
    return " × ".join(f'`obs["{column}"]`' for column in columns)


def _check_contract_agreement(subset: Mapping, contract: IngestContract, path: Path) -> None:
    """Fail when the prompt's subset policy contradicts the validation contract."""
    max_cells = int(subset["max_cells_exclusive"])
    if contract.max_obs_exclusive is not None and contract.max_obs_exclusive != max_cells:
        raise ValueError(
            f"subset.max_cells_exclusive={max_cells} disagrees with contract "
            f"limits.max_obs_exclusive={contract.max_obs_exclusive}: {path}"
        )
    minimum = int(subset["minimum_condition_size"])
    columns = tuple(str(column) for column in subset["condition_columns"])
    matching = [rule for rule in contract.group_size_rules if tuple(rule.columns) == columns]
    if not matching:
        raise ValueError(
            f"contract has no group_size_rule for condition columns {list(columns)}: {path}"
        )
    for rule in matching:
        if rule.minimum != minimum:
            raise ValueError(
                f"subset.minimum_condition_size={minimum} disagrees with contract "
                f"group_size_rule minimum={rule.minimum} for {list(columns)}: {path}"
            )


def _resolve_sibling(path: Path, config: Mapping, key: str) -> Path:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Dataset config is missing {key}: {path}")
    return (path.parent / value).resolve()


def render_ingest_prompt(config_path: str | Path, *, work_dir: str | Path | None = None) -> str:
    """Render one dataset prompt from its YAML config and benchmark template."""
    path = Path(config_path).resolve()
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, Mapping):
        raise ValueError(f"Dataset config must be a mapping: {path}")

    dataset = data.get("dataset")
    if not isinstance(dataset, Mapping):
        raise ValueError(f"Dataset config is missing a 'dataset' mapping: {path}")
    missing = [field for field in REQUIRED_DATASET_FIELDS if not dataset.get(field)]
    if missing:
        raise ValueError(f"Dataset config is missing required prompt fields: {missing}")

    subset = data.get("subset")
    if not isinstance(subset, Mapping):
        raise ValueError(f"Dataset config is missing a 'subset' mapping: {path}")
    missing_subset = [field for field in REQUIRED_SUBSET_FIELDS if subset.get(field) is None]
    if missing_subset:
        raise ValueError(f"Dataset config is missing required subset fields: {missing_subset}")

    template_path = _resolve_sibling(path, data, "prompt_template")
    contract_path = _resolve_sibling(path, data, "ingest_contract")
    contract = load_ingest_contract(contract_path)
    _check_contract_agreement(subset, contract, path)

    dataset_id = str(dataset["dataset_id"])
    max_cells = int(subset["max_cells_exclusive"])
    context = {field: str(dataset[field]) for field in REQUIRED_DATASET_FIELDS}
    context.update(
        {
            field: str(dataset[field]) if dataset.get(field) else MISSING_VALUE
            for field in OPTIONAL_DATASET_FIELDS
        }
    )
    context["additional_sources"] = _render_additional_sources(dataset)
    context["dataset_config_path"] = _display_path(path)
    context["ingest_contract_path"] = _display_path(contract_path)
    context["work_dir"] = _display_path(
        Path(work_dir).resolve() if work_dir is not None else Path("data_ingest") / dataset_id / "work"
    )
    context["max_cells_exclusive"] = f"{max_cells:,}"
    context["max_cells_inclusive"] = f"{max_cells - 1:,}"
    context["target_min_cells"] = f"{int(subset['target_min_cells']):,}"
    context["minimum_acceptable_cells"] = f"{int(subset['minimum_acceptable_cells']):,}"
    context["minimum_condition_size"] = str(int(subset["minimum_condition_size"]))
    context["condition_key"] = _render_condition_key(list(subset["condition_columns"]))

    try:
        return Template(template_path.read_text()).substitute(context)
    except KeyError as error:
        raise ValueError(f"Prompt template references unknown field {error.args[0]!r}") from error
