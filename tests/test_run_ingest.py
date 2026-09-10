"""Cover the codex driver's pure parts and the loosened prompt renderer.

Nothing here invokes codex; the command builder and the trace helpers are
deliberately pure so the driver can be tested without an agent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_runner import build_codex_command, find_session_id, resolve_codex_bin
from benchmark_ingest import render_ingest_prompt

CONTRACT = Path("benchmarks/perturbation_prediction/ingest_contract.yaml").resolve()
TEMPLATE = Path("benchmarks/perturbation_prediction/prompts/data_ingest.md.template").resolve()

SUBSET = {
    "condition_columns": ["sm_name", "timepoint_hr", "dose_uM", "cell_type"],
    "control_column": "control",
    "minimum_condition_size": 30,
    "target_min_cells": 195000,
    "minimum_acceptable_cells": 190000,
    "max_cells_exclusive": 200000,
    "seed": 42,
}


def write_config(tmp_path: Path, dataset: dict, subset: dict | None = None) -> Path:
    config = tmp_path / "dataset.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "dataset": dataset,
                "prompt_template": str(TEMPLATE),
                "ingest_contract": str(CONTRACT),
                "subset": dict(subset if subset is not None else SUBSET),
            }
        )
    )
    return config


# --- renderer -------------------------------------------------------------


def test_only_dataset_id_and_publication_url_are_required(tmp_path: Path) -> None:
    config = write_config(
        tmp_path, {"dataset_id": "minimal", "publication_url": "https://example.org/paper"}
    )

    prompt = render_ingest_prompt(config)

    assert "${" not in prompt
    assert "- Dataset ID: `minimal`" in prompt
    # The three optional inputs are still named, so the agent knows they are absent.
    assert "- Official deposited-data URL or accession: `not provided`" in prompt
    assert "- Code URL, if available: `not provided`" in prompt
    assert "- Local publication PDF, if available: `not provided`" in prompt


@pytest.mark.parametrize("field", ["dataset_id", "publication_url"])
def test_renderer_rejects_missing_required_fields(tmp_path: Path, field: str) -> None:
    dataset = {"dataset_id": "incomplete", "publication_url": "https://example.org/paper"}
    dataset.pop(field)

    with pytest.raises(ValueError, match="missing required prompt fields"):
        render_ingest_prompt(write_config(tmp_path, dataset))


def test_extra_dataset_keys_render_as_additional_bullets(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        {
            "dataset_id": "extras",
            "publication_url": "https://example.org/paper",
            "accession": "GSM4150378",
            "protocol_url": "https://example.org/protocol",
            "hf_revision": "2dc5790",
            # Provenance digests belong in config, not in the prompt.
            "local_pdf_sha256": "d6af84b4a72bf3b15f3fae037bdbe0e7b8901cf50f0b496a8e4ca1c00b6ee19e",
        },
    )

    prompt = render_ingest_prompt(config)

    assert "- Accession: `GSM4150378`" in prompt
    assert "- Protocol URL: `https://example.org/protocol`" in prompt
    assert "- HF Revision: `2dc5790`" in prompt
    assert "d6af84b4" not in prompt


def test_subset_values_are_injected_not_hardcoded(tmp_path: Path) -> None:
    """A benchmark with a different cap and condition key must render its own numbers."""
    contract = yaml.safe_load(CONTRACT.read_text())
    contract["limits"]["max_obs_exclusive"] = 50000
    contract["obs"]["group_size_rules"] = [{"columns": ["sm_name", "dose_uM"], "minimum": 12}]
    contract_path = tmp_path / "other_contract.yaml"
    contract_path.write_text(yaml.safe_dump(contract))

    config = tmp_path / "dataset.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "dataset": {"dataset_id": "s", "publication_url": "u"},
                "prompt_template": str(TEMPLATE),
                "ingest_contract": str(contract_path),
                "subset": dict(
                    SUBSET,
                    condition_columns=["sm_name", "dose_uM"],
                    minimum_condition_size=12,
                    max_cells_exclusive=50000,
                    target_min_cells=48000,
                    minimum_acceptable_cells=45000,
                ),
            }
        )
    )

    prompt = render_ingest_prompt(config)

    assert "strictly below **50,000 cells**" in prompt
    assert "target **48,000-49,999 cells**" in prompt
    assert "fewer than **45,000 cells**" in prompt
    assert "`MIN_CELLS_PER_CONDITION = 12`" in prompt
    assert '`obs["sm_name"]` × `obs["dose_uM"]`' in prompt
    assert "200,000" not in prompt
    # timepoint_hr is still a required obs column; it is just not part of this
    # benchmark's condition key.
    condition_section = prompt.split("# Minimum condition size")[1].split("# Gene harmonization")[0]
    assert 'obs["timepoint_hr"]' not in condition_section


def test_work_dir_is_injected(tmp_path: Path) -> None:
    config = write_config(tmp_path, {"dataset_id": "s", "publication_url": "u"})

    prompt = render_ingest_prompt(config, work_dir=tmp_path / "scratch")

    assert "scratch" in prompt


def test_subset_cap_must_match_the_contract(tmp_path: Path) -> None:
    config = write_config(
        tmp_path, {"dataset_id": "s", "publication_url": "u"}, dict(SUBSET, max_cells_exclusive=150000)
    )

    with pytest.raises(ValueError, match="max_obs_exclusive"):
        render_ingest_prompt(config)


def test_subset_condition_minimum_must_match_the_contract(tmp_path: Path) -> None:
    config = write_config(
        tmp_path, {"dataset_id": "s", "publication_url": "u"}, dict(SUBSET, minimum_condition_size=5)
    )

    with pytest.raises(ValueError, match="group_size_rule"):
        render_ingest_prompt(config)


def test_condition_columns_must_have_a_contract_rule(tmp_path: Path) -> None:
    config = write_config(
        tmp_path, {"dataset_id": "s", "publication_url": "u"}, dict(SUBSET, condition_columns=["batch"])
    )

    with pytest.raises(ValueError, match="no group_size_rule"):
        render_ingest_prompt(config)


def test_missing_subset_block_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "dataset.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "dataset": {"dataset_id": "s", "publication_url": "u"},
                "prompt_template": str(TEMPLATE),
                "ingest_contract": str(CONTRACT),
            }
        )
    )

    with pytest.raises(ValueError, match="missing a 'subset' mapping"):
        render_ingest_prompt(config)


# --- codex command --------------------------------------------------------


def test_build_codex_command_defaults(tmp_path: Path) -> None:
    command = build_codex_command(
        "/bin/codex", cwd=tmp_path, last_message_path=tmp_path / "last_message.md"
    )

    assert command[:2] == ["/bin/codex", "exec"]
    assert "--json" in command
    assert command[-1] == "-", "prompt must be read from stdin"
    assert "--sandbox" in command and command[command.index("--sandbox") + 1] == "workspace-write"
    # workspace-write denies network by default; ingests download deposited matrices.
    assert "sandbox_workspace_write.network_access=true" in command
    # Model and effort are inherited from ~/.codex/config.toml unless overridden.
    assert "--model" not in command
    assert not any("model_reasoning_effort" in part for part in command)
    # Rollouts must persist so the trace can be copied and the session resumed.
    assert "--ephemeral" not in command


def test_build_codex_command_overrides(tmp_path: Path) -> None:
    command = build_codex_command(
        "/bin/codex",
        cwd=tmp_path,
        last_message_path=tmp_path / "last_message.md",
        model="gpt-5.6-sol",
        reasoning_effort="xhigh",
        sandbox="read-only",
        network_access=False,
        web_search=False,
    )

    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="xhigh"' in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "sandbox_workspace_write.network_access=true" not in command
    assert 'web_search="live"' not in command


def test_build_codex_command_resume(tmp_path: Path) -> None:
    command = build_codex_command(
        "/bin/codex",
        cwd=tmp_path,
        last_message_path=tmp_path / "last_message.md",
        resume_session_id="01a008a1-7062-73d1-b5f4-da71e08f2c18",
    )

    assert command[1:4] == ["exec", "resume", "01a008a1-7062-73d1-b5f4-da71e08f2c18"]


def test_resolve_codex_bin_rejects_unknown_name() -> None:
    with pytest.raises(FileNotFoundError, match="not found on PATH"):
        resolve_codex_bin("definitely-not-a-real-binary-xyz")


# --- trace ----------------------------------------------------------------


def test_find_session_id_reads_the_event_stream(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            [
                "not json at all",
                json.dumps({"type": "other", "payload": {"note": "no id here"}}),
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {"session_id": "01a008a1-7062-73d1-b5f4-da71e08f2c18"},
                    }
                ),
            ]
        )
    )

    assert find_session_id(events) == "01a008a1-7062-73d1-b5f4-da71e08f2c18"


def test_find_session_id_ignores_non_uuid_values(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"id": "msg_123", "payload": {"id": "item-7"}}))

    assert find_session_id(events) is None


def test_find_session_id_tolerates_a_missing_file(tmp_path: Path) -> None:
    assert find_session_id(tmp_path / "absent.jsonl") is None
