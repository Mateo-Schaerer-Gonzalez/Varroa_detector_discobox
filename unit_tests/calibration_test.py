import yaml
import numpy as np
import pytest

from classes import app_config
from classes.calibration import (
    apply_changes,
    auc,
    best_threshold,
    calls_confusion,
    confusion,
    has_both_classes,
    is_rejected,
    match_ground_truth,
    mite_survival,
    moving_median,
    moving_over_time,
    outcome,
    per_recording,
    roc_curve,
    survival_curves,
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


def test_moving_median_centred_and_trailing_shorten_at_the_ends():
    scores = [1, 9, 2, 8, 3]
    assert moving_median(scores, 3).tolist() == [5, 2, 8, 3, 5.5]
    assert moving_median(scores, 3, centred=False).tolist() == [1, 5, 2, 8, 3]
    assert moving_median(scores, 1).tolist() == scores


def test_confusion_counts():
    result = confusion(SCORES, MOVING, 10)
    assert result["moving_called_moving"] == 2 and result["moving_called_still"] == 1
    assert result["still_called_still"] == 2 and result["still_called_moving"] == 1
    assert result["n_moving"] == 3 and result["n_still"] == 3 and result["n_wrong"] == 2
    assert result["accuracy"] == pytest.approx(4 / 6)
    assert result["sensitivity"] == pytest.approx(2 / 3)


def test_confusion_gives_precision_recall_and_f1():
    result = confusion(SCORES, MOVING, 10)  # 2 moving called moving, 1 still called moving, 1 moving called still
    assert result["precision"] == pytest.approx(2 / 3)
    assert result["sensitivity"] == pytest.approx(2 / 3)  # the recall
    assert result["f1"] == pytest.approx(2 / 3)
    # calls given as such, e.g. the benchmark's, count the same way
    assert calls_confusion(np.array(SCORES) >= 10, MOVING) == {k: v for k, v in result.items() if k != "threshold"}


def test_precision_of_no_call_moving_is_unknown():
    result = calls_confusion([False, False], [True, False])
    assert result["precision"] is None
    assert result["sensitivity"] == 0 and result["f1"] == 0


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


def test_changes_leave_the_other_recordings_as_saved():
    # e.g. recording 3 labelled in another window since this page loaded
    assert apply_changes(["still", "still", "moving"], {0: "moving"}, 3) == ["moving", "still", "moving"]
    assert apply_changes(None, {"1": "still"}, 3) == [None, "still", None]
    assert apply_changes(["still", "still"], {1: None}, 2) == ["still", None]


def test_not_a_mite_in_one_recording_marks_every_recording():
    assert apply_changes(["moving", "still"], {1: "not_a_mite"}, 2) == ["not_a_mite", "not_a_mite"]


def test_a_status_for_a_mite_marked_not_a_mite_takes_the_mark_back():
    marked = ["not_a_mite", "not_a_mite", "not_a_mite"]
    assert apply_changes(marked, {1: "moving"}, 3) == [None, "moving", None]
    # the page sends every recording's status when it brings the labels back
    assert apply_changes(marked, {0: "still", 1: "moving", 2: "still"}, 3) == ["still", "moving", "still"]


def test_a_list_of_changes_gives_every_recording():
    assert apply_changes(["moving", "moving"], ["still"], 2) == ["still", None]


def test_changes_outside_the_recordings_are_ignored():
    assert apply_changes(["moving"], {5: "still", -1: "still"}, 1) == ["moving"]
    assert apply_changes(["not_a_mite"], {}, 1) == ["not_a_mite"]


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


def survival_rows(mite_id, labels, scores):
    return [{"dataset": "d", "mite_id": mite_id, "recording": recording, "movement": label, "score": score}
            for recording, (label, score) in enumerate(zip(labels, scores)) if label is not None]


def test_a_mite_dies_at_the_first_labelled_recording_after_its_last_movement():
    times = [0, 10, 20, 30]
    by_label = lambda row: row["movement"] == "moving"
    assert mite_survival(survival_rows("a", ["moving", "still", "still", "still"], [0] * 4), times, by_label) == (10, True)
    # The recording after its last movement unlabelled: dead at the next labelled one.
    assert mite_survival(survival_rows("a", ["moving", None, "still", None], [0] * 4), times, by_label) == (20, True)
    # Moving in its last labelled recording: censored there.
    assert mite_survival(survival_rows("a", ["still", "moving", None, None], [0] * 4), times, by_label) == (10, False)
    assert mite_survival(survival_rows("a", ["still"] * 4, [0] * 4), times, by_label) is None


def test_survival_curves_by_the_labels_and_the_detector_leave_out_mites_never_moving():
    times = [0, 10, 20]
    rows = (survival_rows("a", ["moving", "still", "still"], [20, 5, 5])      # dies at 10 either way
            + survival_rows("b", ["moving", "moving", "moving"], [20, 20, 5])  # alive by labels, dies at 20 as called
            + survival_rows("c", ["still", "still", "still"], [20, 5, 5]))     # never moving by labels; dies at 10 as called
    curves = survival_curves(rows, times, {"current": 10})
    assert curves["truth"]["alive"] == [100.0, 50.0, 50.0]
    assert (curves["truth"]["n_mites"], curves["truth"]["n_left_out"], curves["truth"]["n_dead"]) == (2, 1, 1)
    assert curves["current"]["alive"] == [100.0, pytest.approx(100 / 3), 0.0]
    assert (curves["current"]["n_mites"], curves["current"]["n_left_out"], curves["current"]["n_dead"]) == (3, 0, 3)


def test_survival_curves_of_calls_made_by_another_method():
    times = [0, 10, 20]
    rows = (survival_rows("a", ["moving", "still", "still"], [20, 5, 5])
            + survival_rows("b", ["moving", "moving", "moving"], [20, 20, 5]))
    for row, call in zip(rows, ["moving", "moving", "still", "still", "still", "still"]):
        row["benchmark_call"] = call  # a dies at 20, b is never called moving
    curves = survival_curves(rows, times, {"current": 10}, {"benchmark": "benchmark_call"})
    assert set(curves) == {"truth", "current", "benchmark"}
    assert curves["benchmark"]["alive"] == [100.0, 100.0, 0.0]
    assert (curves["benchmark"]["n_mites"], curves["benchmark"]["n_left_out"]) == (1, 1)


def test_has_both_classes():
    assert has_both_classes([True, False])
    assert not has_both_classes([True, True])


def test_save_motion_threshold_keeps_the_rest_of_the_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  metric: "variability"\n'
                    "  metric_thresholds: {variability: 15.654, optical_flow: 0.5}   # tuned by hand\n")

    assert app_config.save_motion_threshold(9.12345, path) == 9.123

    text = path.read_text()
    assert "metric_thresholds: {variability: 9.123, optical_flow: 0.5}   # tuned by hand" in text
    assert "radius: 8" in text and 'metric: "variability"' in text


def test_the_threshold_follows_the_metric():
    mite = app_config.MiteConfig(radius=8, metric="optical_flow", moving_color=(0, 0, 0), still_color=(0, 0, 0),
                                 metric_thresholds={"variability": 15.6, "optical_flow": 0.5})
    assert mite.motion_threshold == 0.5
    assert mite.threshold_for("variability") == 15.6
    with pytest.raises(ValueError):
        mite.threshold_for("max_diff")


def test_save_motion_threshold_refuses_a_file_without_one(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mite:\n  radius: 8\n")
    with pytest.raises(ValueError):
        app_config.save_motion_threshold(3, path)


def test_save_movement_score_writes_metric_params_and_threshold(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  metric: "variability"  # which score\n'
                    '  metric_thresholds: {variability: 15.6}   # tuned\nother: 1\n')
    saved = app_config.save_movement_score("topN_variability", {"n": 20}, 3.21, path)
    assert saved == {"metric": "topN_variability", "params": {"n": 20}, "threshold": 3.21, "window": 0, "centred": True,
                     "scale": 0.0}
    text = path.read_text()
    assert 'metric: "topN_variability"  # which score' in text
    assert "metric_thresholds: {variability: 15.6, topN_variability: 3.21}   # tuned" in text
    assert yaml.safe_load(text)["mite"]["metric_params"] == {"topN_variability": {"n": 20}}

    # saving another metric keeps the parameters of the first
    app_config.save_movement_score("optical_flow", {"window": 3, "n": 10}, 0.5, path)
    saved = yaml.safe_load(path.read_text())
    assert saved["mite"]["metric"] == "optical_flow"
    assert saved["mite"]["metric_params"] == {"topN_variability": {"n": 20}, "optical_flow": {"window": 3, "n": 10}}
    assert saved["mite"]["metric_thresholds"] == {"variability": 15.6, "topN_variability": 3.21, "optical_flow": 0.5}
    assert saved["other"] == 1


def test_save_movement_score_writes_the_window_of_the_mites_own_threshold(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  metric: "variability"\n')

    def mite():
        return app_config.MiteConfig(moving_color=(0, 255, 0), still_color=(0, 0, 255), **yaml.safe_load(path.read_text())["mite"])

    saved = app_config.save_movement_score("variability", {}, 0.4, path, window=5, centred=False)
    assert (saved["window"], saved["centred"]) == (5, False)
    assert mite().window_for("variability") == (5, False)
    assert mite().motion_threshold == 0.4
    assert mite().window_for("mean_diff") == (0, True)  # a metric saved before there were windows
    assert mite().scale_for("variability") == 0

    # the threshold rising with the mite's noise, by so many MADs
    saved = app_config.save_movement_score("variability", {}, 0.4, path, window=5, scale=2)
    assert saved["scale"] == 2
    assert mite().scale_for("variability") == 2
    assert mite().scale_for("mean_diff") == 0

    # back to one threshold for every mite
    app_config.save_movement_score("variability", {}, 3.0, path)
    assert mite().window_for("variability") == (0, True)
    assert mite().scale_for("variability") == 0
    assert path.read_text().count("metric_windows") == 1


def test_save_movement_score_sets_plate_stabilization(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  metric: "variability"\n')
    saved = app_config.save_movement_score("variability", {}, 3.0, path, stabilize_plate=True)
    assert saved["stabilize_plate"] is True
    assert yaml.safe_load(path.read_text())["mite"]["stabilize_plate"] is True

    app_config.save_movement_score("variability", {}, 3.0, path, stabilize_plate=False)
    assert yaml.safe_load(path.read_text())["mite"]["stabilize_plate"] is False
    assert path.read_text().count("stabilize_plate") == 1

    # left as it is when not given
    saved = app_config.save_movement_score("variability", {}, 3.0, path)
    assert "stabilize_plate" not in saved
    assert yaml.safe_load(path.read_text())["mite"]["stabilize_plate"] is False
