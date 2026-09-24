"""A live run must give exactly what folder mode gives on the frames it saved.

Each run here replays a recorded folder through the whole live pipeline (source,
pools, the analysis core, the recorder, the published results), then runs folder
mode on the run's folder and compares everything: the results the pages are drawn
from, the workbook, what each figure draws and the images' pixels. The first test
also compares the live run with the reference made before live input existed.
"""

import json
import shutil
import time

import pytest

import pipeline
import reference


def replay(tmp_path, data_dir, name="run", **kwargs):
    """Replay `data_dir` as a live run as fast as it goes; the run's parts once it
    has finished, and the figures it drew last."""
    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    options = {"replay_fps": 100_000, "replay_gap": 0, **kwargs}
    live_id = f"test-{name}"
    with reference.capture_figures() as figures:
        pipeline.open_live(live_id, tmp_path / f"{name}_out", name, source="replay", replay_dir=data_dir,
                           recordings_root=tmp_path / "recordings", library_dir=library, **options)
        pipeline.start_live(live_id)
        run = pipeline._live[live_id]
        assert run.session.finished.wait(120), "the live run did not finish"
    status = pipeline.live_status(live_id)
    results = pipeline.live_results(live_id)["results"]
    pipeline._live.pop(live_id)  # keep its folder, which close_live() would remove if empty
    return {"run": run, "status": status, "results": reference.plain(results), "figures": figures,
            "library": library, **reference.outputs(run.out_dir)}


def folder(tmp_path, run, **kwargs):
    """Folder mode on a live run's folder, as the command line or the page runs it."""
    return reference.run_folder(run.run_dir, tmp_path / "folder_out", run.library_dir,
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
def test_a_replayed_live_run_gives_folder_mode_results_and_the_reference(tmp_path):
    if any((reference.SAMPLE_DATA / name).exists() for name in ("labels.json", "ground_truth.json")):
        pytest.skip("sample_data holds labels or ground truth the reference was made without.")
    live = replay(tmp_path, reference.SAMPLE_DATA)
    assert live["status"]["state"] == "finished" and live["status"]["error"] is None
    assert live["status"]["saved_frames"] == 180

    assert_live_equals_folder(live, folder(tmp_path, live["run"]))

    expected = reference.load("folder_sample_data")
    assert_same(expected["results"], live["results"], "The live results, against the reference,")
    assert_same(expected["excel"], live["excel"], "The live results.xlsx, against the reference,")
    assert_same(expected["figures"], live["figures"], "The live figures, against the reference,")


@pytest.fixture
def small_session(tmp_path):
    """A few frames of sample_data, labelled, with one detection marked not a mite."""
    session = reference.make_small_session(tmp_path / "small_session")
    labels = {"1": "control", "4": "control", "10": "venom"}  # zones with mites
    (session / "labels.json").write_text(json.dumps(labels))
    mite = next(m for m in reference.load("folder_sample_data")["results"]["mites"] if m["id"] == reference.REJECTED_MITE)
    (session / "ground_truth.json").write_text(json.dumps([{"x": mite["x"], "y": mite["y"], "truth": ["not_a_mite"]}]))
    return session


def test_labels_and_not_a_mite_marks_apply_live_as_in_folder_mode(tmp_path, small_session):
    live = replay(tmp_path, small_session)
    assert {g["group"] for g in live["results"]["summary"]["groups"]} >= {"control", "venom"}
    assert reference.REJECTED_MITE not in {m["id"] for m in live["results"]["mites"]}
    assert_live_equals_folder(live, folder(tmp_path, live["run"]))


def test_a_pool_size_pools_live_as_in_folder_mode(tmp_path, small_session):
    live = replay(tmp_path, small_session, pool_size=4)
    assert live["results"]["n_recordings"] == 3  # 6 frames per recording: one pool of 4, 2 left over
    assert_live_equals_folder(live, folder(tmp_path, live["run"], pool_size=4))


def test_without_saving_frames_the_results_are_the_same(tmp_path, small_session):
    live = replay(tmp_path, small_session, save_frames=False)
    assert not any(path.suffix == ".bmp" for path in live["run"].run_dir.rglob("*"))
    original = reference.run_folder(small_session, tmp_path / "original_out", live["library"],
                                    pipeline.load_labels(small_session))
    assert_same(original["results"], live["results"], "The live results")


def test_a_run_stopped_midway_is_analysed_as_far_as_it_got(tmp_path, small_session):
    library = tmp_path / "library"
    library.mkdir()
    pipeline.open_live("stop", tmp_path / "out", "stopped", source="replay", replay_dir=small_session,
                       replay_fps=40, replay_gap=0.5, recordings_root=tmp_path / "recordings", library_dir=library)
    pipeline.start_live("stop")
    run = pipeline._live["stop"]
    deadline = time.monotonic() + 20
    while pipeline.live_status("stop")["completed"] < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.1)  # into the gap or the second recording
    pipeline.stop_live("stop", wait=True, timeout=60)
    status = pipeline.live_status("stop")
    pipeline._live.pop("stop")
    assert status["state"] == "finished" and 1 <= status["analysed"] < 3
    live = reference.plain(run.session.results)
    again = folder(tmp_path, run)
    assert_same(again["results"], live, "The results of the stopped run")


def test_results_are_published_after_each_recording(tmp_path, small_session):
    library = tmp_path / "library"
    library.mkdir()
    pipeline.open_live("steps", tmp_path / "out", "steps", source="replay", replay_dir=small_session,
                       replay_fps=100_000, replay_gap=0.3, recordings_root=tmp_path / "recordings", library_dir=library)
    assert pipeline.live_results("steps") == {"version": 0, "results": None}
    pipeline.start_live("steps")
    seen = set()
    run = pipeline._live["steps"]
    while not run.session.finished.is_set():
        results = pipeline.live_results("steps")["results"]
        if results:
            seen.add(len(results["times"]))
        time.sleep(0.01)
    pipeline.close_live("steps")
    assert seen == {1, 2, 3}


def test_labels_changed_during_a_run_show_at_once(tmp_path, small_session):
    live = replay(tmp_path, small_session)
    run = live["run"]
    pipeline._live[run.live_id] = run
    try:
        pipeline.save_labels(run.run_dir, {"1": "renamed"})
        pipeline.live_refresh(run.live_id)
        groups = {g["group"] for g in pipeline.live_results(run.live_id)["results"]["summary"]["groups"]}
    finally:
        pipeline._live.pop(run.live_id)
    assert "renamed" in groups and "venom" not in groups
    again = reference.run_folder(run.run_dir, tmp_path / "again", run.library_dir, pipeline.load_labels(run.run_dir))
    assert {g["group"] for g in again["results"]["summary"]["groups"]} == groups


def test_a_run_name_already_taken_is_refused(tmp_path, small_session):
    (tmp_path / "recordings" / "taken").mkdir(parents=True)
    with pytest.raises(ValueError, match="already exists"):
        pipeline.open_live("taken", tmp_path / "out", "taken", source="replay", replay_dir=small_session,
                           recordings_root=tmp_path / "recordings")
    with pytest.raises(ValueError, match="letters"):
        pipeline.open_live("bad", tmp_path / "out", "../escape", source="replay", replay_dir=small_session,
                           recordings_root=tmp_path / "recordings")


def test_closing_a_run_that_recorded_nothing_leaves_no_folder(tmp_path, small_session):
    pipeline.open_live("empty", tmp_path / "out", "empty", source="replay", replay_dir=small_session,
                       recordings_root=tmp_path / "recordings")
    assert (tmp_path / "recordings" / "empty").is_dir()
    pipeline.close_live("empty")
    assert not (tmp_path / "recordings" / "empty").exists()
    shutil.rmtree(tmp_path / "recordings")


def test_the_status_says_how_far_a_replay_is(tmp_path, small_session):
    library = tmp_path / "library"
    library.mkdir()
    pipeline.open_live("far", tmp_path / "out", "far", source="replay", replay_dir=small_session,
                       replay_fps=100, replay_gap=0, recordings_root=tmp_path / "recordings", library_dir=library)
    assert pipeline.live_status("far")["timeline"] is None
    pipeline.start_live("far")
    assert pipeline._live["far"].session.finished.wait(60)
    line = pipeline.live_status("far")["timeline"]
    results = pipeline.live_results("far")["results"]
    pipeline.close_live("far")
    # Three recordings of 6 frames at 100 fps, back to back, all played (seconds to a tenth).
    assert line["starts"] == pytest.approx([0.0, 0.06, 0.12], abs=0.05)
    assert line["elapsed"] == line["length"] == pytest.approx(0.18, abs=0.05)
    # The results' axis is the folder's own: its recordings' times, not the replay's.
    assert results["times"][-1] <= line["minutes"] < results["times"][-1] + 0.01
