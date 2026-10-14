"""Entering the ground truth and the poke test of a live test run while it goes on
(pipeline.open_live_calibration / grow_live_calibration): a calibration session
on the recordings analysed so far, which grows as the run analyses more, and
whose ground truth and poke test end up with the run's folder like any folder's."""

import shutil
import time

import pytest

import folder_camera
import pipeline
import reference


def wait_for(condition, what, timeout=60):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"Timed out waiting for {what}."
        time.sleep(0.02)


@pytest.fixture
def library(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    return library


@pytest.fixture
def session(tmp_path):
    return reference.make_small_session(tmp_path / "small_session")


@pytest.fixture
def paused_run(tmp_path, monkeypatch, library, session):
    """A live run of the recordings of `session`, paused once its first one is
    analysed: the second waits."""
    folder_camera.open_live(monkeypatch, "cal", tmp_path / "out", "run", session, gap=2,
                            recordings_root=tmp_path / "recordings", library_dir=library)
    pipeline.start_live("cal")
    run = pipeline._live["cal"]
    wait_for(lambda: run.source.completed >= 1, "the first recording")
    pipeline.pause_live("cal")  # within the gap: the second recording waits for it
    wait_for(lambda: len(run.session.recordings) == 1, "the first recording's analysis")
    yield run
    pipeline.close_live("cal")


def test_the_recordings_so_far_are_opened_and_grow_with_the_run(tmp_path, library, paused_run):
    run = paused_run
    # A recording being written: no frame complete yet.
    capturing = run.run_dir / "2099-01-01-00-00-00_fps-30"
    capturing.mkdir()
    (capturing / "2099-01-01-00-00-00_fps-30_000000.bmp.part").write_bytes(b"half a frame")

    out = tmp_path / "cal"
    opened = pipeline.open_live_calibration("cal", out)
    assert opened["n_recordings"] == 1 and opened["recordings"] == list(run.session.recordings)
    mite = opened["mites"][0]["id"]
    pipeline.edit_truth(out, "set", mite=mite, recording=0, state="moving", library_dir=library)
    pipeline.save_truth(out, library)  # the library's copy leaves the frame being written for later
    copy = library / opened["dataset_id"] / pipeline.RECORDINGS_DIRNAME
    assert copy.is_dir() and not list(copy.rglob("*.part"))
    shutil.rmtree(capturing)

    pipeline.edit_truth(out, "set", mite=mite, recording=0, state="still", library_dir=library)
    pipeline.edit_poke(out, "add", 0, library_dir=library)
    pipeline.edit_poke(out, "set", 0, mite=mite, state="moved", library_dir=library)
    # Nothing comes before the run analyses it.
    assert pipeline.grow_live_calibration(out, "cal")["n_recordings"] == 1

    pipeline.resume_live("cal")
    assert run.session.finished.wait(120), "the live run did not finish"
    grown = pipeline.grow_live_calibration(out, "cal")
    assert grown["n_recordings"] == 3 == len(grown["times"]) == len(grown["recordings"])
    assert grown["truth_view"]["states"][mite] == ["still", None, None]
    assert grown["truth_view"]["unsaved"] == 1  # the change waits for "Save changes", as before
    pipeline.edit_truth(out, "dead", mite=mite, recording=2, library_dir=library)
    pipeline.save_truth(out, library)
    pipeline.edit_poke(out, "add", 2, library_dir=library)  # after a recording that came since
    pipeline.edit_poke(out, "set", 2, mite=mite, state="unmoved", library_dir=library)

    # The run's folder, opened as any folder once the run is over, has them.
    again = pipeline.open_calibration(run.run_dir, tmp_path / "again", library_dir=library)
    same = ("data_dir", "dataset_id", "times", "recordings", "zones", "mites")
    assert {key: again[key] for key in same} == {key: grown[key] for key in same}
    assert again["truth_view"]["states"] == {mite: ["still", None, "still"]}
    poke = pipeline.poke_view(tmp_path / "again", library)
    assert [(r["after"], r["states"]) for r in poke["rounds"]] == [(0, {mite: "moved"}), (2, {mite: "unmoved"})]


def test_a_run_needs_its_first_recording_analysed_and_saved(tmp_path, monkeypatch, library, session):
    roots = {"recordings_root": tmp_path / "recordings", "library_dir": library}
    folder_camera.open_live(monkeypatch, "early", tmp_path / "out", "early", session, **roots)
    with pytest.raises(ValueError, match="first recording is analysed"):
        pipeline.open_live_calibration("early", tmp_path / "cal")
    pipeline.close_live("early")

    folder_camera.open_live(monkeypatch, "unsaved", tmp_path / "out", "unsaved", session, save_frames=False, **roots)
    with pytest.raises(ValueError, match="does not save its recordings"):
        pipeline.open_live_calibration("unsaved", tmp_path / "cal")
    pipeline.close_live("unsaved")
