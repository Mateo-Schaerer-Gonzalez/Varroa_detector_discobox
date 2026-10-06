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


def test_with_a_scale_the_threshold_rises_with_the_mites_noise():
    quiet, noisy = [1.0, 1.1, 0.9, 1.0, 1.1], [1.0, 2.0, 0.0, 1.0, 2.0]
    threshold = MiteThreshold(0.5, window=5, scale=2)
    # the same median, 1.0; the MADs are 0.1 and 1.0
    assert threshold.thresholds(quiet)[2] == pytest.approx(1.0 + 0.5 + 2 * 0.1)
    assert threshold.thresholds(noisy)[2] == pytest.approx(1.0 + 0.5 + 2 * 1.0)
    assert MiteThreshold(0.5, window=5).thresholds(noisy)[2] == pytest.approx(1.5)
    # without a window there is no noise to scale by
    assert MiteThreshold(0.5, scale=2).thresholds(noisy) == [0.5] * 5


def test_from_config_reads_the_window_and_scale_of_the_metric_in_use():
    class Config:
        metric = "variability"
        motion_threshold = 0.4

        @staticmethod
        def window_for(metric):
            return (5, False) if metric == "variability" else (0, True)

        @staticmethod
        def scale_for(metric):
            return 2.0 if metric == "variability" else 0.0

    assert MiteThreshold.from_config(Config).describe() == {"offset": 0.4, "window": 5, "centred": False, "scale": 2.0}


def test_a_mites_own_threshold_follows_its_light_where_one_threshold_cannot():
    search = ThresholdSearch(SERIES, OBSERVATIONS)
    # no single threshold tells B still (about 5) from A moving (about 4)
    assert search.confusion(search.fit(0, True))["accuracy"] < 1
    best = search.best()
    assert best.window >= 2
    assert search.confusion(best)["accuracy"] == 1


def test_table_lists_the_single_threshold_first_then_every_window_both_ways_at_every_scale():
    table = ThresholdSearch(SERIES, OBSERVATIONS).table()
    assert [(row["window"], row["centred"], row["scale"]) for row in table] == [
        (0, True, 0), *[(window, centred, scale) for window in range(2, 7) for centred in (True, False)
                        for scale in ThresholdSearch.SCALES]]
    assert all(0 <= row["balance"] <= 1 and row["mae"] >= 0 for row in table)
    # one row of each window is its best scale
    assert sum(row["best_of_window"] for row in table) == 1 + 5 * 2


def test_death_times_are_those_of_the_survival_curves():
    # recordings every 5 minutes; a mite labelled in all six
    times = [0, 5, 10, 15, 20, 25]
    search = ThresholdSearch({"a": [0] * 6}, [("a", recording, False) for recording in range(6)], times)

    def death(moving):
        return search.death_times(moving)[0]

    # dead at the first recording after the last one it moved in
    assert death([True, True, False, True, False, False]) == 20
    # never moving: dead from its first recording
    assert death([False] * 6) == 0
    # moving in its last recording: dead one recording later, the earliest it can have
    assert death([True] * 6) == 30


def test_death_times_go_by_the_labelled_recordings_only():
    times = [0, 5, 10, 15]
    search = ThresholdSearch({"a": [0] * 4}, [("a", 0, True), ("a", 3, False)], times)
    assert search.truth_death.tolist() == [15]
    assert search.death_times([False, False]).tolist() == [0]


def test_death_error_is_the_mean_distance_between_the_death_times():
    times = [0, 5, 10, 15]
    series = {"a": [9, 9, 1, 1], "b": [9, 1, 1, 1]}
    labels = {"a": [True, True, False, False], "b": [True, False, False, False]}
    search = ThresholdSearch(series, [(mite, recording, moving) for mite in series
                                      for recording, moving in enumerate(labels[mite])], times)
    assert search.truth_death.tolist() == [10, 5]
    # a threshold that calls them as labelled
    assert search.death_error(search.calls(MiteThreshold(5))) == {"mae": 0, "bias": 0, "n_mites": 2, "n_exact": 2}
    # one calling every recording moving: both die at 20, 10 and 15 minutes late
    error = search.death_error(search.calls(MiteThreshold(0)))
    assert error == {"mae": 12.5, "bias": 12.5, "n_mites": 2, "n_exact": 0}


def test_the_fit_minimises_the_death_time_error_not_the_wrong_calls():
    times = list(range(0, 50, 5))
    # A stops moving after 10 minutes, but one late still recording scores as
    # high as its movement; B moves weakly throughout.
    series = {"a": [9, 9, 9, 1, 1, 1, 1, 1, 9, 1], "b": [4, 4, 4, 4, 4, 4, 4, 4, 4, 4]}
    labels = {"a": [True, True, True] + [False] * 7, "b": [True] * 10}
    search = ThresholdSearch(series, [(mite, recording, moving) for mite in series
                                      for recording, moving in enumerate(labels[mite])], times)
    fit = search.fit(0, True)
    # 1 < threshold <= 4 calls one observation wrong, yet has A die 30 minutes late;
    # no threshold gives both death times, and the best error is the same
    # either side of A's late score, so the better-balanced one wins
    assert search.mae(fit) == pytest.approx(min(search.mae(MiteThreshold(value)) for value in (0.5, 2.5, 6.5)))
    offsets, maes = search.mae_curve(0, True)
    assert offsets.tolist() == [1, 2.5, 6.5]
    assert maes.tolist() == pytest.approx([search.mae(MiteThreshold(offset)) for offset in offsets])


def test_the_error_at_every_offset_is_the_one_counted_mite_by_mite():
    rng = np.random.default_rng(1)
    series, observations = {}, []
    for mite in range(8):
        series[mite] = rng.uniform(0, 10, 9).round(1)
        observations += [(mite, recording, bool(rng.random() < 0.4)) for recording in range(9) if rng.random() < 0.8]
    search = ThresholdSearch(series, observations, [7 * recording for recording in range(9)])
    for window, centred, scale in [(0, True, 0), (4, True, 0), (5, False, 2), (9, True, 4)]:
        offsets, maes = search.mae_curve(window, centred, scale)
        assert maes.tolist() == pytest.approx(
            [search.mae(MiteThreshold(offset, window, centred, scale)) for offset in offsets])
        fit = search.fit(window, centred, scale)
        assert search.mae(fit) == pytest.approx(maes.min())


def test_the_scale_tells_noisy_mites_from_moving_ones():
    # Quiet mites move 2 above their median; noisy ones scatter that far while still.
    rng = np.random.default_rng(2)
    series, observations = {}, []
    for mite in range(10):
        noise = 0.05 if mite % 2 else 1.0
        moving = [recording < 4 for recording in range(16)] if mite % 2 else [False] * 16
        series[mite] = [3 + rng.normal(0, noise) + (2 if moves else 0) for moves in moving]
        observations += [(mite, recording, moves) for recording, moves in enumerate(moving)]
    search = ThresholdSearch(series, observations)
    own = search.best(scaled=False)
    assert own.scale == 0
    best = search.best()
    assert best.scale > 0
    assert search.mae(best) < search.mae(own)


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
    # the death times of the other half, exactly; one threshold for all cannot
    assert held["own"] == 0
    assert held["single"] > 0
    assert held["scaled"] >= 0


def test_held_out_is_nothing_with_a_single_mite():
    search = ThresholdSearch({"a": [1, 2]}, [("a", 0, False), ("a", 1, False)])
    assert search.held_out() is None
