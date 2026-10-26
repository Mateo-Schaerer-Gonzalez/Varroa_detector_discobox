"""The calls too close to the threshold to trust are asked to be checked by eye
where a mite's time of death depends on them, and the answers are kept."""

import json

import pandas as pd
import pytest
import yaml

import pipeline
from pipeline import run_results
import reference
from classes import app_config
from classes.app_config import MiteConfig, get_default_config
from classes.results.call_corrections import CallCorrections
from classes.results.movement_stats import MovementReport
from classes.results.review_band import ReviewBand
from classes.plate.zones import MITE_SCORE_COLUMNS

THRESHOLD = 3.5
BAND = ReviewBand(2.5, 4.5)
# as pipeline has them, before conftest.py keeps the other tests' runs from them
REVIEW = run_results.review_calls


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
    assert review == {"low": 2.5, "high": 4.5, "to_check": {"0": [3, 1], "2": [2]}, "n_recordings": 3, "n_mites": 2,
                      "n_asked": 2, "n_done": 0}
    # a correction counts as checked, like a call kept as checked
    answered = BAND.describe(data, {"corrections": {"0": [1]}, "checked": {"2": [2]}})
    assert answered["to_check"] == {"0": [3]}
    assert (answered["n_asked"], answered["n_done"]) == (2, 1)  # mite 2 is done, mite 0 not yet
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

    # without a band the one in use moves with the threshold, scaled: as far below it against above
    assert app_config.save_movement_score("variability", {}, 8.4, path)["review_band"] == [6.2, 8.5]
    assert yaml.safe_load(path.read_text())["mite"]["metric_review_bands"] == {"variability": [6.2, 8.5]}


def test_saving_the_threshold_alone_moves_its_band_with_it(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('mite:\n  radius: 8\n  metric: "variability"\n  metric_thresholds: {variability: 4.0}\n'
                    "  metric_review_bands: {variability: [3.0, 5.0], optical_flow: [0.4, 0.6]}\n")
    assert app_config.save_motion_threshold(2.0, path) == 2.0
    mite = yaml.safe_load(path.read_text())["mite"]
    assert mite["metric_thresholds"] == {"variability": 2.0}
    assert mite["metric_review_bands"] == {"variability": [1.5, 2.5], "optical_flow": [0.4, 0.6]}

    # a band the threshold had left already is not in use, and is not moved
    path.write_text('mite:\n  radius: 8\n  metric: "variability"\n  metric_thresholds: {variability: 4.0}\n'
                    "  metric_review_bands: {variability: [5.0, 6.0]}\n")
    app_config.save_motion_threshold(2.0, path)
    assert yaml.safe_load(path.read_text())["mite"]["metric_review_bands"] == {"variability": [5.0, 6.0]}
    # nor is there one to move without a band
    path.write_text('mite:\n  radius: 8\n  metric: "variability"\n  metric_thresholds: {variability: 4.0}\n')
    app_config.save_motion_threshold(2.0, path)
    assert "metric_review_bands" not in path.read_text()


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
    assert config({"variability": [4.0, 5.0]}).review_band_for("variability") is None  # a threshold saved since
    assert config({}).review_band_for("variability") is None
    assert config({"variability": "wide"}).review_band_for("variability") is None


# --- on the results of a run

@pytest.mark.slow
def test_the_results_ask_for_the_close_calls_until_they_are_answered(tmp_path, monkeypatch):
    session = reference.make_small_session(tmp_path / "small_session")
    out = tmp_path / "out"
    # the calls to check as the app makes them, which the other tests' runs are kept from (conftest.py)
    monkeypatch.setattr(run_results, "review_calls", REVIEW)
    monkeypatch.setattr(get_default_config().mite, "metric_review_bands", {})
    pipeline.save_review_mites(session, 0)
    results = pipeline.run_analysis(session, out)
    assert "review" not in results

    # more mites to check than there are: the band as wide as it goes, from 0 to twice the threshold
    pipeline.save_review_mites(session, 1000)
    results = pipeline.review_again(out)
    review = results["review"]
    assert 0 < review["n_mites"] == review["n_asked"] <= len(results["mites"])
    assert 0 <= review["low"] < results["threshold"] < review["high"] <= 2 * results["threshold"] + 1e-6
    mite = next(m for m in results["mites"] if m["id"] in review["to_check"])
    latest = review["to_check"][mite["id"]][0]

    # the latest close call is answered with the detector's own call: no correction, and asked no more
    answered = pipeline.correct_call(out, mite["id"], latest, "moving" if mite["moving"][latest] else "still", checked=True)
    assert "corrections" not in answered and answered["checked"] == {mite["id"]: [latest]}
    assert answered["mites"] == results["mites"]
    left = answered["review"]["to_check"].get(mite["id"], [])
    assert latest not in left and (left == [] or not mite["moving"][latest])
    assert (answered["review"]["low"], answered["review"]["high"]) == (review["low"], review["high"])  # the band stays

    again = pipeline.run_analysis(session, out)  # another run keeps the answer
    assert again["review"]["to_check"].get(mite["id"], []) == left


# --- the band fitted to the mites to check

def test_the_band_is_the_narrowest_asking_about_the_mites_to_check():
    # each mite's last recording is its only close call, ever further from the threshold
    data = mite_data({"0": [9.0, 3.4], "1": [9.0, 3.0], "2": [9.0, 2.0], "3": [9.0, 1.0]})
    for n_mites, asked in ((1, {"0"}), (2, {"0", "1"}), (3, {"0", "1", "2"})):
        band = ReviewBand.fitted(data, THRESHOLD, n_mites)
        review = band.describe(data)
        assert set(review["to_check"]) == asked and review["n_asked"] == n_mites
        assert THRESHOLD - band.low == pytest.approx(band.high - THRESHOLD)  # as far either way without a shape
    assert ReviewBand.fitted(data, THRESHOLD, 0) is None
    # more mites than there are: every mite, and no wider than that takes
    band = ReviewBand.fitted(data, THRESHOLD, 50)
    assert band.describe(data)["n_asked"] == 4 and 2.5 <= THRESHOLD - band.low < 3.0
    # but never further from the threshold than the threshold itself
    far = mite_data({"0": [9.0, 3.4], "1": [9.0, 7.5]})
    assert ReviewBand.fitted(far, THRESHOLD, 2).describe(far)["to_check"] == {"0": [1]}


def test_the_band_keeps_the_shape_of_the_one_in_config():
    # a band reaching only above the threshold leaves the still side to the detector
    data = mite_data({"0": [3.4, 1.0], "1": [3.6, 1.0], "2": [9.0, 4.0]})
    band = ReviewBand.fitted(data, THRESHOLD, 1, shape=(THRESHOLD, 5.0))
    assert band.low == THRESHOLD and 3.6 < band.high < 4.0
    assert band.describe(data)["to_check"] == {"1": [0]}  # not mite 0, as close below
    band = ReviewBand.fitted(data, THRESHOLD, 2, shape=(THRESHOLD, 5.0))
    assert band.describe(data)["to_check"] == {"1": [0], "2": [1]}
    # and one three times as wide below as above keeps that
    band = ReviewBand.fitted(data, THRESHOLD, 2, shape=(0.5, 4.5))
    assert THRESHOLD - band.low == pytest.approx(3 * (band.high - THRESHOLD))


def test_a_mite_answered_counts_against_the_mites_to_check():
    data = mite_data({"0": [9.0, 3.4], "1": [9.0, 3.0]})
    band = ReviewBand.fitted(data, THRESHOLD, 1)
    review = band.describe(data, {"checked": {"0": [1]}})
    assert review["to_check"] == {} and (review["n_asked"], review["n_done"]) == (1, 1)
    assert set(band.describe(data)["to_check"]) == {"0"}  # mite 1 is not asked for in its place


def test_a_run_has_its_own_number_of_mites_to_check(tmp_path):
    default = get_default_config().mite.review_mites
    assert pipeline.review_mites(tmp_path) == pipeline.review_mites() == default
    (tmp_path / pipeline.SETTINGS_FILENAME).write_text("fps=10\n", encoding="utf-8")
    assert pipeline.save_review_mites(tmp_path, 7) == 7 and pipeline.review_mites(tmp_path) == 7
    for wrong in (-1, 2.5, "many"):
        with pytest.raises(ValueError):
            pipeline.save_review_mites(tmp_path, wrong)
    assert pipeline.save_review_mites(tmp_path, None) == default
    assert (tmp_path / pipeline.SETTINGS_FILENAME).read_text(encoding="utf-8") == "fps=10\n"


