"""Entering the ground truth and the poke test of a live test run while it goes on
(pipeline.open_live_calibration / grow_live_calibration): a calibration session
on the recordings analysed so far, which grows as the run analyses more, and
whose ground truth and poke test end up with the run's folder like any folder's."""

import time

import pytest

import folder_camera
import pipeline
from pipeline import preview_images
from pipeline.live import live_runs
import reference


def wait_for(condition, what, timeout=60):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"Timed out waiting for {what}."
        time.sleep(0.02)


@pytest.fixture
def session(tmp_path):
    return reference.make_small_session(tmp_path / "small_session")


@pytest.fixture
def paused_run(tmp_path, monkeypatch, session):
    """A live run of the recordings of `session`, paused once its first one is
    analysed: the second waits."""
    folder_camera.open_live(monkeypatch, "cal", tmp_path / "out", "run", session, gap=2,
                            recordings_root=tmp_path / "recordings")
    pipeline.start_live("cal")
    run = live_runs.open_runs["cal"]
    wait_for(lambda: run.source.completed >= 1, "the first recording")
    pipeline.pause_live("cal")  # within the gap: the second recording waits for it
    wait_for(lambda: len(run.session.recordings) == 1, "the first recording's analysis")
    yield run
    pipeline.close_live("cal")


def test_the_recordings_so_far_are_opened_and_grow_with_the_run(tmp_path, paused_run):
    run = paused_run
    out = tmp_path / "cal"
    opened = pipeline.open_live_calibration("cal", out)
    assert opened["n_recordings"] == 1 and opened["recordings"] == list(run.session.recordings)
    mite = opened["mites"][0]["id"]
    pipeline.edit_truth(out, "set", mite=mite, recording=0, state="moving")
    pipeline.save_truth(out)
    assert (run.run_dir / pipeline.GROUND_TRUTH_FILENAME).is_file()  # kept with the run's recordings

    pipeline.edit_truth(out, "set", mite=mite, recording=0, state="still")
    pipeline.edit_poke(out, "add", 0)
    pipeline.edit_poke(out, "set", 0, mite=mite, state="moved")
    # Nothing comes before the run analyses it.
    assert pipeline.grow_live_calibration(out, "cal")["n_recordings"] == 1

    pipeline.resume_live("cal")
    assert run.session.finished.wait(120), "the live run did not finish"
    grown = pipeline.grow_live_calibration(out, "cal")
    assert grown["n_recordings"] == 3 == len(grown["times"]) == len(grown["recordings"])
    assert grown["truth_view"]["states"][mite] == ["still", None, None]
    assert grown["truth_view"]["unsaved"] == 1  # the change waits for its save, as before
    pipeline.edit_truth(out, "dead", mite=mite, recording=2)
    pipeline.save_truth(out)
    pipeline.edit_poke(out, "add", 2)  # after a recording that came since
    pipeline.edit_poke(out, "set", 2, mite=mite, state="unmoved")

    # The run's folder, opened as any folder once the run is over, has them.
    again = pipeline.open_calibration(run.run_dir, tmp_path / "again")
    same = ("data_dir", "dataset_id", "times", "recordings", "zones", "mites")
    assert {key: again[key] for key in same} == {key: grown[key] for key in same}
    assert again["truth_view"]["states"] == {mite: ["still", None, "still"]}
    poke = pipeline.poke_view(tmp_path / "again")
    assert [(r["after"], r["states"]) for r in poke["rounds"]] == [(0, {mite: "moved"}), (2, {mite: "unmoved"})]


def test_a_run_needs_its_first_recording_analysed_and_saved(tmp_path, monkeypatch, session):
    roots = {"recordings_root": tmp_path / "recordings"}
    folder_camera.open_live(monkeypatch, "early", tmp_path / "out", "early", session, **roots)
    with pytest.raises(ValueError, match="first recording is analysed"):
        pipeline.open_live_calibration("early", tmp_path / "cal")
    pipeline.close_live("early")

    folder_camera.open_live(monkeypatch, "unsaved", tmp_path / "out", "unsaved", session, save_frames=False, **roots)
    with pytest.raises(ValueError, match="does not save its recordings"):
        pipeline.open_live_calibration("unsaved", tmp_path / "cal")
    pipeline.close_live("unsaved")


def test_from_the_recording_mites_were_added_in_the_plate_is_drawn_from_the_frame_they_were_found_on(tmp_path):
    data_dir, out_dir = tmp_path / "run", tmp_path / "out"
    (data_dir / pipeline.ADDED_FRAMES_DIRNAME).mkdir(parents=True)
    out_dir.mkdir()
    for start in (2, 4, 9):  # the one added in recording 9 is not in the 5 recordings analysed yet
        (data_dir / pipeline.ADDED_FRAMES_DIRNAME / f"from_{start}.jpg").write_bytes(b"jpeg %d" % start)
    previews = preview_images.added_previews(data_dir, out_dir, 5)
    first = pipeline.PREVIEW_NAME
    assert previews == [first, first, "preview_from_2.jpg", "preview_from_2.jpg", "preview_from_4.jpg"]
    assert (out_dir / "preview_from_4.jpg").read_bytes() == b"jpeg 4" and not (out_dir / "preview_from_9.jpg").exists()
    assert preview_images.added_previews(tmp_path / "folder", out_dir, 3) == [first] * 3  # no mites added


def test_the_results_of_a_run_that_added_mites_draw_each_recording_on_the_frame_they_were_found_on(tmp_path):
    from types import SimpleNamespace
    data_dir, out_dir = tmp_path / "run", tmp_path / "results"
    (data_dir / pipeline.ADDED_FRAMES_DIRNAME).mkdir(parents=True)
    (data_dir / pipeline.ADDED_FRAMES_DIRNAME / "from_1.jpg").write_bytes(b"first")
    run = SimpleNamespace(frames="rois", data_dir=data_dir, n_recordings=3)
    previews = preview_images.added_previews(run.data_dir, out_dir, run.n_recordings, again=False)
    assert previews == [pipeline.PREVIEW_NAME, "preview_from_1.jpg", "preview_from_1.jpg"]
    # in the run's own results, a copy already there stays
    (out_dir / "preview_from_1.jpg").write_bytes(b"kept")
    preview_images.added_previews(run.data_dir, out_dir, run.n_recordings, again=False)
    assert (out_dir / "preview_from_1.jpg").read_bytes() == b"kept"
