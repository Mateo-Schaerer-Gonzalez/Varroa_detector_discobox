"""Where the app keeps things: recordings/, results/ and the calibration reports in it;
the list of recordings the pages show; and moving the folders of earlier versions."""

import json
import shutil

import pytest

import folder_camera
import pipeline
import reference


@pytest.fixture
def roots(tmp_path):
    return {"recordings_root": tmp_path / "recordings", "results_root": tmp_path / "results"}


def test_a_folder_is_listed_with_its_settings_labels_marks_and_results(tmp_path, roots):
    folder = reference.make_small_session(roots["recordings_root"] / "hive 3")
    (folder / "labels.json").write_text(json.dumps({"0": "control", "1": "venom", "2": "control", "3": " "}))
    (folder / "ground_truth.json").write_text(json.dumps([
        {"x": 10, "y": 10, "truth": ["not_a_mite"]},
        {"x": 50, "y": 50, "truth": ["moving", None, "still"]},
        {"x": 90, "y": 90, "truth": [None, None, None]},
    ]))
    (roots["recordings_root"] / "empty run").mkdir()  # nothing recorded: not listed
    (roots["results_root"] / "hive 3").mkdir(parents=True)
    (roots["results_root"] / "hive 3" / "results.xlsx").write_bytes(b"x")

    [listed] = pipeline.list_recordings(**roots)
    first, last = sorted(d.name for d in folder.iterdir() if d.is_dir())[::2]
    assert listed["name"] == "hive 3" and listed["path"] == str(folder.resolve())
    assert listed["started"] == pipeline.DataLoader.parse_start_time(first).isoformat()
    assert listed["ended"] >= pipeline.DataLoader.parse_start_time(last).isoformat()  # to the second
    assert (listed["n_recordings"], listed["frames"], listed["fps"]) == (3, reference.SMALL_FRAMES, 30)
    assert listed["settings"] == {"recording_count": 6, "recording_timeout": 5, "vent_time": 20, "led1_time": 20,
                                  "led2_time": 20, "frame_count": 30, "fps": 30, "vent": 255, "led1": 255, "led2": 255}
    assert listed["run"] is None  # not a live run of this app
    assert (listed["n_labelled_plates"], listed["groups"]) == (3, ["control", "venom"])
    assert (listed["n_not_a_mite"], listed["n_ground_truth"]) == (1, 1)
    assert listed["results"]["file"] == "results.xlsx" and not listed["recording_now"]
    assert pipeline.recording_results_file("hive 3", "results.xlsx", roots["results_root"]).endswith("results.xlsx")


def test_a_folder_without_settings_is_listed_from_its_recordings(tmp_path, roots):
    folder = reference.make_small_session(roots["recordings_root"] / "copied")
    (folder / ".settings.txt").unlink()
    [listed] = pipeline.list_recordings(**roots)
    assert listed["settings"] is None and listed["fps"] == 30 and listed["results"] is None


@pytest.mark.parametrize("name, filename", [("..", "results.xlsx"), ("run", "../x"), ("a/b", "results.xlsx"), ("run", "")])
def test_a_results_file_is_only_ever_one_in_a_results_folder(tmp_path, name, filename):
    with pytest.raises(ValueError):
        pipeline.recording_results_file(name, filename, tmp_path)


def test_a_live_run_writes_run_json_and_its_results_go_to_results(tmp_path, roots, monkeypatch):
    small = reference.make_small_session(tmp_path / "small_session")
    status = folder_camera.open_live(monkeypatch, "record", None, "run 1", small, **roots)
    assert status["out_dir"] == str(roots["results_root"] / "run 1")
    pipeline.start_live("record")
    listed = pipeline.list_recordings(**roots)
    assert pipeline._live["record"].session.finished.wait(60)
    pipeline.close_live("record")
    assert not listed or listed[0]["recording_now"] or listed[0]["run"]["ended_at"]  # listed while it went on

    run_dir = roots["recordings_root"] / "run 1"
    info = json.loads((run_dir / "run.json").read_text())
    assert info["source"] == "camera" and info["camera"] == "Folder camera (small_session)"
    assert (info["recordings_planned"], info["recordings_analysed"], info["frames_saved"]) == (3, 3, True)
    assert info["ended_at"] >= info["started_at"] and info["error"] is None
    assert (roots["results_root"] / "run 1" / "results.xlsx").is_file()

    [listed] = pipeline.list_recordings(**roots)
    assert listed["run"]["camera"] == info["camera"] and not listed["recording_now"]
    assert listed["results"]["file"] == "results.xlsx"
    # the run's settings are kept with its recordings, as the Discobox app keeps them
    assert listed["settings"]["recording_timeout"] == 5


def test_clips_are_kept_apart_and_a_folder_opened_again_gets_new_ones(tmp_path):
    small = reference.make_small_session(tmp_path / "small_session")
    out_dir = pipeline.results_dir(small, tmp_path / "results")
    assert out_dir == tmp_path / "results" / "small_session"
    pipeline.open_session(small, out_dir)
    clip = pipeline.analysis_clip(small, out_dir, 0, zone_id=0)
    assert all((out_dir / name).is_file() and name.startswith("clips/") for name in clip["frames"])
    pipeline.open_session(small, out_dir)
    assert not (out_dir / "clips").exists()


def test_a_calibration_works_in_its_recordings_results_and_a_pooled_report_in_a_folder_of_its_own(tmp_path):
    assert pipeline.calibration_dir(tmp_path / "recordings" / "hive 3", tmp_path) == tmp_path / "hive 3" / "calibration"
    assert (tmp_path / "hive 3" / "calibration").is_dir()
    first = pipeline.new_pooled_report_dir(tmp_path)
    second = pipeline.new_pooled_report_dir(tmp_path)
    assert first != second and first.is_dir() and second.is_dir() and first.parent == tmp_path / "pooled"


def test_pooled_report_folders_without_a_report_are_removed(tmp_path):
    pooled = tmp_path / "results" / "pooled"
    (pooled / "2026-09-01 10-00-00").mkdir(parents=True)
    (pooled / "2026-09-01 11-00-00").mkdir()
    (pooled / "2026-09-01 11-00-00" / "calibration.xlsx").write_bytes(b"x")
    pipeline.remove_empty_pooled_reports(tmp_path / "results")
    assert [path.name for path in pooled.iterdir()] == ["2026-09-01 11-00-00"]
    pipeline.remove_empty_pooled_reports(tmp_path / "nothing here")  # no results folder yet
