"""Shared fixtures for the Gauntlet. Runs the adapter under test twice per session (once on the
real id_map, once with sm_name shuffled) via the Viash shim, and hands every test module the
resulting AnnData predictions plus the frozen fixture manifest.

Usage: `pytest gauntlet --adapter <path/to/script.py>` from methods/benchmark_adapt/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anndata as ad
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))  # belt-and-suspenders; pyproject.toml's pythonpath should cover this too

from harness import viash_shim  # noqa: E402

FIXTURE_DIR = ROOT / "fixtures" / "data"
DEFAULT_ADAPTER = ROOT / "examples" / "golden_adapter" / "script.py"


def pytest_addoption(parser):
    parser.addoption("--adapter", action="store", default=str(DEFAULT_ADAPTER), help="Path to the script.py under test")
    parser.addoption("--min-change-frac", action="store", default=0.05, type=float, help="G3 sensitivity threshold override")
    parser.addoption("--stochastic-tol", action="store", default=None, type=float, help="G7 tolerance (unset by default -- see checks.py)")


@pytest.fixture(scope="session")
def fixture_manifest():
    manifest_path = FIXTURE_DIR / "fixture_manifest.json"
    if not manifest_path.exists():
        from fixtures.make_tiny_fixture import build

        build()
    return json.loads(manifest_path.read_text())


@pytest.fixture(scope="session")
def id_map_df(fixture_manifest):
    return pd.read_csv(FIXTURE_DIR / "id_map.csv")


@pytest.fixture(scope="session")
def adapter_script(request):
    path = Path(request.config.getoption("--adapter")).resolve()
    if not path.exists():
        pytest.exit(f"--adapter path does not exist: {path}", returncode=2)
    return path


@pytest.fixture(scope="session")
def min_change_frac(request):
    return float(request.config.getoption("--min-change-frac"))


@pytest.fixture(scope="session")
def stochastic_tolerance(request):
    value = request.config.getoption("--stochastic-tol")
    return float(value) if value is not None else None


def _de_train_path(fixture_manifest) -> Path:
    return (ROOT / "fixtures" / fixture_manifest["files"]["de_train"]).resolve()


def _run_adapter(adapter_script: Path, fixture_manifest: dict, id_map_path: Path, tmp_dir: Path) -> ad.AnnData:
    out_path = tmp_dir / "prediction.h5ad"
    par = {
        "de_train": str(_de_train_path(fixture_manifest)),
        "id_map": str(id_map_path),
        "output": str(out_path),
        # real wf_method.yaml argument: which de_train layer to read. Output layer name is always
        # "prediction" regardless of this value -- see checks.py's module docstring.
        "layer": fixture_manifest["input_layer_default"],
    }
    result = viash_shim.run_component(adapter_script, par, workdir=tmp_dir)
    if not result.ok:
        pytest.fail(
            f"adapter {adapter_script} exited {result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    if not out_path.exists():
        pytest.fail(f"adapter {adapter_script} exited 0 but did not write {out_path}")
    return ad.read_h5ad(out_path)


@pytest.fixture(scope="session")
def prediction(adapter_script, fixture_manifest, tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("gauntlet_real")
    return _run_adapter(adapter_script, fixture_manifest, FIXTURE_DIR / "id_map.csv", tmp_dir)


def _derange_sm_name(id_map: pd.DataFrame) -> pd.DataFrame:
    """A guaranteed no-fixed-point shuffle of sm_name within each cell_type group (rotate by one).

    A plain `.sample(frac=1)` can, by chance, land on a permutation identical to the original when
    there are only a couple of distinct compound names per group (exactly what happens with this
    tiny fixture) -- which would silently turn G3 into a no-op instead of an actual perturbation
    test. Rotation guarantees every row's sm_name differs from its original value whenever the
    group has >= 2 distinct compounds, without relying on a random seed landing right.
    """
    import numpy as np

    shuffled = id_map.copy()
    for _, group in id_map.groupby("cell_type"):
        idx = group.index
        vals = group["sm_name"].to_numpy()
        if len(vals) > 1 and len(set(vals)) > 1:
            shuffled.loc[idx, "sm_name"] = np.roll(vals, 1)
    return shuffled


@pytest.fixture(scope="session")
def prediction_shuffled(adapter_script, fixture_manifest, id_map_df, tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("gauntlet_shuffled")
    shuffled = _derange_sm_name(id_map_df)
    shuffled_path = tmp_dir / "id_map_shuffled.csv"
    shuffled.to_csv(shuffled_path, index=False)
    return _run_adapter(adapter_script, fixture_manifest, shuffled_path, tmp_dir)


@pytest.fixture(scope="session")
def prediction_rerun(adapter_script, fixture_manifest, tmp_path_factory):
    """A second independent run on the same (unshuffled) inputs, for G7 stochastic-tolerance."""
    tmp_dir = tmp_path_factory.mktemp("gauntlet_rerun")
    return _run_adapter(adapter_script, fixture_manifest, FIXTURE_DIR / "id_map.csv", tmp_dir)
