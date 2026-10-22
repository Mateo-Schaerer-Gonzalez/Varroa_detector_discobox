"""The command line's live options. Folder mode's own output is checked against
the reference in folder_regression_test.py."""

import time

import pytest

import folder_camera
import main
import pipeline
import reference


@pytest.fixture
def small_session(tmp_path):
    return reference.make_small_session(tmp_path / "small_session")


@pytest.fixture
def recordings_root(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "RECORDINGS_ROOT", tmp_path / "recordings")
    return tmp_path / "recordings"


@pytest.fixture
def camera(small_session, monkeypatch):
    """The command line's camera: the recordings of small_session, `gap` seconds apart."""
    def connect(gap=0.0):
        monkeypatch.setattr(pipeline.live_camera, "choose_camera", lambda camera_id: "FOLDER")
        monkeypatch.setattr(pipeline, "open_lights", lambda port: folder_camera.NoLights())
        monkeypatch.setattr(pipeline, "CameraSource",
                            lambda _id, settings, lights: folder_camera.FolderCamera(small_session, settings, lights, gap))
        # dead after longer than the run: every mite is followed to the end, as folder mode scores it
        return ["--live", "--settings", str(small_session / pipeline.SETTINGS_FILENAME), "--dead-after", "10000"]
    return connect


def test_a_live_run_saves_a_folder_folder_mode_reads_the_same(tmp_path, recordings_root, camera, capsys):
    out = tmp_path / "live_out"
    assert main.main([*camera(), "--run-name", "cli run", "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Test run cli run: Folder camera (small_session)" in printed
    assert "3/3" in printed and "30 mites across 3 recordings" in printed

    folder = reference.run_folder(recordings_root / "cli run", tmp_path / "folder_out")
    assert reference.outputs(out)["excel"] == folder["excel"]


def test_ctrl_c_stops_a_live_run_cleanly(tmp_path, recordings_root, camera, monkeypatch, capsys):
    def interrupted(total):
        while not pipeline.live_status(main.LIVE_ID)["analysed"]:
            time.sleep(0.01)
        raise KeyboardInterrupt

    monkeypatch.setattr(main, "follow", interrupted)
    out = tmp_path / "live_out"
    assert main.main([*camera(gap=30), "--run-name", "stopped", "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Stopping" in printed and "30 mites across 1 recordings" in printed
    assert (out / "results.xlsx").is_file()
    assert main.LIVE_ID not in pipeline._live  # the source is closed and forgotten


def test_a_live_run_takes_no_folder(capsys):
    with pytest.raises(SystemExit):
        main.main(["--live", "some_folder"])
    assert "takes no folder" in capsys.readouterr().err


def test_without_vimba_x_listing_cameras_says_why(monkeypatch, capsys):
    def no_vimba():
        raise pipeline.live_camera.CameraError("Vimba X could not start")

    monkeypatch.setattr(pipeline.live_camera, "print_cameras", no_vimba)
    assert main.main(["--list-cameras"]) == 1
    assert "Vimba X could not start" in capsys.readouterr().err

