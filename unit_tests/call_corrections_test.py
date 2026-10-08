"""The detector's calls corrected by hand on the result pages are kept next to the
recordings, and every number of the results follows them."""

import json

import pandas as pd
import pytest

import pipeline
import reference
from classes.call_corrections import CallCorrections
from classes.movement_stats import MovementReport, MovementStats
from classes.survival import SurvivalAnalysis, SurvivalReport
from classes.zones import MITE_SCORE_COLUMNS


def mite_data():
    """Two mites over three recordings; mite 0 moves in the first one only."""
    rows = [{"mite_ID": mite_id, "time": time, "motion_score": 1.0, "moving": moving, "zone_id": 1,
             "group": "a", "zone_type": "mite", "x": x, "y": 60.0}
            for mite_id, x, calls in (("0", 50.0, [True, False, False]), ("1", 90.0, [False, False, False]))
            for time, moving in zip([0.0, 5.0, 10.0], calls)]
    return pd.DataFrame(rows, columns=MITE_SCORE_COLUMNS)


def calls(data, mite_id):
    return list(data[data["mite_ID"] == mite_id].sort_values("time")["moving"])


def test_without_corrections_the_table_is_the_detectors(tmp_path):
    data = mite_data()
    applied, changes = CallCorrections(tmp_path).apply(data)
    assert applied is data and changes == {}


def test_a_corrected_call_replaces_the_detectors(tmp_path):
    corrections = CallCorrections(tmp_path)
    assert corrections.change(50.0, 60.0, 2, detected=False, state="moving") == "moving"
    applied, changes = corrections.apply(mite_data())
    assert calls(applied, "0") == [True, False, True] and calls(applied, "1") == [False, False, False]
    assert changes == {"corrections": {"0": [2]}}
    assert list(applied[applied["corrected"]]["time"]) == [10.0] and "censored" not in applied


def test_a_call_changed_back_to_the_detectors_is_no_correction(tmp_path):
    corrections = CallCorrections(tmp_path)
    corrections.change(50.0, 60.0, 0, detected=True, state="still")
    assert calls(corrections.apply(mite_data())[0], "0") == [False, False, False]
    corrections.change(50.0, 60.0, 0, detected=True, state="moving")
    assert corrections.apply(mite_data())[1] == {}
    assert json.loads((tmp_path / CallCorrections.FILENAME).read_text(encoding="utf-8")) == {}


def test_a_click_steps_through_moving_still_gone_and_gone_from_here_on(tmp_path):
    corrections = CallCorrections(tmp_path)
    steps = [corrections.change(50.0, 60.0, 1, detected=False) for _click in range(4)]
    assert steps == ["gone", "gone_from", "moving", "still"]
    assert corrections.apply(mite_data())[1] == {}  # round to the detector's call: nothing left


def test_a_mite_gone_in_a_recording_is_censored_there(tmp_path):
    corrections = CallCorrections(tmp_path)
    corrections.change(50.0, 60.0, 0, detected=True, state="gone")
    applied, changes = corrections.apply(mite_data())
    assert changes == {"censored": {"0": [0]}}
    assert calls(applied, "0") == [False, False, False]  # a censored row is not moving
    assert list(applied[applied["censored"]]["time"]) == [0.0]


def test_a_mite_gone_from_a_recording_on_is_censored_in_every_later_one(tmp_path):
    corrections = CallCorrections(tmp_path)
    corrections.change(50.0, 60.0, 1, detected=False, state="gone_from")
    assert corrections.apply(mite_data())[1] == {"censored": {"0": [1, 2]}, "gone_from": {"0": 1}}
    # seen again in the last recording: the one in between stays gone
    corrections.change(50.0, 60.0, 2, detected=False, state="moving")
    assert corrections.apply(mite_data())[1] == {"corrections": {"0": [2]}, "censored": {"0": [1]}}
    with pytest.raises(ValueError):
        corrections.change(50.0, 60.0, 2, detected=False, state="dead")


def test_corrections_go_by_position_and_by_pool_size(tmp_path):
    CallCorrections(tmp_path).change(52.0, 61.0, 1, detected=False, state="moving")  # a few pixels off: still mite 0
    assert CallCorrections(tmp_path).apply(mite_data())[1] == {"corrections": {"0": [1]}}
    assert CallCorrections(tmp_path, pool_size=30).apply(mite_data())[1] == {}
    far = mite_data().assign(x=lambda data: data["x"] + 200)
    assert CallCorrections(tmp_path).apply(far)[1] == {}


def test_a_damaged_file_reads_as_no_corrections(tmp_path):
    (tmp_path / CallCorrections.FILENAME).write_text("{not json", encoding="utf-8")
    assert CallCorrections(tmp_path).entries() == []
    (tmp_path / CallCorrections.FILENAME).write_text('{"recording": [{"x": 1}]}', encoding="utf-8")
    assert CallCorrections(tmp_path).entries() == []


# --- what the results make of them

def results():
    """Three mites of one zone over four recordings; mite 0 is gone from the third on, mite 1 in the second."""
    return {"times": [0, 10, 20, 30], "zones": [{"id": 1, "label": "a", "n_mites": 3}],
            "corrections": {"0": [1]}, "censored": {"0": [2, 3], "1": [1]}, "gone_from": {"0": 2},
            "mites": [{"id": "0", "zone_id": 1, "scores": [1.0, 2.0, 9.0, 9.0], "moving": [True, True, False, False]},
                      {"id": "1", "zone_id": 1, "scores": [5.0, 9.0, 5.0, 1.0], "moving": [True, False, True, False]},
                      {"id": "2", "zone_id": 1, "scores": [5.0, 1.0, 1.0, 1.0], "moving": [True, False, False, False]}]}


def test_the_pages_are_told_which_calls_are_the_users_and_where_a_mite_is_gone():
    described = MovementReport(results()).describe()
    first, second, _third = described["mites"]
    assert first["corrected"] == [False, True, False, False]
    assert first["censored"] == [False, False, True, True] and first["gone_from"] == 2
    assert second["censored"] == [False, True, False, False] and second["gone_from"] is None
    assert first["mean_score"] == 1.5 and first["max_score"] == 2.0  # not the scores of an empty spot
    [zone] = described["zones"]
    assert zone["n_seen"] == [3, 2, 2, 2] and zone["rests"] is None  # no rest through a recording not seen


def test_a_rest_is_not_counted_through_a_recording_in_which_the_mite_was_gone():
    assert MovementStats.rest_periods([True, False, True], [0, 5, 10]) == [10]
    assert MovementStats.rest_periods([True, None, True, False, True], [0, 5, 10, 15, 20]) == [10]


def test_a_mite_gone_for_good_is_censored_where_it_was_last_there():
    survival = SurvivalAnalysis([0, 10, 20, 30])
    assert survival.survival([True, True, None, None]) == (10, False)   # alive when last there
    assert survival.survival([True, False, None, None]) == (10, True)   # dead by then
    assert survival.survival([True, None, True, False]) == (30, True)   # a gap says nothing
    assert survival.survival([True, False, False, False]) == (10, True)
    assert not SurvivalAnalysis.in_study([None, None, False, False])


def test_the_survival_rate_takes_a_lost_mite_out_of_the_count():
    survival = SurvivalAnalysis([0, 10, 20, 30])
    lost = [[True, True, None, None], [True, True, True, False], [True, True, True, True]]
    # 3 at risk until 10 min; the lost mite leaves; then 1 of the 2 left dies at 30 min
    assert survival.alive_percent(lost) == [100.0, 100.0, 100.0, 50.0]
    report = SurvivalReport(results()).describe()
    assert report["mites"]["0"] == {"in_study": True, "time": 10, "dead": False, "lost": True}
    assert report["mites"]["2"] == {"in_study": True, "time": 10, "dead": True, "lost": False}
    json.dumps(report, allow_nan=False)  # what the server's JSON needs


@pytest.mark.slow
def test_a_call_corrected_on_the_result_pages_changes_the_results_and_stays(tmp_path):
    session = reference.make_small_session(tmp_path / "small_session")
    out, library = tmp_path / "out", tmp_path / "library"
    results = pipeline.run_analysis(session, out, library_dir=library)
    assert "corrections" not in results and "censored" not in results
    mite = results["mites"][0]
    zone = next(zone for zone in results["zones"] if zone["id"] == mite["zone_id"])
    detected, other = [("moving", "still"), ("still", "moving")][not mite["moving"][1]]

    changed = pipeline.correct_call(out, mite["id"], 1, other)
    after = changed["mites"][0]
    assert after["moving"][1] is not mite["moving"][1] and after["scores"] == mite["scores"]
    assert changed["corrections"] == {mite["id"]: [1]}
    zone_after = next(z for z in changed["zones"] if z["id"] == zone["id"])
    assert zone_after["moving"][1] != zone["moving"][1]  # the zone's numbers follow
    pipeline.finish_files(out)  # written a moment after the page has its numbers
    measurements = pd.read_excel(out / "results.xlsx", sheet_name="measurements")
    assert int(measurements["corrected"].sum()) == 1  # and so does the workbook

    again = pipeline.run_analysis(session, out, library_dir=library)  # another run keeps it
    assert again["mites"][0]["moving"] == after["moving"]

    assert pipeline.correct_call(out, mite["id"], 1, detected)["mites"] == results["mites"]  # back to the detector's
    with pytest.raises(ValueError):
        pipeline.correct_call(out, "no such mite", 0)
    with pytest.raises(ValueError):
        pipeline.correct_call(out, mite["id"], 99)


@pytest.mark.slow
def test_a_mite_marked_gone_counts_in_no_number_of_the_results(tmp_path):
    session = reference.make_small_session(tmp_path / "small_session")
    out, library = tmp_path / "out", tmp_path / "library"
    results = pipeline.run_analysis(session, out, library_dir=library)
    mite = results["mites"][0]
    n_last = len(results["times"]) - 1

    gone = pipeline.correct_call(out, mite["id"], 1, "gone_from")
    assert gone["censored"] == {mite["id"]: list(range(1, n_last + 1))} and gone["gone_from"] == {mite["id"]: 1}
    assert gone["summary"]["n_observations"] == results["summary"]["n_observations"] - n_last
    json.dumps(pipeline.describe_movement(gone), allow_nan=False)
    json.dumps(pipeline.describe_survival(gone), allow_nan=False)
    workbook = pd.read_excel(pipeline.results_file(out, "results.xlsx"), sheet_name=None)  # waits for it
    assert int(workbook["measurements"]["censored"].sum()) == n_last  # the rows stay, marked
    zone_rows = workbook["moving"][(workbook["moving"]["level"] == "zone") & (workbook["moving"]["name"] == mite["zone_id"])]
    n_zone = sum(1 for m in results["mites"] if m["zone_id"] == mite["zone_id"])
    assert list(zone_rows["n_mites"]) == [n_zone] + [n_zone - 1] * n_last

    assert pipeline.correct_call(out, mite["id"], 1, "moving" if mite["moving"][1] else "still") == results
