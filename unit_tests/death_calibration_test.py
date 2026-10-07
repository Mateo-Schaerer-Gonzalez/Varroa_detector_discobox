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


def test_the_death_error_by_threshold_is_lowest_at_the_suggested_one():
    rng = np.random.default_rng(3)
    # 12 mites over 40 recordings: still around 1.5, moving around 6 until each one's death
    scores = rng.normal(1.5, 0.2, (12, 40))
    states = np.full((12, 40), S, dtype=object)
    for mite, death in enumerate(rng.integers(5, 30, 12)):
        moves = rng.random(death) < 0.5
        scores[mite, :death][moves] = rng.normal(6, 1.5, moves.sum())
        states[mite, :death][moves] = M
    run = run_of(scores, states)
    suggested, error = death_calibration.best_threshold([run])
    curve = death_calibration.death_curve([run], [1.6, suggested])
    assert curve["n_mites"] == 12 and len({len(curve[key]) for key in ("thresholds", "mae", "n_early", "n_late", "n_exact")}) == 1
    at = curve["thresholds"].index(round(suggested, 4))
    assert curve["mae"][at] == pytest.approx(error, abs=1e-3) == min(curve["mae"])
    assert round(1.6, 4) in curve["thresholds"]  # the other threshold marked is on the chart too
    for index, threshold in enumerate(curve["thresholds"]):
        off = run.death_errors(scores >= threshold)
        assert (curve["n_early"][index], curve["n_late"][index], curve["n_exact"][index]) == (
            (off < 0).sum(), (off > 0).sum(), (off == 0).sum())
    # cut where the error is far above the worst of the two marked
    assert max(curve["mae"]) <= max(3 * max(curve["mae"][at], curve["mae"][curve["thresholds"].index(1.6)]), 1.0)
    # a threshold marked outside the scores, e.g. one saved for another metric, is left off
    assert max(death_calibration.death_curve([run], [500.0, suggested])["thresholds"]) < 500


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


def test_the_checks_are_counted_from_the_last_close_call_back_to_the_first_movement():
    rng = np.random.default_rng(5)
    scores = rng.random((30, 25)) * 6
    states = rng.choice([M, S, None], size=(30, 25), p=[0.2, 0.7, 0.1])
    run = run_of(scores, states)
    for low, high in ((2.0, 4.0), (0.5, 5.5), (3.0, 3.0)):
        expected = []
        for mite in range(30):
            labelled = [r for r in range(25) if states[mite, r] is not None]
            clear = [r for r in labelled if scores[mite, r] >= high]
            close = [r for r in labelled if low <= scores[mite, r] < high and r > (clear[-1] if clear else -1)][::-1]
            moved = [index for index, r in enumerate(close) if states[mite, r] == M]
            expected.append(moved[0] + 1 if moved else len(close))
        assert list(run.checks(low, high)) == expected


def test_what_the_checks_buy_goes_from_the_threshold_alone_to_the_best_band():
    # mite 0: a weak last movement (3) and, later, a still recording scoring 4; mite 1 is clear
    scores = [[9.0, 3.0, 1.0, 4.0, 1.0, 1.0], [9.0, 1.0, 1.0, 1.0, 1.0, 1.0]]
    run = run_of(scores, [[M, M, S, S, S, S], [M, S, S, S, S, S]])
    threshold, error = death_calibration.best_threshold([run])
    grid = death_calibration.band_grid([run], threshold)
    assert (grid[0]["low"], grid[0]["high"], grid[0]["checks_per_mite"]) == (threshold, threshold, 0)
    assert grid[0]["mae"] == error
    frontier = death_calibration.checks_frontier(grid)
    assert frontier[0] == grid[0] and frontier[-1]["mae"] == 0
    assert [band["mae"] for band in frontier] == sorted((band["mae"] for band in frontier), reverse=True)
    assert [band["checks_per_mite"] for band in frontier] == sorted(band["checks_per_mite"] for band in frontier)
    # the band for a number of checks is the last of them within it
    for allowed in (0, 0.5, 1, 5):
        low, high = death_calibration.best_band([run], threshold, allowed, grid=grid)
        within = [band for band in frontier if band["checks_per_mite"] <= allowed]
        assert death_calibration.band_outcome([run], low, high)["mae"] == within[-1]["mae"]


def test_the_band_stays_within_the_checks_allowed():
    scores = [[9.0, 3.0, 1.0, 4.0, 1.0, 1.0], [9.0, 1.0, 1.0, 1.0, 1.0, 1.0]]
    run = run_of(scores, [[M, M, S, S, S, S], [M, S, S, S, S, S]])
    threshold, _error = death_calibration.best_threshold([run])
    assert death_calibration.best_band([run], threshold, 0) == (threshold, threshold)
    low, high = death_calibration.best_band([run], threshold, 1)
    assert death_calibration.band_outcome([run], low, high)["mae"] == 0
