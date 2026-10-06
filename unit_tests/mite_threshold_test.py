import numpy as np
import pytest

from classes.mite_threshold import MiteThreshold, ThresholdSearch

# Two mites under different light: A scores about 1 when still, B about 5. Each
# moves in two of its six recordings, 3 above what it scores when still.
STILL_A, STILL_B = [1.0, 1.1, 0.9, 1.0], [5.0, 5.1, 4.9, 5.0]
SERIES = {
    "a": [STILL_A[0], 4.0, STILL_A[1], STILL_A[2], 4.1, STILL_A[3]],
    "b": [STILL_B[0], 8.0, STILL_B[1], STILL_B[2], 8.1, STILL_B[3]],
}
LABELS = [False, True, False, False, True, False]
OBSERVATIONS = [(mite, recording, moving) for mite in SERIES for recording, moving in enumerate(LABELS)]


def test_without_a_window_the_offset_is_the_threshold_of_every_recording():
    threshold = MiteThreshold(3.0)
    assert threshold.thresholds([1, 5, 3]) == [3.0, 3.0, 3.0]
    assert threshold.moving([1, 5, 3]) == [False, True, True]


def test_with_a_window_the_threshold_is_the_offset_above_the_moving_median():
    threshold = MiteThreshold(0.5, window=3, centred=False)
    assert threshold.thresholds([1, 9, 2, 8]) == [1.5, 5.5, 2.5, 8.5]
    assert threshold.moving([1, 9, 2, 8]) == [False, True, False, False]


def test_from_config_reads_the_window_of_the_metric_in_use():
    class Config:
        metric = "variability"
        motion_threshold = 0.4

        @staticmethod
        def window_for(metric):
            return (5, False) if metric == "variability" else (0, True)

    assert MiteThreshold.from_config(Config).describe() == {"offset": 0.4, "window": 5, "centred": False}


def test_a_mites_own_threshold_follows_its_light_where_one_threshold_cannot():
    search = ThresholdSearch(SERIES, OBSERVATIONS)
    # no single threshold tells B still (about 5) from A moving (about 4)
    assert search.confusion(search.fit(0, True))["accuracy"] < 1
    best = search.best()
    assert best.window >= 2
    assert search.confusion(best)["accuracy"] == 1


def test_table_lists_the_single_threshold_first_then_every_window_both_ways():
    table = ThresholdSearch(SERIES, OBSERVATIONS).table()
    assert [(row["window"], row["centred"]) for row in table] == [
        (0, True), *[(window, centred) for window in range(2, 7) for centred in (True, False)]]
    assert all(0 <= row["balance"] <= 1 for row in table)


def test_the_median_is_taken_over_unlabelled_recordings_too():
    # only the moving recordings and one still one are labelled
    search = ThresholdSearch(SERIES, [("a", 1, True), ("a", 0, False), ("b", 1, True), ("b", 0, False)])
    # a window reaching over all six recordings: the median of each mite's whole series
    assert search.above(12, True).tolist() == pytest.approx([4.0 - 1.05, 1.0 - 1.05, 8.0 - 5.05, 5.0 - 5.05])


def test_wrong_calls_gather_on_the_mites_that_move_most():
    # C moves in five of six recordings: its median is its movement, not its noise
    series = {**SERIES, "c": [8.0, 8.2, 7.9, 8.1, 5.0, 8.3]}
    observations = OBSERVATIONS + [("c", recording, recording != 4) for recording in range(6)]
    search = ThresholdSearch(series, observations)
    rows = {row["share"]: row for row in search.by_share_moving(MiteThreshold(1.5, 6, True))}
    assert rows["up to 50%"] == {"share": "up to 50%", "n_mites": 2, "n": 12, "n_wrong": 0}
    assert rows["up to 100%"]["n_mites"] == 1 and rows["up to 100%"]["n_wrong"] == 5


def test_held_out_judges_the_choice_on_mites_it_never_saw():
    series, observations = {}, []
    rng = np.random.default_rng(0)
    for mite in range(12):
        still = rng.uniform(1, 6)
        scores = [still + (3 if moving else 0) + rng.normal(0, 0.05) for moving in LABELS]
        series[mite] = scores
        observations += [(mite, recording, moving) for recording, moving in enumerate(LABELS)]
    held = ThresholdSearch(series, observations).held_out(repeats=5)
    assert held["repeats"] == 5
    assert held["own"] == 1
    assert held["single"] < 1


def test_held_out_is_nothing_without_both_labels():
    search = ThresholdSearch({"a": [1, 2]}, [("a", 0, False), ("a", 1, False)])
    assert search.held_out() is None
