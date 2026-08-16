"""G6 -- output sanity: expected shape, declared layer present, no NaN/Inf."""

from gauntlet.checks import check_output_sanity


def test_output_shape_and_finiteness(prediction, fixture_manifest):
    result = check_output_sanity(prediction, fixture_manifest["output_layer"], fixture_manifest["n_genes"])
    result.assert_ok()
