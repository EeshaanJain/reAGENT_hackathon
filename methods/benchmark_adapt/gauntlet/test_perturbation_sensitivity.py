"""G3 -- shuffle sm_name, require the prediction to change materially. Catches a model that has
collapsed to predicting the training mean. examples/broken_adapter/script.py includes a
mean-collapse variant specifically so this test has something real to catch.
"""

from gauntlet.checks import check_perturbation_sensitivity


def test_prediction_changes_when_compound_labels_are_shuffled(prediction, prediction_shuffled, fixture_manifest, min_change_frac):
    result = check_perturbation_sensitivity(
        prediction, prediction_shuffled, fixture_manifest["output_layer"], min_median_rel_change=min_change_frac
    )
    result.assert_ok()
