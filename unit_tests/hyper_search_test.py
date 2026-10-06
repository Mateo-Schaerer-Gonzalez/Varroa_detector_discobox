"""The hyperparameter search: what can be searched, how one set of values is
judged on mites its threshold never saw, and what a search reports."""

import numpy as np
import pytest

from classes.hyper_search import CENTRED, SCALE, STABILIZE, WINDOW, HyperSearch, SearchSpace

pytest.importorskip("optuna")

TIMES = [5.0 * recording for recording in range(8)]
N_MITES = 12


def labels(mite):
    """Mite `mite` moves in its first few recordings, then never again."""
    return [recording < 2 + mite % 4 for recording in range(len(TIMES))]


OBSERVATIONS = [(mite, recording, moving) for mite in range(N_MITES) for recording, moving in enumerate(labels(mite))]


def score(metric_params, stabilize):
    """A metric that tells moving from still only near n = 100, and only on a
    stabilized plate: elsewhere the still recordings score as high as the moving."""
    rng = np.random.default_rng(0)
    blur = abs(metric_params["n"] - 100) / 50 + (0 if stabilize else 3)
    return {mite: [1 + (5 if moving else 0) + blur * rng.uniform(0, 3) for moving in labels(mite)]
            for mite in range(N_MITES)}


def values(**changed):
    return {"n": 600, STABILIZE: True, WINDOW: 0, CENTRED: True, SCALE: 0.0, **changed}


def search(searched, n_trials=25, **changed):
    space = SearchSpace("topN_variability", n_recordings=len(TIMES), n_frames=30)
    return HyperSearch(space, values(**changed), searched, score, OBSERVATIONS, TIMES, n_trials)


def test_the_space_lists_the_metrics_parameters_and_the_thresholds():
    names = [spec["name"] for spec in SearchSpace("topN_binary_flux").specs()]
    assert names == ["threshold", "n", STABILIZE, WINDOW, CENTRED, SCALE]
    # a metric without parameters still has the plate and the threshold
    assert [spec["name"] for spec in SearchSpace("max_diff").specs()] == [STABILIZE, WINDOW, CENTRED, SCALE]
    with pytest.raises(ValueError):
        SearchSpace("max_diff").spec("n")


def test_optical_flows_step_stays_below_the_frames_of_a_recording():
    assert SearchSpace("optical_flow", n_frames=10).spec("step")["high"] == 9


def test_the_window_is_none_or_at_least_two_recordings():
    spec = SearchSpace("max_diff", n_recordings=6).spec(WINDOW)
    assert [value for value in range(8) if SearchSpace.holds(spec, value)] == [0, 2, 3, 4, 5, 6]
    assert SearchSpace.as_suggested(spec, 0) == 1


def test_a_set_of_values_is_judged_on_mites_its_threshold_never_saw():
    judged = search(["n"]).judge(values(n=100))
    # scores that tell moving from still give every death time, held out or not
    assert judged["value"] == 0 and judged["mae_all"] == 0
    assert len(judged["errors"]) == N_MITES and len(judged["folds"]) == HyperSearch.FOLDS
    assert judged["metric_params"] == {"n": 100}

    blurred = search(["n"]).judge(values(n=600))
    assert blurred["value"] > 0
    # fitted on the mites it is judged on, a threshold looks no worse than held out
    assert blurred["mae_all"] <= blurred["value"] + 1e-9


def test_the_search_finds_values_better_than_those_in_use():
    found = search(["n"])
    found.run()
    described = found.describe()
    assert described["n_done"] == 25 and len(described["trials"]) == 25
    # it starts from the values in use
    assert described["trials"][0]["values"] == {"n": 600}
    assert described["trials"][0]["value"] == pytest.approx(described["baseline"]["mean"], abs=1e-3)
    assert described["best"]["mean"] < described["baseline"]["mean"]
    assert described["difference"]["mean"] < 0
    assert described["best"]["low"] <= described["best"]["mean"] <= described["best"]["high"]
    assert abs(described["best"]["metric_params"]["n"] - 100) < abs(600 - 100)
    # the best so far never rises
    so_far = [trial["best_so_far"] for trial in described["trials"]]
    assert so_far == sorted(so_far, reverse=True) and so_far[-1] == pytest.approx(described["best"]["mean"], abs=1e-3)
    plateau = described["plateau"]["values"]["n"]
    assert plateau["low"] <= described["best"]["metric_params"]["n"] <= plateau["high"]


def test_what_is_not_searched_keeps_its_value():
    found = search([WINDOW, SCALE], n_trials=8, n=100)
    found.run()
    described = found.describe()
    assert all(set(trial["values"]) == {WINDOW, SCALE} for trial in described["trials"])
    assert described["best"]["metric_params"] == {"n": 100} and described["best"]["stabilize"] is True
    assert all(trial["values"][WINDOW] != 1 for trial in described["trials"])
    # one threshold for every mite has no MADs to rise by
    assert described["best"]["scale"] == 0 or described["best"]["window"]


def test_the_scores_of_a_movement_score_are_worked_out_once():
    calls = []

    def counting(metric_params, stabilize):
        calls.append((metric_params["n"], stabilize))
        return score(metric_params, stabilize)

    space = SearchSpace("topN_variability", n_recordings=len(TIMES), n_frames=30)
    found = HyperSearch(space, values(n=100), [WINDOW, CENTRED, SCALE], counting, OBSERVATIONS, TIMES, 10)
    found.run()
    assert calls == [(100, True)]


def test_importances_say_which_hyperparameter_matters():
    found = search(["n", STABILIZE, CENTRED], n_trials=40)
    found.run()
    importances = found.describe()["importances"]
    assert importances is None or (set(importances) == {"n", STABILIZE, CENTRED}
                                   and importances[CENTRED] < max(importances["n"], importances[STABILIZE]))


def test_a_shaking_plate_is_judged_at_the_threshold_fitted_on_the_steady_one():
    found = search(["n"], n=100)
    steady = found.judge(values(n=100))
    steady["values"] = values(n=100)
    assert found.shaken_error(steady, score({"n": 100}, True)) == steady["mae_all"] == 0
    # shaken: every still recording scores as high as a moving one, and no mite dies
    shaken = {mite: [9.0] * len(TIMES) for mite in range(N_MITES)}
    assert found.shaken_error(steady, shaken) > 10


def test_a_stopped_search_keeps_its_trials():
    found = search(["n"], n_trials=50)
    stopping = found.judge

    def judge_then_stop(given):
        if len(found.trials) >= 3:
            found.stop()
        return stopping(given)

    found.judge = judge_then_stop
    found.run()
    assert 3 <= len(found.trials) < 50
    assert found.describe()["best"] is not None


def test_a_search_needs_something_to_search_and_two_mites():
    with pytest.raises(ValueError):
        search([])
    space = SearchSpace("topN_variability", n_recordings=2)
    lonely = HyperSearch(space, values(), ["n"], lambda _params, _stabilize: {"a": [1.0, 2.0]},
                         [("a", 0, True), ("a", 1, False)], [0, 5], 3)
    with pytest.raises(ValueError):
        lonely.run()
