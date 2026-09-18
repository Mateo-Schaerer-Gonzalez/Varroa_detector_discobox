import cv2
import numpy as np
import pytest

from classes.data_loader import DataLoader

SETTINGS_TEXT = (
    "recording_count=12\n"
    "recording_timeout=5\n"
    "vent_time=20\n"
    "led1_time=20\n"
    "led2_time=20\n"
    "frame_count=3\n"
    "fps=30\n"
    "vent=255\n"
    "led1=255\n"
    "led2=255\n"
)


def make_session(tmp_path, recording_names=("2025-09-04_15-25-04_fps-30",), frame_count=3,
                  size=(4, 4), local_settings=None):
    (tmp_path / ".settings.txt").write_text(SETTINGS_TEXT)
    for name in recording_names:
        recording_dir = tmp_path / name
        recording_dir.mkdir()
        for i in range(frame_count):
            frame = np.full((size[0], size[1], 3), i, dtype=np.uint8)
            cv2.imwrite(str(recording_dir / f"frame_{i:04d}.bmp"), frame)
        if local_settings:
            (recording_dir / ".settings.txt").write_text(local_settings)
    # Non-recording folder that should never be picked up as a recording.
    (tmp_path / "results").mkdir()
    return tmp_path


class TestSettings:
    def test_parses_session_settings(self, tmp_path):
        root = make_session(tmp_path)
        loader = DataLoader(root)
        assert loader.settings == {
            "recording_count": 12,
            "recording_timeout": 5,
            "vent_time": 20,
            "led1_time": 20,
            "led2_time": 20,
            "frame_count": 3,
            "fps": 30,
            "vent": 255,
            "led1": 255,
            "led2": 255,
        }

    def test_missing_settings_file_yields_empty_dict(self, tmp_path):
        loader = DataLoader(tmp_path)
        assert loader.settings == {}

    def test_recording_level_settings_override_session_defaults(self, tmp_path):
        name = "2025-09-04_15-25-04_fps-30"
        root = make_session(tmp_path, recording_names=(name,), local_settings="fps=15\n")
        loader = DataLoader(root)
        settings = loader.get_settings(name)
        assert settings["fps"] == 15
        assert settings["recording_count"] == 12  # inherited from session defaults


class TestRecordingDirs:
    def test_lists_only_fps_named_folders(self, tmp_path):
        names = ("2025-09-04_15-25-04_fps-30", "2025-09-04_15-30-04_fps-30")
        root = make_session(tmp_path, recording_names=names)
        loader = DataLoader(root)
        assert [d.name for d in loader.recording_dirs] == sorted(names)


class TestLoadRecording:
    def test_stacks_frames_into_3d_array_when_grayscale(self, tmp_path):
        name = "2025-09-04_15-25-04_fps-30"
        root = make_session(tmp_path, recording_names=(name,), frame_count=3, size=(4, 6))
        loader = DataLoader(root, grayscale=True)
        frames = loader.load_recording(name)
        assert frames.shape == (3, 4, 6)

    def test_stacks_frames_into_4d_array_when_color(self, tmp_path):
        name = "2025-09-04_15-25-04_fps-30"
        root = make_session(tmp_path, recording_names=(name,), frame_count=3, size=(4, 6))
        loader = DataLoader(root, grayscale=False)
        frames = loader.load_recording(name)
        assert frames.shape == (3, 4, 6, 3)

    def test_frames_are_ordered_by_filename(self, tmp_path):
        name = "2025-09-04_15-25-04_fps-30"
        root = make_session(tmp_path, recording_names=(name,), frame_count=3, size=(2, 2))
        loader = DataLoader(root, grayscale=True)
        frames = loader.load_recording(name)
        assert [int(frame[0, 0]) for frame in frames] == [0, 1, 2]

    def test_raises_when_no_images_found(self, tmp_path):
        name = "empty_fps-30"
        (tmp_path / name).mkdir()
        (tmp_path / ".settings.txt").write_text(SETTINGS_TEXT)
        loader = DataLoader(tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load_recording(name)


class TestLoadAll:
    def test_loads_every_recording(self, tmp_path):
        names = ("2025-09-04_15-25-04_fps-30", "2025-09-04_15-30-04_fps-30")
        root = make_session(tmp_path, recording_names=names, frame_count=3, size=(4, 4))
        loader = DataLoader(root, grayscale=True)
        result = loader.load_all()
        assert set(result.keys()) == set(names)
        for frames in result.values():
            assert frames.shape == (3, 4, 4)


class TestGetFps:
    def test_falls_back_to_folder_name_fps(self, tmp_path):
        name = "2025-09-04_15-25-04_fps-30"
        (tmp_path / ".settings.txt").write_text("recording_count=12\n")  # no fps key
        (tmp_path / name).mkdir()
        for i in range(3):
            cv2.imwrite(str(tmp_path / name / f"frame_{i:04d}.bmp"), np.full((2, 2, 3), i, dtype=np.uint8))
        loader = DataLoader(tmp_path)
        assert loader.get_fps(name) == 30

    def test_settings_override_folder_name_fps(self, tmp_path):
        name = "2025-09-04_15-25-04_fps-30"
        root = make_session(tmp_path, recording_names=(name,), local_settings="fps=15\n")
        loader = DataLoader(root)
        assert loader.get_fps(name) == 15


class TestLoadFolder:
    def test_stacks_all_recordings_into_single_array(self, tmp_path):
        names = ("2025-09-04_15-25-04_fps-30", "2025-09-04_15-30-04_fps-30")
        root = make_session(tmp_path, recording_names=names, frame_count=3, size=(4, 4))
        loader = DataLoader(root, grayscale=True)
        frames, times = loader.load_folder()
        assert frames.shape == (6, 4, 4)
        assert times.shape == (6,)

    def test_times_start_at_zero_and_account_for_recording_gap(self, tmp_path):
        names = ("2025-09-04_15-25-04_fps-30", "2025-09-04_15-30-04_fps-30")
        root = make_session(tmp_path, recording_names=names, frame_count=3, size=(2, 2))
        loader = DataLoader(root, grayscale=True)
        _, times = loader.load_folder()
        assert times[0] == 0
        # Within the first recording, frames are 1/30s apart.
        assert times[1] == pytest.approx(1 / 30)
        assert times[2] == pytest.approx(2 / 30)
        # Second recording starts 5 minutes (300s) after the first.
        assert times[3] == pytest.approx(300.0)
        assert times[4] == pytest.approx(300.0 + 1 / 30)

    def test_raises_when_no_recordings_found(self, tmp_path):
        (tmp_path / ".settings.txt").write_text(SETTINGS_TEXT)
        loader = DataLoader(tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load_folder()
