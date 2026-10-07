"""The calls too close to the threshold to trust are asked to be checked by eye
where a mite's time of death depends on them, and the answers are kept."""

import json

import pandas as pd
import pytest
import yaml

import pipeline
import reference
from classes import app_config
from classes.app_config import MiteConfig, get_default_config
from classes.call_corrections import CallCorrections
from classes.movement_stats import MovementReport
from classes.review_band import ReviewBand
from classes.zones import MITE_SCORE_COLUMNS

THRESHOLD = 3.5
BAND = ReviewBand(2.5, 4.5)


def calls(scores):
    return [score >= THRESHOLD for score in scores]


def mite_data(scores):
    """One mite per entry of `scores` (mite id -> one score per recording)."""
    rows = [{"mite_ID": mite_id, "time": 10.0 * at, "motion_score": value, "moving": value >= THRESHOLD, "zone_id": 1,
             "group": "a", "zone_type": "mite", "x": 50.0 + 40 * index, "y": 60.0}
            for index, (mite_id, values) in enumerate(scores.items()) for at, value in enumerate(values)]
    return pd.DataFrame(rows, columns=MITE_SCORE_COLUMNS)


# --- which calls to check

def test_the_close_calls_after_the_last_clear_movement_are_to_check_the_latest_first():
    scores = [3.0, 9.0, 3.0, 1.0, 4.0, 1.0, 2.6]
    assert BAND.to_check(scores, calls(scores)) == [6, 4, 2]  # not the 3.0 before the clear movement


def test_clear_scores_need_no_check():
    scores = [9.0, 1.0, 1.0, 5.0, 1.0]
    assert BAND.to_check(scores, calls(scores)) == []


def test_a_close_call_seen_to_be_a_movement_settles_the_ones_before_it():
    scores = [9.0, 3.0, 1.0, 4.0, 1.0, 3.0]
    moving = calls(scores)
    assert BAND.to_check(scores, moving) == [5, 3, 1]
    # the last one is looked at and is still: the others are left
    assert BAND.to_check(scores, moving, checked=[False] * 5 + [True]) == [3, 1]
    # the one before is a movement after all: nothing before it matters any more
    assert BAND.to_check(scores, moving, checked=[False, False, False, True, False, True]) == []
    # ... unless it was set still by hand: then the first one is still open
    moving[3] = False
    assert BAND.to_check(scores, moving, checked=[False, False, False, True, False, True]) == [1]


def test_a_recording_in_which_the_mite_is_gone_is_not_asked_for():
    scores = [9.0, 3.0, 3.0]
    assert BAND.to_check(scores, calls(scores), censored=[False, False, True]) == [1]


def test_the_pages_are_told_what_is_left_to_check():
    data = mite_data({"0": [9.0, 3.0, 1.0, 4.0], "1": [9.0, 1.0, 1.0, 1.0], "2": [1.0, 1.0, 2.6, 1.0]})
    review = BAND.describe(data)
    assert review == {"low": 2.5, "high": 4.5, "to_check": {"0": [3, 1], "2": [2]}, "n_recordings": 3, "n_mites": 2}
    # a correction counts as checked, like a call kept as checked
    assert BAND.describe(data, {"corrections": {"0": [1]}, "checked": {"2": [2]}})["to_check"] == {"0": [3]}
    # mite 0's last call, moving, set by hand: a settled movement, so the one before it matters no more
    assert BAND.describe(data, {"checked": {"0": [3]}})["to_check"] == {"2": [2]}

    results = {"times": [0, 10, 20, 30], "zones": [{"id": 1, "label": "a", "n_mites": 3}], "review": review,
               "corrections": {"1": [0]}, "checked": {"1": [2]},
               "mites": [{"id": mite_id, "zone_id": 1, "scores": list(rows.sort_values("time")["motion_score"]),
                          "moving": list(rows.sort_values("time")["moving"])} for mite_id, rows in data.groupby("mite_ID")]}
    first, second, _third = MovementReport(results).describe()["mites"]
    assert first["to_check"] == [3, 1] and first["checked"] == [False] * 4
    assert second["to_check"] == [] and second["checked"] == [True, False, True, False]


# --- the answers are kept

def test_a_call_kept_as_checked_stays_also_when_it_is_the_detectors(tmp_path):
    corrections = CallCorrections(tmp_path)
    corrections.change(50.0, 60.0, 1, detected=False, state="still", checked=True)
    data = mite_data({"0": [9.0, 3.0, 1.0]})
    applied, changes = corrections.apply(data)
    assert changes == {"checked": {"0": [1]}} and "corrected" not in applied
    assert list(applied["moving"]) == list(data["moving"])
    assert BAND.describe(applied, changes)["to_check"] == {}
    assert CallCorrections(tmp_path).entries()[0]["checked"] == [1]  # read back from the file
    # "gone" is no call: nothing to keep as checked
    corrections.change(50.0, 60.0, 2, detected=False, state="gone", checked=True)
    assert CallCorrections(tmp_path).entries()[0]["checked"] == [1]


def test_a_file_saved_before_calls_were_checked_reads_as_none_checked(tmp_path):
    (tmp_path / CallCorrections.FILENAME).write_text(
        json.dumps({"recording": [{"x": 50.0, "y": 60.0, "moving": {"1": True}, "gone": [], "gone_from": None}]}),
        encoding="utf-8")
    assert CallCorrections(tmp_path).entries()[0]["checked"] == []


# --- the band in config.yaml

def test_the_band_is_saved_per_metric_and_taken_out_again(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  metric: "variability"  # which score\n'
                    "  metric_thresholds: {variability: 3.5, optical_flow: 0.5}\n"
                    "  metric_review_bands: {optical_flow: [0.4, 0.6]}   # by eye\n")
    assert app_config.save_review_band(2.50049, 4.5, path) == [2.5, 4.5]
    text = path.read_text()
    assert "metric_review_bands: {optical_flow: [0.4, 0.6], variability: [2.5, 4.5]}   # by eye" in text
    assert 'metric: "variability"  # which score' in text

    assert app_config.save_review_band(None, None, path) is None
    assert yaml.safe_load(path.read_text())["mite"]["metric_review_bands"] == {"optical_flow": [0.4, 0.6]}


def test_the_band_is_saved_with_the_threshold_from_the_calibration_report(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  metric: "variability"\n  metric_thresholds: {variability: 3.5}\n'
                    "  metric_review_bands: {variability: [2.5, 4.0]}\n")
    saved = app_config.save_movement_score("variability", {}, 4.2, path, review_band=[3.1, 4.25])
    assert saved["threshold"] == 4.2 and saved["review_band"] == [3.1, 4.25]
    mite = yaml.safe_load(path.read_text())["mite"]
    assert mite["metric_thresholds"] == {"variability": 4.2} and mite["metric_review_bands"] == {"variability": [3.1, 4.25]}

    # a band the new threshold is not in is refused, and nothing of it is saved
    for band in ([2.0, 3.0], [5.0, 4.0], [3.0]):
        with pytest.raises(ValueError):
            app_config.save_movement_score("variability", {}, 3.6, path, review_band=band)
    assert yaml.safe_load(path.read_text())["mite"] == mite

    # without a band the one saved stays, used again once the threshold is back in it
    assert "review_band" not in app_config.save_movement_score("variability", {}, 9.0, path)
    assert yaml.safe_load(path.read_text())["mite"]["metric_review_bands"] == {"variability": [3.1, 4.25]}


def test_a_band_must_hold_the_threshold(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  metric: "variability"\n  metric_thresholds: {variability: 3.5}\n')
    for low, high in ((4.0, 5.0), (1.0, 3.0), (4.0, 3.0)):
        with pytest.raises(ValueError):
            app_config.save_review_band(low, high, path)
    assert "metric_review_bands" not in path.read_text()
    assert app_config.save_review_band(3.0, 4.0, path) == [3.0, 4.0]  # a file without the line gets it


def test_a_band_the_threshold_left_is_no_band():
    def config(bands):
        return MiteConfig(radius=8, metric="variability", moving_color=(0, 255, 0), still_color=(0, 0, 255),
                          metric_thresholds={"variability": 3.5}, metric_review_bands=bands)

    assert config({"variability": [2.5, 4.5]}).review_band_for("variability") == (2.5, 4.5)
    assert ReviewBand.of(config({"variability": [2.5, 4.5]})).high == 4.5
    assert config({"variability": [4.0, 5.0]}).review_band_for("variability") is None  # a threshold saved since
    assert config({}).review_band_for("variability") is None and ReviewBand.of(config({})) is None
    assert config({"variability": "wide"}).review_band_for("variability") is None


# --- on the results of a run

@pytest.mark.slow
def test_the_results_ask_for_the_close_calls_until_they_are_answered(tmp_path, monkeypatch):
    session = reference.make_small_session(tmp_path / "small_session")
    out, library = tmp_path / "out", tmp_path / "library"
    # the band as config.yaml has it, which the other tests' runs are kept from (conftest.py)
    monkeypatch.setattr(pipeline, "_review_band", lambda metric: ReviewBand.of(get_default_config().mite, metric))
    mite_config = get_default_config().mite
    monkeypatch.setattr(mite_config, "metric_review_bands", {})
    results = pipeline.run_analysis(session, out, library_dir=library)
    assert "review" not in results

    # a band from just below the threshold up to above every score: every mite's last recordings are close
    threshold = results["threshold"]
    highest = max(score for mite in results["mites"] for score in mite["scores"])
    lowest = min(score for mite in results["mites"] for score in mite["scores"])
    monkeypatch.setattr(mite_config, "metric_review_bands", {mite_config.metric: [min(lowest, threshold), highest + 1]})
    results = pipeline.review_again(out)
    review = results["review"]
    n_recordings = results["n_recordings"]
    assert review["n_mites"] == len(results["mites"])
    mite = results["mites"][0]
    assert review["to_check"][mite["id"]] == list(range(n_recordings))[::-1]

    # the last recording is answered with the detector's own call: no correction, and asked no more
    last = n_recordings - 1
    answered = pipeline.correct_call(out, mite["id"], last, "moving" if mite["moving"][last] else "still", checked=True)
    assert "corrections" not in answered and answered["checked"] == {mite["id"]: [last]}
    assert answered["mites"] == results["mites"]
    left = answered["review"]["to_check"].get(mite["id"], [])
    assert left == ([] if mite["moving"][last] else list(range(last))[::-1])

    again = pipeline.run_analysis(session, out, library_dir=library)  # another run keeps the answer
    assert again["review"]["to_check"].get(mite["id"], []) == left
