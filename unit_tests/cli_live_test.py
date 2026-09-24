"""The command line's live options. Folder mode's own output is checked against
the reference in folder_regression_test.py."""

import time

import pytest

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


def test_a_replay_runs_live_and_saves_a_folder_folder_mode_reads_the_same(tmp_path, small_session, recordings_root, capsys):
    out = tmp_path / "live_out"
    assert main.main(["--replay", str(small_session), "--replay-gap", "0", "--fps", "1000",
                      "--run-name", "cli run", "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Test run cli run: replay of small_session, pools of whole recording" in printed
    assert "3/3" in printed and "30 mites across 3 recordings" in printed

    folder = reference.run_folder(recordings_root / "cli run", tmp_path / "folder_out", tmp_path / "no_library")
    assert reference.outputs(out)["excel"] == folder["excel"]


def test_ctrl_c_stops_a_live_run_cleanly(tmp_path, small_session, recordings_root, monkeypatch, capsys):
    def interrupted(total):
        while not pipeline.live_status(main.LIVE_ID)["analysed"]:
            time.sleep(0.01)
        raise KeyboardInterrupt

    monkeypatch.setattr(main, "follow", interrupted)
    out = tmp_path / "live_out"
    assert main.main(["--replay", str(small_session), "--replay-gap", "5", "--run-name", "stopped", "--out-dir", str(out)]) == 0
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


def test_folder_mode_takes_a_pool_size(tmp_path, small_session, capsys):
    main.main([str(small_session), str(tmp_path / "out"), "--pool-size", "3"])
    assert "30 mites across 6 recordings" in capsys.readouterr().out  # 3 recordings of 6 frames, 2 pools each
