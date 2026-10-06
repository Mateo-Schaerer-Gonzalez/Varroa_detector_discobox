"""The scores of a finished run are put on one scale for every mite, keeping the
threshold's scale, and the detector's calls follow the normalised scores."""

import json

import pandas as pd
import pytest

import pipeline
import reference
from classes.app_config import get_default_config
from classes.score_normalizer import ScoreNormalizer
from classes.zones import MITE_SCORE_COLUMNS

TIMES = [0.0, 5.0, 10.0, 15.0, 20.0]
THRESHOLD = 2.6


def mite_data(scores, brightness=None):
    """One mite per entry of `scores` (mite id -> one score per recording)."""
    rows = [{"mite_ID": mite_id, "time": time, "motion_score": value, "moving": value >= THRESHOLD, "zone_id": 1,
             "group": "a", "zone_type": "mite", "x": 50.0 + 40 * index, "y": 60.0,
             "brightness": None if brightness is None else brightness[mite_id][at]}
            for index, (mite_id, values) in enumerate(scores.items())
            for at, (time, value) in enumerate(zip(TIMES, values))]
    return pd.DataFrame(rows, columns=MITE_SCORE_COLUMNS)


def of(data, mite_id, column="motion_score"):
    return list(data[data["mite_ID"] == mite_id].sort_values("time")[column])


def test_nothing_switched_on_leaves_the_table_as_it_is():
    data = mite_data({"0": [2.0, 2.1, 5.0, 2.0, 2.2]})
    assert ScoreNormalizer().apply(data, THRESHOLD) is data


def test_the_floor_of_every_mite_is_moved_to_the_common_one():
    # mite 1 is still throughout, on a floor that straddles the threshold
    data = mite_data({"0": [2.0, 2.1, 5.0, 2.0, 2.2], "1": [2.5, 2.7, 2.6, 2.5, 2.8], "2": [2.2, 2.3, 2.2, 6.0, 2.1]})
    assert of(data, "1", "moving") == [False, True, True, False, True]

    normalised = ScoreNormalizer(floor=True).apply(data, THRESHOLD)

    # floors 2.1, 2.6 and 2.2: all moved to 2.2
    assert of(normalised, "1") == pytest.approx([2.1, 2.3, 2.2, 2.1, 2.4])
    assert of(normalised, "1", "moving") == [False] * 5
    assert of(normalised, "0") == pytest.approx([2.1, 2.2, 5.1, 2.1, 2.3])
    assert of(normalised, "0", "moving") == [False, False, True, False, False]
    assert of(normalised, "2") == of(data, "2")  # the mite of the common floor
    assert of(normalised, "1", "raw_score") == of(data, "1")


def test_scores_are_scaled_to_the_typical_brightness():
    data = mite_data({"0": [2.0] * 5, "1": [3.0] * 5, "2": [4.0] * 5},
                     brightness={"0": [80.0] * 5, "1": [120.0] * 5, "2": [100.0] * 5})
    normalised = ScoreNormalizer(brightness=True).apply(data, THRESHOLD)
    assert of(normalised, "0") == pytest.approx([2.5] * 5)   # 2.0 * 100 / 80
    assert of(normalised, "1") == pytest.approx([2.5] * 5)   # 3.0 * 100 / 120
    assert of(normalised, "2") == pytest.approx([4.0] * 5)
    assert of(normalised, "1", "moving") == [False] * 5 and of(normalised, "2", "moving") == [True] * 5


def test_a_score_without_brightness_is_not_scaled():
    data = mite_data({"0": [2.0] * 5, "1": [3.0] * 5})
    assert of(ScoreNormalizer(brightness=True).apply(data, THRESHOLD), "1") == [3.0] * 5


def test_the_users_calls_and_the_recordings_a_mite_is_gone_in_are_left_alone():
    data = mite_data({"0": [2.5, 2.7, 2.6, 0.2, 0.2], "1": [2.0, 2.1, 2.2, 2.0, 2.1]})
    data["corrected"] = [True] + [False] * 9
    data["censored"] = [False, False, False, True, True] + [False] * 5
    data.loc[0, "moving"] = True  # the user's
    normalised = ScoreNormalizer(floor=True).apply(data, THRESHOLD)
    # mite 0's floor is 2.6, of the recordings it is there in; the common one 2.35
    assert of(normalised, "0")[:3] == pytest.approx([2.25, 2.45, 2.35])
    assert of(normalised, "0", "moving") == [True, False, False, False, False]


def test_a_calibrations_scores_go_through_the_same():
    scores = {"0": [2.0, 2.1, 5.0, 2.0, 2.2], "1": [2.5, 2.7, 2.6, 2.5, 2.8], "2": [2.2, 2.3, 2.2, 6.0, 2.1]}
    normalised = ScoreNormalizer(floor=True).by_mite(scores)
    assert normalised["1"] == pytest.approx([2.1, 2.3, 2.2, 2.1, 2.4]) and normalised["2"] == pytest.approx(scores["2"])
    table = ScoreNormalizer(floor=True).apply(mite_data(scores), THRESHOLD)
    assert all(normalised[mite_id] == pytest.approx(of(table, mite_id)) for mite_id in scores)

    brightness = {"0": [80.0] * 5, "1": [120.0] * 5, "2": [100.0] * 5}
    scaled = ScoreNormalizer(brightness=True).by_mite({"0": [2.0] * 5, "1": [3.0] * 5, "2": [4.0] * 5}, brightness)
    assert scaled["0"] == pytest.approx([2.5] * 5) and scaled["1"] == pytest.approx([2.5] * 5)
    assert ScoreNormalizer().by_mite({}) == {}


@pytest.mark.slow
def test_the_analysis_of_a_folder_normalises_as_config_yaml_says(tmp_path, monkeypatch):
    session = reference.make_small_session(tmp_path / "small_session")
    out, library = tmp_path / "out", tmp_path / "library"
    mite_config = get_default_config().mite
    monkeypatch.setattr(mite_config, "normalize_floor", False)
    monkeypatch.setattr(mite_config, "normalize_brightness", False)
    results = pipeline.run_analysis(session, out, library_dir=library)
    assert results["normalization"] == {"floor": False, "brightness": False}

    monkeypatch.setattr(mite_config, "normalize_floor", True)
    normalised = pipeline.run_analysis(session, out, library_dir=library)
    assert normalised["normalization"] == {"floor": True, "brightness": False}
    assert [mite["scores"] for mite in normalised["mites"]] != [mite["scores"] for mite in results["mites"]]
    threshold = normalised["threshold"]
    assert all(mite["moving"] == [value >= threshold for value in mite["scores"]] for mite in normalised["mites"])
    json.dumps(pipeline.describe_movement(normalised), allow_nan=False)
    measurements = pd.read_excel(out / "results.xlsx", sheet_name="measurements")
    assert {"raw_score", "brightness"} <= set(measurements.columns)
    assert measurements["brightness"].notna().all()

    # a call corrected on the normalised scores goes by the detector's call on them
    mite = normalised["mites"][0]
    other = "still" if mite["moving"][1] else "moving"
    assert pipeline.correct_call(out, mite["id"], 1, other)["corrections"] == {mite["id"]: [1]}
    assert pipeline.correct_call(out, mite["id"], 1, "moving" if mite["moving"][1] else "still") == normalised

    monkeypatch.setattr(mite_config, "normalize_brightness", True)
    both = pipeline.run_analysis(session, out, library_dir=library)
    assert both["normalization"] == {"floor": True, "brightness": True}
    assert [mite["scores"] for mite in both["mites"]] != [mite["scores"] for mite in normalised["mites"]]
