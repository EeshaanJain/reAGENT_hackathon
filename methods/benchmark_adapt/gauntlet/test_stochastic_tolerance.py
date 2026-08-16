"""G7 -- "repeated runs are identical or within an explicitly defined stochastic tolerance."
No document in this workstream ever defines that tolerance number. This test does not invent one:
it skips, loudly, until --stochastic-tol is passed (or BENCHMARK_ADAPT_STOCHASTIC_TOL is set).
Silently defaulting to *some* number would make this check pass without anyone having actually
decided what "reproducible" means for a given method -- worse than not having the check at all.
"""

import pytest

from gauntlet.checks import check_stochastic_tolerance


def test_repeated_runs_within_tolerance(prediction, prediction_rerun, fixture_manifest, stochastic_tolerance):
    if stochastic_tolerance is None:
        pytest.skip(
            "G7 not configured: pass --stochastic-tol=<float> (see todo.html gap list and "
            "README 'what's real vs. a stand-in') -- this is a decision the team owes, not a bug"
        )
    result = check_stochastic_tolerance(prediction, prediction_rerun, fixture_manifest["output_layer"], stochastic_tolerance)
    result.assert_ok()
