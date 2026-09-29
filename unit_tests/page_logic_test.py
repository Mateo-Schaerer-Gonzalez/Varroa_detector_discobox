"""What the server works out for the pages, so the browser only draws it: the test
report's error map and rates, the live progress bar, the list of recordings, the
files a dropped folder needs copied, and the "not a mite" marks of the label page."""

import json

import pytest

import pipeline
import reporting
from classes.calibration import outcome_rates
from classes.error_map import ErrorMap
from classes.live.progress import RunProgress
from classes.recording_info import RecordingInfo
from classes.upload_plan import UploadPlan


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
    assert one["open"] == {"dataset": "d", "zone_id": 1, "recording": 0}  # its first error


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


# --- the live progress bar

def status(**overrides):
    return {"timeline": {"elapsed": 30.0, "length": 120.0, "starts": [0.0, 60.0, 120.0]}, "open_ended": False,
            "alive": None, "analysed": 1, "completed": 1, "recording_name": "r1", **overrides}


def test_the_bar_fills_as_the_run_goes_with_a_tick_per_recording():
    progress = RunProgress(status()).describe()
    assert progress["fraction"] == 0.25 and progress["left_seconds"] == 90.0 and not progress["alive_bar"]
    assert progress["marks"] == [{"at": 0.0, "state": "analysed"}, {"at": 0.5, "state": "capturing"},
                                 {"at": 1.0, "state": "planned"}]


def test_a_run_until_every_mite_is_dead_shows_the_mites_alive():
    progress = RunProgress(status(open_ended=True, alive={"alive": 3, "mites": 4})).describe()
    assert progress["fraction"] == 0.75 and progress["alive_bar"] and progress["marks"] == []
    assert RunProgress(status(open_ended=True)).describe()["fraction"] == 1  # before the first results


def test_no_bar_before_the_run_starts():
    assert RunProgress(status(timeline=None)).describe() == {"fraction": 0, "alive_bar": False, "marks": [], "left_seconds": 0}
    starting = RunProgress(status(timeline={"elapsed": 0.0, "length": 0.0, "starts": [0.0]})).describe()
    assert starting["fraction"] == 0 and starting["marks"] == []


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


def test_a_single_recording_folder_becomes_a_session():
    plan = UploadPlan("2025-09-04_fps-30", [{"path": "a.bmp", "size": 3}])
    assert plan.name == "2025-09-04_fps-30_session"
    assert plan.files[0]["target"] == "2025-09-04_fps-30/a.bmp"


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
    marks = pipeline.mark_detection(tmp_path, MITES, "0", True, library_dir=tmp_path / "library")
    assert marks == {"mites": {"0": True, "1": False, "2": False}, "zones": {1: 1, 2: 1}}
    marks = pipeline.mark_detection(tmp_path, MITES, "0", False, library_dir=tmp_path / "library")
    assert marks["zones"] == {1: 2, 2: 1}


def test_taking_a_mark_back_puts_back_the_labels_it_replaced(tmp_path):
    entry = {"x": 50.0, "y": 60.0, "truth": ["moving", "still"]}
    (tmp_path / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([entry]), encoding="utf-8")
    pipeline.mark_detection(tmp_path, MITES, "0", True, library_dir=tmp_path / "library")
    pipeline.mark_detection(tmp_path, MITES, "0", False, library_dir=tmp_path / "library")
    assert json.loads((tmp_path / pipeline.GROUND_TRUTH_FILENAME).read_text(encoding="utf-8")) == [entry]


def test_an_unknown_detection_is_refused(tmp_path):
    with pytest.raises(ValueError):
        pipeline.mark_detection(tmp_path, MITES, "9", True)


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
