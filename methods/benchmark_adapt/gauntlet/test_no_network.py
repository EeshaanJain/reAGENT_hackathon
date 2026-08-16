"""G4 -- no network at inference. Blocks a model from re-downloading its own copy of the
evaluation data -- a leak that no amount of API-level discipline upstream would catch. The check
has to wrap the adapter's actual execution (in-subprocess), not just inspect its output -- see
harness/viash_shim.py's block_network option.
"""

from pathlib import Path

from harness import viash_shim

ROOT = Path(__file__).parent.parent


def test_inference_succeeds_with_network_blocked(adapter_script, fixture_manifest, id_map_df, tmp_path):
    out_path = tmp_path / "prediction.h5ad"
    par = {
        "de_train": str((ROOT / "fixtures" / fixture_manifest["files"]["de_train"]).resolve()),
        "id_map": str((ROOT / "fixtures" / "data" / "id_map.csv").resolve()),
        "output": str(out_path),
        "layer": fixture_manifest["input_layer_default"],
    }
    result = viash_shim.run_component(adapter_script, par, workdir=tmp_path, block_network=True)
    assert result.ok, (
        f"adapter failed with network blocked (returncode={result.returncode}) -- either it tried "
        f"to reach the network during inference, or it failed for an unrelated reason:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert out_path.exists(), "adapter exited 0 with network blocked but produced no output"
