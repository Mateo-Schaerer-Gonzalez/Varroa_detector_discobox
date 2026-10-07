"""The threshold and the band to check by eye are chosen by where they put each
mite's death, counted as the calibration report counts it."""

import numpy as np
import pytest

from classes import calibration, death_calibration
from classes.death_calibration import LabelledRun

M, S = calibration.MOVING, calibration.STILL


def run_of(scores, states):
    states = np.array(states, dtype=object)
    return LabelledRun(scores, states == M, (states == M) | (states == S))


def test_deaths_are_counted_as_the_calibration_report_counts_them():
    rng = np.random.default_rng(0)
    scores = rng.random((20, 12))
    states = rng.choice([M, S, None], size=(20, 12), p=[0.3, 0.5, 0.2])
    run = run_of(scores, states)
    for threshold in (0.2, 0.6, 0.95):
        expected = []
        for mite in range(20):
            rows = [{"recording": r, "score": scores[mite, r], "movement": states[mite, r]}
                    for r in range(12) if states[mite, r] is not None]
            by_detector = calibration.death_recording(rows, lambda row: row["score"] >= threshold)
            expected.append(by_detector - calibration.death_recording(rows, lambda row: row["movement"] == M))
        assert list(run.death_errors(scores >= threshold)) == expected


def test_the_threshold_keeps_a_late_false_call_from_moving_the_death():
    # the mite moves twice, weakly the second time; long after, a still recording scores 4
    scores = [[9.0, 5.0, 1.0, 1.1, 0.9, 4.0, 1.0, 1.2]]
    run = run_of(scores, [[M, M, S, S, S, S, S, S]])
    threshold, error = death_calibration.best_threshold([run])
    assert 4.0 < threshold <= 5.0
    assert error == 0
    assert death_calibration.death_mae([run], [3.0])[0] == 4


def test_the_threshold_is_the_middle_of_the_widest_stretch_of_best_ones():
    run = run_of([[10.0, 2.0, 1.0]], [[M, S, S]])
    threshold, _error = death_calibration.best_threshold([run])
    assert threshold == 6.0


def test_mites_of_several_runs_are_pooled():
    first = run_of([[5.0, 1.0, 1.0]], [[M, S, S]])
    second = run_of([[5.0, 1.0, 3.0, 1.0], [1.0, 1.0, 1.0, 1.0]], [[M, S, S, S], [S, S, S, S]])
    assert death_calibration.death_mae([first, second], [2.0])[0] == 2 / 3


def test_the_observations_of_a_report_make_one_run_per_dataset():
    def row(dataset, mite, recording, score, movement):
        return {"dataset": dataset, "mite_id": mite, "recording": recording, "score": score, "movement": movement}

    rows = [row("a", "0", 0, 9.0, M), row("a", "0", 2, 4.0, S), row("a", "1", 1, 1.0, S),  # mite 0's recording 1 unlabelled
            row("b", "0", 0, 8.0, M), row("b", "0", 1, 1.0, S)]
    first, second = death_calibration.runs_of_rows(rows)
    assert first.scores.shape == (2, 3) and second.scores.shape == (1, 2)
    assert first.labelled.tolist() == [[True, False, True], [False, True, False]]
    assert first.moving.tolist() == [[True, False, False], [False, False, False]]
    for threshold in (0.5, 3.0, 5.0, 8.5):
        expected = calibration.death_errors(rows, {"t": threshold})["t"]["mae"]
        assert death_calibration.death_mae([first, second], [threshold])[0] == pytest.approx(expected)
    threshold, error = death_calibration.best_threshold([first, second])
    assert 4.0 < threshold <= 8.0 and error == 0


def test_a_band_checked_by_eye_puts_the_death_right():
    # the last movement scores 3, below a still recording's 4
    scores = [[9.0, 3.0, 1.0, 4.0, 1.0, 1.0]]
    run = run_of(scores, [[M, M, S, S, S, S]])
    assert death_calibration.best_threshold([run])[1] > 0
    outcome = death_calibration.band_outcome([run], 2.5, 4.5)
    assert outcome["mae"] == 0 and outcome["exact"] == 1
    # the still 4 is looked at first, then the 3 that shows the mite moving
    assert outcome["checks_per_mite"] == 2


def test_only_the_recordings_after_the_last_clear_movement_are_checked():
    scores = [[3.0, 9.0, 3.0, 1.0, 3.0, 1.0]]
    run = run_of(scores, [[S, M, S, S, S, S]])
    assert list(run.checks(2.0, 5.0)) == [2]


def test_the_band_stays_within_the_checks_allowed():
    scores = [[9.0, 3.0, 1.0, 4.0, 1.0, 1.0], [9.0, 1.0, 1.0, 1.0, 1.0, 1.0]]
    run = run_of(scores, [[M, M, S, S, S, S], [M, S, S, S, S, S]])
    threshold, _error = death_calibration.best_threshold([run])
    assert death_calibration.best_band([run], threshold, 0) == (threshold, threshold)
    low, high = death_calibration.best_band([run], threshold, 1)
    assert death_calibration.band_outcome([run], low, high)["mae"] == 0
