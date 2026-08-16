"""G1 -- layer/unit conformance. The plan's own acceptance criterion: "write the failing case
first -- a check you've never seen fail isn't a check." examples/broken_adapter/script.py exists
specifically to fail this test (it emits `logFC` instead of the required "prediction" layer).

Output layer is always literally "prediction" (file_prediction.yaml; verified against
src/methods/scape/script.py's real `layers={"prediction": ...}`). The bounds checked here are
whatever the fixture's `--layer` selection implies (default clipped_sign_log10_pval, +/-4) -- the
model was asked to operate in that semantic space via `par['layer']`, so its "prediction" output
is expected to land in the same range.
"""

from gauntlet.checks import check_layer_conformance


def test_layer_present_finite_and_in_range(prediction, fixture_manifest):
    result = check_layer_conformance(prediction, fixture_manifest["output_layer"], tuple(fixture_manifest["input_layer_bounds"]))
    result.assert_ok()
