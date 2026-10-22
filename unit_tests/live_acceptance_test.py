"""A live run must give exactly what folder mode gives on the frames it saved.

Each run here feeds a recorded folder through the whole live pipeline (a stand-in
for the camera, the analysis core, the recorder, the published results), then
runs folder mode on the run's folder and compares everything: the results the
pages are drawn from, the workbook, what each figure draws and the images'
pixels. The first test also compares the live run with the reference made before
live input existed.
"""

import json
import shutil
import time

import pytest

import folder_camera
import pipeline
from pipeline.live import live_runs
import reference
import reporting


@pytest.fixture
def live_run(tmp_path, monkeypatch):
    """Run `data_dir` as a live run as fast as it goes; the run's parts once it
    has finished, and the figures it drew last."""
    def run_it(data_dir, name="run", **kwargs):
        live_id = f"test-{name}"
        with reference.capture_figures() as figures:
            folder_camera.open_live(monkeypatch, live_id, tmp_path / f"{name}_out", name, data_dir,
                                    recordings_root=tmp_path / "recordings", **kwargs)
            pipeline.start_live(live_id)
            run = live_runs.open_runs[live_id]
            assert run.session.finished.wait(120), "the live run did not finish"
        status = pipeline.live_status(live_id)
        results = pipeline.live_results(live_id)["results"]
        live_runs.open_runs.pop(live_id)  # keep its folder, which close_live() would remove if empty
        return {"run": run, "status": status, "results": reference.plain(results), "figures": figures,
                **reference.outputs(run.out_dir)}
    return run_it


def folder(tmp_path, run, **kwargs):
    """Folder mode on a live run's folder, as the command line or the page runs it."""
    return reference.run_folder(run.run_dir, tmp_path / "folder_out",
                                pipeline.load_labels(run.run_dir) or None, **kwargs)


def assert_same(expected, actual, what):
    found = reference.differences(expected, actual)
    assert not found, f"{what} differs:\n  " + "\n  ".join(found)


def assert_live_equals_folder(live, folder_run):
    assert_same(folder_run["results"], live["results"], "The live results")
    assert live["files"] == folder_run["files"]
    assert_same(folder_run["excel"], live["excel"], "The live results.xlsx")
    assert_same(folder_run["figures"], live["figures"], "The live figures")
    assert_same(folder_run["pixels"], live["pixels"], "The live images")


@pytest.mark.slow
def test_a_live_run_gives_folder_mode_results_and_the_reference(tmp_path, live_run):
    if any((reference.SAMPLE_DATA / name).exists() for name in ("labels.json", "ground_truth.json", "corrections.json")):
        pytest.skip("sample_data holds labels, ground truth or corrected calls the reference was made without.")
    live = live_run(reference.SAMPLE_DATA)
    assert live["status"]["state"] == "finished" and live["status"]["error"] is None
    assert live["status"]["saved_frames"] == 180

    assert_live_equals_folder(live, folder(tmp_path, live["run"]))

    expected = reference.load("folder_sample_data")
    # a folder of whole frames, against the mites' ROIs the live run saved
    assert_same({**expected["results"], "frames": "rois"}, live["results"], "The live results, against the reference,")
    assert_same(expected["excel"], live["excel"], "The live results.xlsx, against the reference,")
    assert_same(expected["figures"], live["figures"], "The live figures, against the reference,")


@pytest.fixture
def small_session(tmp_path):
    """A few frames of sample_data, labelled, with one detection marked not a mite."""
    session = reference.make_small_session(tmp_path / "small_session")
    labels = {"4": "control", "7": "control", "13": "venom"}  # zones with mites
    (session / "labels.json").write_text(json.dumps(labels))
    mite = next(m for m in reference.load("folder_sample_data")["results"]["mites"] if m["id"] == reference.REJECTED_MITE)
    (session / "ground_truth.json").write_text(json.dumps([{"x": mite["x"], "y": mite["y"], "truth": ["not_a_mite"]}]))
    return session


def test_labels_and_not_a_mite_marks_apply_live_as_in_folder_mode(tmp_path, small_session, live_run):
    live = live_run(small_session)
    assert {g["group"] for g in live["results"]["summary"]["groups"]} >= {"control", "venom"}
    assert reference.REJECTED_MITE not in {m["id"] for m in live["results"]["mites"]}
    assert_live_equals_folder(live, folder(tmp_path, live["run"]))


def test_without_saving_frames_the_results_are_the_same(tmp_path, small_session, live_run):
    live = live_run(small_session, save_frames=False)
    assert not any(path.suffix in (".bmp", ".mkv", ".png") for path in live["run"].run_dir.rglob("*"))
    original = reference.run_folder(small_session, tmp_path / "original_out",
                                    pipeline.load_labels(small_session))
    assert_same({**original["results"], "frames": "none"}, live["results"], "The live results")


def test_a_run_stopped_midway_is_analysed_as_far_as_it_got(tmp_path, small_session, monkeypatch):
    folder_camera.open_live(monkeypatch, "stop", tmp_path / "out", "stopped", small_session, gap=30,
                            recordings_root=tmp_path / "recordings")
    pipeline.start_live("stop")
    run = live_runs.open_runs["stop"]
    deadline = time.monotonic() + 20
    while pipeline.live_status("stop")["completed"] < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    pipeline.stop_live("stop", wait=True, timeout=60)  # between the first recording and the second
    status = pipeline.live_status("stop")
    live_runs.open_runs.pop("stop")
    assert status["state"] == "finished" and status["analysed"] == 1
    live = reference.plain(run.session.results)
    again = folder(tmp_path, run)
    assert_same(again["results"], live, "The results of the stopped run")


def test_the_workbook_is_written_in_the_background_while_the_run_goes_on(tmp_path, small_session, monkeypatch):
    folder_camera.open_live(monkeypatch, "files", tmp_path / "out", "files", small_session, gap=30,
                            recordings_root=tmp_path / "recordings")
    pipeline.start_live("files")
    run = live_runs.open_runs["files"]
    try:
        deadline = time.monotonic() + 20
        while pipeline.live_results("files")["results"] is None and time.monotonic() < deadline:
            time.sleep(0.02)
        workbook = run.out_dir / reporting.EXCEL_NAME
        assert (run.out_dir / pipeline.PREVIEW_NAME).is_file()  # the pages draw on it at once
        assert not workbook.exists()  # not after every recording: LIVE_FILES_EVERY later
        assert pipeline.results_file(run.out_dir, workbook.name).is_file()  # a download does not wait for that
    finally:
        pipeline.stop_live("files", wait=True, timeout=60)
        live_runs.open_runs.pop("files")


def test_results_are_published_after_each_recording(tmp_path, small_session, monkeypatch):
    folder_camera.open_live(monkeypatch, "steps", tmp_path / "out", "steps", small_session, gap=0.3,
                            recordings_root=tmp_path / "recordings")
    assert pipeline.live_results("steps") == {"version": 0, "results": None}
    pipeline.start_live("steps")
    seen = set()
    run = live_runs.open_runs["steps"]
    while not run.session.finished.is_set():
        results = pipeline.live_results("steps")["results"]
        if results:
            seen.add(len(results["times"]))
        time.sleep(0.01)
    pipeline.close_live("steps")
    assert seen == {1, 2, 3}


def test_labels_changed_during_a_run_show_at_once(tmp_path, small_session, live_run):
    live = live_run(small_session)
    run = live["run"]
    live_runs.open_runs[run.live_id] = run
    try:
        pipeline.save_labels(run.run_dir, {"4": "renamed"})
        pipeline.live_refresh(run.live_id)
        groups = {g["group"] for g in pipeline.live_results(run.live_id)["results"]["summary"]["groups"]}
    finally:
        live_runs.open_runs.pop(run.live_id)
    assert "renamed" in groups and "venom" not in groups
    again = reference.run_folder(run.run_dir, tmp_path / "again", pipeline.load_labels(run.run_dir))
    assert {g["group"] for g in again["results"]["summary"]["groups"]} == groups


def test_a_run_name_already_taken_is_refused(tmp_path, small_session, monkeypatch):
    (tmp_path / "recordings" / "taken").mkdir(parents=True)
    with pytest.raises(ValueError, match="already exists"):
        folder_camera.open_live(monkeypatch, "taken", tmp_path / "out", "taken", small_session,
                                recordings_root=tmp_path / "recordings")
    with pytest.raises(ValueError, match="letters"):
        folder_camera.open_live(monkeypatch, "bad", tmp_path / "out", "../escape", small_session,
                                recordings_root=tmp_path / "recordings")


def test_closing_a_run_that_recorded_nothing_leaves_no_folder(tmp_path, small_session, monkeypatch):
    folder_camera.open_live(monkeypatch, "empty", tmp_path / "out", "empty", small_session,
                            recordings_root=tmp_path / "recordings")
    assert (tmp_path / "recordings" / "empty").is_dir()
    pipeline.close_live("empty")
    assert not (tmp_path / "recordings" / "empty").exists()
    shutil.rmtree(tmp_path / "recordings")


# --- until the run starts, its name and whether it is saved can change

def test_a_run_not_started_can_be_renamed_and_takes_its_folders_along(tmp_path, small_session, monkeypatch):
    roots = {"recordings_root": tmp_path / "recordings", "results_root": tmp_path / "results"}
    (tmp_path / "recordings" / "taken").mkdir(parents=True)
    (tmp_path / "results" / "earlier").mkdir(parents=True)
    (tmp_path / "results" / "earlier" / "results.xlsx").write_bytes(b"of an earlier recording")
    status = folder_camera.open_live(monkeypatch, "rename", None, "earlier", small_session, **roots)
    try:
        pipeline.live_preview("rename")  # the label page's picture, in the results folder
        pipeline.save_labels(status["run_dir"], {"4": "renamed venom"})

        with pytest.raises(ValueError, match="already exists"):
            pipeline.set_live_options("rename", run_name="taken")
        with pytest.raises(ValueError, match="letters"):
            pipeline.set_live_options("rename", run_name="../escape")
        assert pipeline.live_status("rename")["run_name"] == "earlier"

        status = pipeline.set_live_options("rename", run_name=" hive 3 ", save_frames=False)
        assert (status["run_name"], status["save_frames"]) == ("hive 3", False)
        assert status["run_dir"] == str(tmp_path / "recordings" / "hive 3")
        assert status["out_dir"] == str(tmp_path / "results" / "hive 3")
        assert not (tmp_path / "recordings" / "earlier").exists()
        assert pipeline.load_labels(status["run_dir"]) == {"4": "renamed venom"}
        assert (tmp_path / "results" / "hive 3" / pipeline.PREVIEW_NAME).is_file()
        # results that were there before the run took the name are not the run's to remove
        assert (tmp_path / "results" / "earlier" / "results.xlsx").is_file()

        # renamed again, the results folder the run made itself goes along
        status = pipeline.set_live_options("rename", run_name="hive 4", save_frames=True)
        assert not (tmp_path / "results" / "hive 3").exists()
        assert (tmp_path / "results" / "hive 4" / pipeline.PREVIEW_NAME).is_file()

        pipeline.start_live("rename")
        assert live_runs.open_runs["rename"].session.finished.wait(60)
        with pytest.raises(ValueError, match="has started"):
            pipeline.set_live_options("rename", run_name="too late")
        assert pipeline.live_status("rename")["saved_frames"] == 3 * reference.SMALL_FRAMES
        assert (tmp_path / "results" / "hive 4" / "results.xlsx").is_file()
    finally:
        pipeline.close_live("rename")
    assert pipeline.list_recordings(**roots)[0]["name"] == "hive 4"
