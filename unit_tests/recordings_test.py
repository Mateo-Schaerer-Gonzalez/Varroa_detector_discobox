"""Where the app keeps things: recordings/, results/ and the calibration reports;
the list of recordings the pages show; and moving the folders of earlier versions."""

import json
import shutil

import pytest

import pipeline
import reference


@pytest.fixture
def roots(tmp_path):
    return {"recordings_root": tmp_path / "recordings", "results_root": tmp_path / "results",
            "library_dir": tmp_path / "library"}


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


def test_a_live_run_writes_run_json_and_its_results_go_to_results(tmp_path, roots):
    small = reference.make_small_session(tmp_path / "small_session")
    library = roots["library_dir"]
    library.mkdir()
    status = pipeline.open_live("record", None, "run 1", source="replay", replay_dir=small, replay_fps=100_000,
                                replay_gap=0, pool_size=3, **roots)
    assert status["out_dir"] == str(roots["results_root"] / "run 1")
    pipeline.start_live("record")
    listed = pipeline.list_recordings(**roots)
    assert pipeline._live["record"].session.finished.wait(60)
    pipeline.close_live("record")
    assert not listed or listed[0]["recording_now"] or listed[0]["run"]["ended_at"]  # listed while it went on

    run_dir = roots["recordings_root"] / "run 1"
    info = json.loads((run_dir / "run.json").read_text())
    assert info["source"] == "replay" and info["camera"] == "replay of small_session"
    assert info["replay_of"] == str(small.resolve())
    assert (info["recordings_planned"], info["recordings_analysed"], info["pool_size"]) == (3, 3, 3)
    assert info["ended_at"] >= info["started_at"] and info["error"] is None
    assert (roots["results_root"] / "run 1" / "results.xlsx").is_file()

    [listed] = pipeline.list_recordings(**roots)
    assert listed["run"]["pool_size_text"] == "3 frames" and not listed["recording_now"]
    assert listed["results"]["file"] == "results.xlsx"
    # the replay's settings are kept with its recordings, as the Discobox app keeps them
    assert listed["settings"]["recording_timeout"] == 5


def test_clips_are_kept_apart_and_a_folder_opened_again_gets_new_ones(tmp_path):
    small = reference.make_small_session(tmp_path / "small_session")
    out_dir = pipeline.results_dir(small, tmp_path / "results")
    assert out_dir == tmp_path / "results" / "small_session"
    pipeline.open_session(small, out_dir, library_dir=tmp_path / "library")
    clip = pipeline.analysis_clip(small, out_dir, 0, zone_id=0)
    assert all((out_dir / name).is_file() and name.startswith("clips/") for name in clip["frames"])
    pipeline.open_session(small, out_dir, library_dir=tmp_path / "library")
    assert not (out_dir / "clips").exists()


def test_each_calibration_session_gets_a_folder_of_its_own(tmp_path):
    first = pipeline.new_calibration_report_dir("sample/data", tmp_path)
    second = pipeline.new_calibration_report_dir("sample/data", tmp_path)
    assert first != second and first.is_dir() and second.is_dir()
    assert first.name.endswith(" sample_data") and first.parent == tmp_path


def test_the_folders_of_earlier_versions_move_to_todays(tmp_path):
    app = tmp_path / "app"
    live_run = reference.make_small_session(app / "output" / "test_run_1")
    dropped = reference.make_small_session(app / "uploads" / "dropped")
    (app / "outputs" / "3b70a75b").mkdir(parents=True)
    (app / "outputs" / "3b70a75b" / "results.xlsx").write_bytes(b"x")
    (app / "output" / "taken").mkdir()
    (app / "recordings" / "taken").mkdir(parents=True)  # never overwritten
    library = app / "calibration_data"
    old_id = pipeline.dataset_id(dropped)
    (library / old_id).mkdir(parents=True)
    (library / old_id / "dataset.json").write_text(json.dumps(
        {"data_dir": str(dropped.resolve()), "name": "dropped", "times": [0.0], "mites": [], "truth": {}}))
    reports = library / "reports"
    (reports / "2026-09-01 10-00-00 no report").mkdir(parents=True)
    (reports / "2026-09-01 11-00-00 a report").mkdir()
    (reports / "2026-09-01 11-00-00 a report" / "calibration.xlsx").write_bytes(b"x")

    done = pipeline.tidy_folders(app, app / "recordings", app / "results", library, reports)
    assert (app / "recordings" / "test_run_1").is_dir() and (app / "recordings" / "dropped").is_dir()
    assert (app / "results" / "earlier sessions" / "3b70a75b" / "results.xlsx").is_file()
    assert (app / "output" / "taken").is_dir() and not (app / "uploads").exists() and not (app / "outputs").exists()
    assert any("left output/taken where it is" in line for line in done)
    assert pipeline.list_recordings(app / "recordings", app / "results", library)
    # the saved ground truth of the dropped folder follows it
    new_id = pipeline.dataset_id(app / "recordings" / "dropped")
    moved = json.loads((library / new_id / "dataset.json").read_text())
    assert moved["data_dir"] == str((app / "recordings" / "dropped").resolve()) and not (library / old_id).exists()
    # only calibration sessions that made a report are kept
    assert [path.name for path in reports.iterdir()] == ["2026-09-01 11-00-00 a report"]
    # a second start has nothing more to move
    shutil.rmtree(app / "output")
    assert pipeline.tidy_folders(app, app / "recordings", app / "results", library, reports) == []
    assert not live_run.exists()
