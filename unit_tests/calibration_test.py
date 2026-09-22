import numpy as np
import pytest

from classes import app_config
from classes.calibration import (
    auc,
    best_threshold,
    confusion,
    forward_max,
    has_both_classes,
    is_rejected,
    match_ground_truth,
    outcome,
    per_recording,
    roc_curve,
    survival,
)

# Three dead mites that barely move and three alive ones that do, with one of each
# on the wrong side of a threshold of 10.
SCORES = [1.0, 2.0, 12.0, 8.0, 20.0, 30.0]
ALIVE = [False, False, False, True, True, True]


def test_roc_runs_from_nothing_called_alive_to_everything():
    fpr, tpr, thresholds = roc_curve(SCORES, ALIVE)
    assert (fpr[0], tpr[0]) == (0, 0) and np.isinf(thresholds[0])
    assert (fpr[-1], tpr[-1]) == (1, 1) and thresholds[-1] == 1.0
    assert np.all(np.diff(fpr) >= 0) and np.all(np.diff(tpr) >= 0)


def test_roc_needs_both_classes():
    with pytest.raises(ValueError):
        roc_curve([1, 2], [True, True])


def test_auc_perfect_chance_and_ties():
    assert auc([1, 2, 10, 20], [False, False, True, True]) == 1.0
    assert auc([1, 1], [False, True]) == 0.5
    # 8 of the 9 alive/dead pairs are ordered correctly (8 < 12 is the exception)
    assert auc(SCORES, ALIVE) == pytest.approx(8 / 9)


def test_best_threshold_sits_in_the_gap_between_the_classes():
    assert best_threshold([1, 2, 10, 20], [False, False, True, True]) == 6.0


def test_best_threshold_maximises_sensitivity_plus_specificity():
    threshold = best_threshold(SCORES, ALIVE)
    result = confusion(SCORES, ALIVE, threshold)
    j = result["sensitivity"] + result["specificity"]
    for candidate in np.linspace(0, 35, 200):
        other = confusion(SCORES, ALIVE, candidate)
        assert other["sensitivity"] + other["specificity"] <= j + 1e-9


def test_confusion_counts():
    result = confusion(SCORES, ALIVE, 10)
    assert result["alive_ok"] == 2 and result["alive_missed"] == 1
    assert result["dead_ok"] == 2 and result["dead_missed"] == 1
    assert result["accuracy"] == pytest.approx(4 / 6)
    assert result["sensitivity"] == pytest.approx(2 / 3)


def test_outcome_uses_at_or_above_threshold_as_alive():
    assert outcome("alive", 10, 10) == "alive_ok"
    assert outcome("dead", 10, 10) == "dead_missed"
    assert outcome("dead", 9.9, 10) == "dead_ok"
    assert outcome("not_a_mite", 50, 10) is None


def test_ground_truth_matched_by_nearest_position():
    mites = [{"id": "0", "x": 100, "y": 100}, {"id": "1", "x": 108, "y": 100}, {"id": "2", "x": 500, "y": 500}]
    saved = [
        {"x": 107, "y": 101, "truth": ["alive", "dead"]},   # closest to mite 1, not mite 0
        {"x": 99, "y": 100, "truth": ["alive", None]},
        {"x": 900, "y": 900, "truth": ["alive", "alive"]},  # no mite near it any more
    ]
    assert match_ground_truth(mites, saved, n_recordings=2) == {"0": ["alive", None], "1": ["alive", "dead"]}


def test_ground_truth_ignores_unknown_states():
    saved = [{"x": 0, "y": 0, "truth": ["maybe", "maybe"]}]
    assert match_ground_truth([{"id": "0", "x": 0, "y": 0}], saved, n_recordings=2) == {}


def test_ground_truth_fits_the_number_of_recordings():
    # an old single status applies to every recording; a list is cut or padded
    assert per_recording("dead", 3) == ["dead", "dead", "dead"]
    assert per_recording(["alive"], 3) == ["alive", None, None]
    assert per_recording(["alive", "dead", "dead", "dead"], 2) == ["alive", "dead"]


def test_rejection_is_any_not_a_mite_mark():
    assert is_rejected(["not_a_mite", "not_a_mite"])
    assert is_rejected("not_a_mite")
    assert not is_rejected(["alive", None])


def test_forward_max_is_the_best_score_from_each_recording_on():
    # moved in recordings 0 and 2, still from 3 on
    assert forward_max([20, 1, 18, 2, 3]) == [20, 18, 18, 3, 3]


def test_survival_compares_truth_and_detector_on_the_same_observations():
    observations = [
        {"recording": 0, "truth": "alive", "score": 20},
        {"recording": 0, "truth": "alive", "score": 5},   # a miss at threshold 10
        {"recording": 1, "truth": "dead", "score": 5},
    ]
    result = survival(observations, 3, {"current": 10})
    assert result["n"] == [2, 1, 0]
    assert result["truth"] == [1.0, 0.0, None]
    assert result["current"] == [0.5, 0.0, None]


def test_has_both_classes():
    assert has_both_classes([True, False])
    assert not has_both_classes([True, True])


def test_save_motion_threshold_keeps_the_rest_of_the_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mite:\n  radius: 8\n  motion_threshold: 15.654   # tuned by hand\n  metric: \"variability\"\n")

    assert app_config.save_motion_threshold(9.12345, path) == 9.123

    text = path.read_text()
    assert "motion_threshold: 9.123   # tuned by hand" in text
    assert "radius: 8" in text and 'metric: "variability"' in text


def test_save_motion_threshold_refuses_a_file_without_one(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mite:\n  radius: 8\n")
    with pytest.raises(ValueError):
        app_config.save_motion_threshold(3, path)
