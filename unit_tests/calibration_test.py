import yaml
import numpy as np
import pytest

from classes import app_config
from classes.calibration import (
    auc,
    best_threshold,
    confusion,
    has_both_classes,
    is_rejected,
    match_ground_truth,
    moving_over_time,
    outcome,
    per_recording,
    roc_curve,
)

# Three still observations that barely score and three moving ones that do, with
# one of each on the wrong side of a threshold of 10.
SCORES = [1.0, 2.0, 12.0, 8.0, 20.0, 30.0]
MOVING = [False, False, False, True, True, True]


def test_roc_runs_from_nothing_called_moving_to_everything():
    fpr, tpr, thresholds = roc_curve(SCORES, MOVING)
    assert (fpr[0], tpr[0]) == (0, 0) and np.isinf(thresholds[0])
    assert (fpr[-1], tpr[-1]) == (1, 1) and thresholds[-1] == 1.0
    assert np.all(np.diff(fpr) >= 0) and np.all(np.diff(tpr) >= 0)


def test_roc_needs_both_classes():
    with pytest.raises(ValueError):
        roc_curve([1, 2], [True, True])


def test_auc_perfect_chance_and_ties():
    assert auc([1, 2, 10, 20], [False, False, True, True]) == 1.0
    assert auc([1, 1], [False, True]) == 0.5
    # 8 of the 9 moving/still pairs are ordered correctly (8 < 12 is the exception)
    assert auc(SCORES, MOVING) == pytest.approx(8 / 9)


def test_best_threshold_sits_in_the_gap_between_the_classes():
    assert best_threshold([1, 2, 10, 20], [False, False, True, True]) == 6.0


def test_best_threshold_maximises_sensitivity_plus_specificity():
    threshold = best_threshold(SCORES, MOVING)
    result = confusion(SCORES, MOVING, threshold)
    j = result["sensitivity"] + result["specificity"]
    for candidate in np.linspace(0, 35, 200):
        other = confusion(SCORES, MOVING, candidate)
        assert other["sensitivity"] + other["specificity"] <= j + 1e-9


def test_confusion_counts():
    result = confusion(SCORES, MOVING, 10)
    assert result["moving_called_moving"] == 2 and result["moving_called_still"] == 1
    assert result["still_called_still"] == 2 and result["still_called_moving"] == 1
    assert result["n_moving"] == 3 and result["n_still"] == 3 and result["n_wrong"] == 2
    assert result["accuracy"] == pytest.approx(4 / 6)
    assert result["sensitivity"] == pytest.approx(2 / 3)


def test_outcome_calls_moving_at_or_above_the_threshold():
    assert outcome(True, 10, 10) == "moving_called_moving"
    assert outcome(False, 10, 10) == "still_called_moving"
    assert outcome(False, 9.9, 10) == "still_called_still"


def test_ground_truth_matched_by_nearest_position():
    mites = [{"id": "0", "x": 100, "y": 100}, {"id": "1", "x": 108, "y": 100}, {"id": "2", "x": 500, "y": 500}]
    saved = [
        {"x": 107, "y": 101, "truth": ["moving", "still"]},   # closest to mite 1, not mite 0
        {"x": 99, "y": 100, "truth": ["moving", None]},
        {"x": 900, "y": 900, "truth": ["moving", "moving"]},  # no mite near it any more
    ]
    assert match_ground_truth(mites, saved, n_recordings=2) == {"0": ["moving", None], "1": ["moving", "still"]}


def test_ground_truth_ignores_unknown_states():
    saved = [{"x": 0, "y": 0, "truth": ["maybe", "maybe"]}]
    assert match_ground_truth([{"id": "0", "x": 0, "y": 0}], saved, n_recordings=2) == {}


def test_ground_truth_fits_the_number_of_recordings():
    # a single status applies to every recording; a list is cut or padded
    assert per_recording("still", 3) == ["still", "still", "still"]
    assert per_recording(["moving"], 3) == ["moving", None, None]
    assert per_recording(["moving", "still", "still", "still"], 2) == ["moving", "still"]


def test_older_alive_dead_labels_read_as_moving_still():
    assert per_recording(["alive", "dead", None], 3) == ["moving", "still", None]


def test_rejection_is_any_not_a_mite_mark():
    assert is_rejected(["not_a_mite", "not_a_mite"])
    assert is_rejected("not_a_mite")
    assert not is_rejected(["moving", None])


def test_moving_over_time_compares_labels_and_detector_on_the_same_rows():
    rows = [
        {"recording": 0, "movement": "moving", "score": 20},
        {"recording": 0, "movement": "moving", "score": 5},   # called still at threshold 10
        {"recording": 1, "movement": "still", "score": 5},
    ]
    result = moving_over_time(rows, 3, {"current": 10})
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


def test_save_movement_score_writes_metric_params_and_threshold(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  motion_threshold: 15.6   # tuned\n  metric: "variability"  # which score\nother: 1\n')
    saved = app_config.save_movement_score("topN_variability", {"n": 20}, 3.21, path)
    assert saved == {"metric": "topN_variability", "params": {"n": 20}, "threshold": 3.21}
    text = path.read_text()
    assert 'metric: "topN_variability"  # which score' in text
    assert "motion_threshold: 3.21   # tuned" in text
    assert yaml.safe_load(text)["mite"]["metric_params"] == {"topN_variability": {"n": 20}}

    # saving another metric keeps the parameters of the first
    app_config.save_movement_score("optical_flow", {"window": 3, "n": 10}, 0.5, path)
    saved = yaml.safe_load(path.read_text())
    assert saved["mite"]["metric"] == "optical_flow"
    assert saved["mite"]["metric_params"] == {"topN_variability": {"n": 20}, "optical_flow": {"window": 3, "n": 10}}
    assert saved["other"] == 1
