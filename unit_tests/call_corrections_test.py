"""The detector's calls corrected by hand on the result pages are kept next to the
recordings, and every number of the results follows them."""

import json

import pandas as pd
import pytest

import pipeline
import reference
from classes.call_corrections import CallCorrections
from classes.movement_stats import MovementReport
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
    applied, corrections = CallCorrections(tmp_path).apply(data)
    assert applied is data and corrections == {}


def test_a_corrected_call_replaces_the_detectors(tmp_path):
    corrections = CallCorrections(tmp_path)
    assert corrections.toggle(50.0, 60.0, 2, detected=False) is True
    applied, which = corrections.apply(mite_data())
    assert calls(applied, "0") == [True, False, True] and calls(applied, "1") == [False, False, False]
    assert which == {"0": [2]}
    assert list(applied[applied["corrected"]]["time"]) == [10.0]


def test_changing_a_call_again_brings_back_the_detectors(tmp_path):
    corrections = CallCorrections(tmp_path)
    corrections.toggle(50.0, 60.0, 0, detected=True)
    assert calls(corrections.apply(mite_data())[0], "0") == [False, False, False]
    assert corrections.toggle(50.0, 60.0, 0, detected=True) is True
    assert corrections.apply(mite_data())[1] == {}
    assert json.loads((tmp_path / CallCorrections.FILENAME).read_text(encoding="utf-8")) == {}


def test_corrections_go_by_position_and_by_pool_size(tmp_path):
    CallCorrections(tmp_path).toggle(52.0, 61.0, 1, detected=False)  # a few pixels off: still mite 0
    assert CallCorrections(tmp_path).apply(mite_data())[1] == {"0": [1]}
    assert CallCorrections(tmp_path, pool_size=30).apply(mite_data())[1] == {}
    far = mite_data().assign(x=lambda data: data["x"] + 200)
    assert CallCorrections(tmp_path).apply(far)[1] == {}


def test_a_damaged_file_reads_as_no_corrections(tmp_path):
    (tmp_path / CallCorrections.FILENAME).write_text("{not json", encoding="utf-8")
    assert CallCorrections(tmp_path).entries() == []
    (tmp_path / CallCorrections.FILENAME).write_text('{"recording": [{"x": 1}]}', encoding="utf-8")
    assert CallCorrections(tmp_path).entries() == []


def test_the_pages_are_told_which_calls_are_the_users():
    results = {"times": [0, 10], "zones": [{"id": 1, "label": "a", "n_mites": 2}], "corrections": {"0": [1]},
               "mites": [{"id": "0", "zone_id": 1, "scores": [1.0, 2.0], "moving": [False, True]},
                         {"id": "1", "zone_id": 1, "scores": [1.0, 2.0], "moving": [False, False]}]}
    mites = MovementReport(results).describe()["mites"]
    assert [mite["corrected"] for mite in mites] == [[False, True], [False, False]]


@pytest.mark.slow
def test_a_call_corrected_on_the_result_pages_changes_the_results_and_stays(tmp_path):
    session = reference.make_small_session(tmp_path / "small_session")
    out, library = tmp_path / "out", tmp_path / "library"
    results = pipeline.run_analysis(session, out, library_dir=library)
    assert "corrections" not in results
    mite = results["mites"][0]
    zone = next(zone for zone in results["zones"] if zone["id"] == mite["zone_id"])

    changed = pipeline.correct_call(out, mite["id"], 1)
    after = changed["mites"][0]
    assert after["moving"][1] is not mite["moving"][1] and after["scores"] == mite["scores"]
    assert changed["corrections"] == {mite["id"]: [1]}
    zone_after = next(z for z in changed["zones"] if z["id"] == zone["id"])
    assert zone_after["moving"][1] != zone["moving"][1]  # the zone's numbers follow
    measurements = pd.read_excel(out / "results.xlsx", sheet_name="measurements")
    assert int(measurements["corrected"].sum()) == 1  # and so does the workbook

    again = pipeline.run_analysis(session, out, library_dir=library)  # another run keeps it
    assert again["mites"][0]["moving"] == after["moving"]

    assert pipeline.correct_call(out, mite["id"], 1)["mites"] == results["mites"]  # back to the detector's
    with pytest.raises(ValueError):
        pipeline.correct_call(out, "no such mite", 0)
    with pytest.raises(ValueError):
        pipeline.correct_call(out, mite["id"], 99)
