"""What the server works out for the pages, so the browser only draws it: the test
report's error map and rates, the live run's progress, the list of recordings, the
files a dropped folder needs copied, and the "not a mite" marks of the label page."""

import json

import pytest

import pipeline
from classes.results import reporting
from classes.ground_truth.calibration import outcome_rates
from classes.results.error_map import ErrorMap
from classes.live.progress import RunProgress
from classes.storage.recording_info import RecordingInfo
from classes.storage.upload_plan import UploadPlan


def row(mite, recording, outcome, dataset="d"):
    return {"dataset": dataset, "dataset_name": "Dataset", "mite_id": mite, "zone_id": 1, "x": 5.0, "y": 6.0,
            "recording": recording, "recording_name": f"r{recording}", "time": 5.0 * recording, "outcome": outcome}


# --- the test report

def test_each_mite_on_the_error_map_is_coloured_by_its_more_frequent_error():
    rows = [row("0", 0, "moving_called_moving"), row("0", 1, "moving_called_moving"),
            row("1", 0, "moving_called_still"), row("1", 1, "still_called_moving"),
            row("2", 0, "still_called_moving"), row("2", 1, "still_called_still")]
    selection = ErrorMap(rows).describe()["d"]["all"]
    assert [(m["mite_id"], m["kind"]) for m in selection["mites"]] == [
        ("0", "correct"), ("1", "missed-positive"), ("2", "missed-negative")]  # a tie counts as moving missed
    assert selection["counts"] == {"correct": 1, "missed-positive": 1, "missed-negative": 1}
    one = selection["mites"][1]
    assert one["n"] == 2 and one["moving_missed"] == [{"time": 0.0, "recording_name": "r0"}]
    assert one["open"] == {"dataset": "d", "zone_id": 1, "mite_id": "1", "recording": 0}  # its first error


def test_the_error_map_of_one_recording():
    rows = [row("0", 0, "moving_called_still"), row("0", 1, "moving_called_moving")]
    recordings = ErrorMap(rows).describe()["d"]["recordings"]
    assert recordings[1]["mites"][0]["kind"] == "correct"
    assert recordings[0]["mites"][0]["kind"] == "missed-positive"


def test_outcome_rates_are_fractions_of_their_row():
    counts = {"moving_called_moving": 3, "moving_called_still": 1, "still_called_moving": 0, "still_called_still": 0,
              "n_moving": 4, "n_still": 0}
    assert outcome_rates(counts) == {"moving_called_moving": 0.75, "moving_called_still": 0.25,
                                     "still_called_moving": None, "still_called_still": None}


# --- the live run's progress

def status(**overrides):
    return {"timeline": {"elapsed": 30.0, "length": 120.0, "starts": [0.0, 60.0, 120.0]},
            "analysed": 1, "completed": 1, "recording_name": "r1", "state": "running", **overrides}


def test_the_progress_is_the_zones_circles_and_the_countdown():
    zones = [{"id": 1, "label": "venom", "mites": 2, "dead": 1, "gone": 0, "fraction": 0.5, "done": False, "counts": True}]
    assert RunProgress(status(), zones).describe() == {"zones": zones, "next_seconds": 30.0}
    assert RunProgress(status(timeline=None)).describe() == {"zones": [], "next_seconds": None}  # before the run starts


def test_the_countdown_to_the_next_recording():
    assert RunProgress(status()).describe()["next_seconds"] == 30.0
    assert RunProgress(status(state="paused")).describe()["next_seconds"] == 30.0
    last = {"elapsed": 120.0, "length": 141.0, "starts": [0.0, 60.0, 120.0]}
    assert RunProgress(status(timeline=last)).describe()["next_seconds"] is None  # none to come
    assert RunProgress(status(state="stopping")).describe()["next_seconds"] is None
    assert RunProgress(status(state="finished")).describe()["next_seconds"] is None


# --- the list of recordings

def test_the_state_of_a_live_run():
    assert RecordingInfo.state(None, True) == "recording"
    assert RecordingInfo.state(None, False) is None
    assert RecordingInfo.state({"ended_at": None}, False) == "interrupted"
    assert RecordingInfo.state({"ended_at": "x", "recordings_analysed": 4, "recordings_planned": 6}, False) == "stopped"
    assert RecordingInfo.state({"ended_at": "x", "recordings_analysed": 6, "recordings_planned": 6}, False) is None


def test_the_recordings_planned():
    assert RecordingInfo.planned({"recordings_planned": 6}, {"recording_count": 9}) == 6
    assert RecordingInfo.planned(None, {"recording_count": 9}) == 9
    assert RecordingInfo.planned(None, None) is None


def test_the_fan_and_leds():
    alike = {"vent_time": 20, "led1_time": 20, "led2_time": 20, "vent": 255, "led1": 255, "led2": 255}
    assert RecordingInfo.lights(alike)["all_alike"] == {"seconds": 20, "level": 255}
    mixed = RecordingInfo.lights({**alike, "led2_time": 0, "led1": 100})
    assert mixed["all_alike"] is None and mixed["level"] is None
    assert mixed["devices"][2] == {"name": "LED 2", "seconds": 0, "level": 255}
    assert RecordingInfo.lights({**alike, "led2_time": 0})["level"] == 255  # every device on has one intensity
    assert RecordingInfo.lights(None) == {"all_alike": None, "level": None, "devices": []}


# --- a folder dropped into the page

def test_only_the_files_the_app_needs_are_copied():
    files = [{"path": "r_fps-30/a.BMP", "size": 3}, {"path": "notes.docx", "size": 1}, {"path": ".settings.txt", "size": 2},
             {"path": "labels.json", "size": 2}, {"path": "Labels.json", "size": 2}]
    plan = UploadPlan("session", files)
    assert [f["target"] for f in plan.files] == ["r_fps-30/a.BMP", ".settings.txt", "labels.json"]
    kept = UploadPlan("session", [{"path": "r_fps-30/a.bmp", "size": 3}, {"path": "ground_truth.json", "size": 2},
                                  {"path": "poke_test.json", "size": 2}])
    assert [f["target"] for f in kept.files] == ["r_fps-30/a.bmp", "ground_truth.json", "poke_test.json"]
    assert kept.missing(lambda target: 1 if target.endswith(".json") else None) == [
        {"path": "r_fps-30/a.bmp", "target": "r_fps-30/a.bmp"}]  # what was entered in this app is never replaced


def test_a_single_recording_folder_becomes_a_session():
    plan = UploadPlan("2025-09-04_fps-30", [{"path": "a.bmp", "size": 3}])
    assert plan.name == "2025-09-04_fps-30_session"
    assert plan.files[0]["target"] == "2025-09-04_fps-30/a.bmp"


def test_a_session_saved_as_the_mites_rois_is_copied_whole_but_for_its_unfinished_parts():
    files = [{"path": path, "size": 1} for path in (
        "first_frame.png", "rois/index.json", "rois/mite_000.mkv", "rois/parts/r_fps-30/mite_000.mkv",
        "rois/parts/r_fps-30.part/mite_000.mkv", "rois/stitching/mite_000.mkv", "rois/index.json.part", ".settings.txt")]
    plan = UploadPlan("run", files)
    assert [f["target"] for f in plan.files] == [
        "first_frame.png", "rois/index.json", "rois/mite_000.mkv", "rois/parts/r_fps-30/mite_000.mkv", ".settings.txt"]
    with pytest.raises(ValueError, match="No .bmp images"):
        UploadPlan("run", [{"path": "rois/mite_000.mkv", "size": 1}])


def test_a_folder_without_frames_or_with_a_bad_path_is_refused():
    with pytest.raises(ValueError, match="No .bmp images"):
        UploadPlan("session", [{"path": "a.txt", "size": 1}])
    with pytest.raises(ValueError):
        UploadPlan("session", [{"path": "../a.bmp", "size": 1}])
    with pytest.raises(ValueError):
        UploadPlan("..", [{"path": "a.bmp", "size": 1}])


def test_files_already_here_are_not_copied_again(tmp_path):
    folder = tmp_path / "session"
    (folder / "r_fps-30").mkdir(parents=True)
    (folder / "r_fps-30" / "a.bmp").write_bytes(b"abc")
    (folder / "labels.json").write_text("{}")  # typed in the app: never replaced
    files = [{"path": "r_fps-30/a.bmp", "size": 3}, {"path": "r_fps-30/b.bmp", "size": 3}, {"path": "labels.json", "size": 99}]
    plan = pipeline.plan_upload("session", files, tmp_path)
    assert plan["name"] == "session" and plan["data_dir"] == str(folder)
    assert plan["missing"] == [{"path": "r_fps-30/b.bmp", "target": "r_fps-30/b.bmp"}]


# --- the label page's "not a mite" marks

MITES = [{"id": "0", "zone_id": 1, "x": 50.0, "y": 60.0}, {"id": "1", "zone_id": 1, "x": 90.0, "y": 60.0},
         {"id": "2", "zone_id": 2, "x": 200.0, "y": 60.0}]


def test_a_mark_says_how_many_mites_each_zone_has_left(tmp_path):
    marks = pipeline.mark_detection(tmp_path, MITES, "0", True)
    assert marks == {"mites": {"0": True, "1": False, "2": False}, "zones": {1: 1, 2: 1}}
    marks = pipeline.mark_detection(tmp_path, MITES, "0", False)
    assert marks["zones"] == {1: 2, 2: 1}


def test_taking_a_mark_back_puts_back_the_labels_it_replaced(tmp_path):
    entry = {"x": 50.0, "y": 60.0, "truth": ["moving", "still"]}
    (tmp_path / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([entry]), encoding="utf-8")
    pipeline.mark_detection(tmp_path, MITES, "0", True)
    pipeline.mark_detection(tmp_path, MITES, "0", False)
    assert json.loads((tmp_path / pipeline.GROUND_TRUTH_FILENAME).read_text(encoding="utf-8")) == [entry]


def test_an_unknown_detection_is_refused(tmp_path):
    with pytest.raises(ValueError):
        pipeline.mark_detection(tmp_path, MITES, "9", True)


# --- the movement scores of the calibration report

def test_the_score_picker_is_told_which_parameters_are_whole_numbers():
    metrics = {metric["name"]: metric for metric in pipeline.movement_scores()["metrics"]}
    assert metrics["topN_variability"]["whole"] == ["n"]
    assert metrics["outline_variability"]["whole"] == ["pad"]
    assert "poly_sigma" not in metrics["optical_flow"]["whole"] and "pad" in metrics["optical_flow"]["whole"]


# --- small things

def test_a_live_run_not_open_says_so():
    # the server answers 404 for it, and the page lets the run go
    with pytest.raises(pipeline.LiveRunNotOpen):
        pipeline.live_status("not-open")


def test_the_death_time_limits_are_those_of_the_settings():
    assert pipeline.death_minutes_range() == [0, 43200]


def test_a_group_seen_once_has_no_sd_rather_than_nan():
    import pandas as pd
    data = pd.DataFrame({"group": ["a"], "mite_ID": [1], "motion_score": [2.0], "moving": [True], "time": [0.0]})
    [group] = reporting._summary(data)["groups"]
    assert group["std_score"] is None
    json.dumps(group, allow_nan=False)  # what the server's JSON needs


def test_the_workbook_says_when_each_mite_last_moved_and_shows_where_it_is(tmp_path):
    import cv2
    import numpy as np
    import pandas as pd
    from openpyxl import load_workbook
    calls = {"0.2": [True, True, False], "0.10": [False, False, False], "0.1": [True, False, True]}
    data = pd.DataFrame([{"mite_ID": mite, "time": 10.0 * at, "motion_score": float(at), "moving": moving,
                          "zone_id": 0, "group": "a", "censored": mite == "0.1" and at == 2}
                         for mite, moves in calls.items() for at, moving in enumerate(moves)])
    cv2.imwrite(str(tmp_path / "plate.jpg"), np.zeros((30, 40, 3), np.uint8))

    reporting.write_excel(data, tmp_path, tmp_path / "plate.jpg")

    sheets = pd.read_excel(tmp_path / reporting.EXCEL_NAME, sheet_name=None, dtype={"mite_ID": str})
    assert list(sheets)[:3] == ["mites", "scores", "mite_map"]
    assert list(sheets["mites"]["mite_ID"]) == ["0.1", "0.2", "0.10"]
    last_moved = list(sheets["mites"]["last_moved_min"])
    assert last_moved[:2] == [0.0, 10.0] and pd.isna(last_moved[2])  # not where it was gone; never
    assert list(sheets["scores"].columns) == ["mite_ID", "zone_id", "group", 0, 10, 20]
    assert list(sheets["scores"].iloc[0, 3:]) == [0, 1, 2]
    assert len(load_workbook(tmp_path / reporting.EXCEL_NAME)["mite_map"]._images) == 1
