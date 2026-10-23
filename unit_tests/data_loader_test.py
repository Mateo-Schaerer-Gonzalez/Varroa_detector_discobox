import cv2
import numpy as np
import pytest

from classes.storage.data_loader import DataLoader

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


@pytest.mark.parametrize("width", [64, 63, 61])  # rows padded to 4 bytes but at 64
def test_a_region_of_a_grey_bmp_is_what_imread_cuts(tmp_path, width):
    frame = np.random.default_rng(width).integers(0, 256, (37, width), dtype=np.uint8)
    path = tmp_path / "frame.bmp"
    cv2.imwrite(str(path), frame)
    for x1, y1, x2, y2 in [(0, 0, width, 37), (5, 3, 20, 30), (-4, -6, 9, 7), (50, 30, 80, 60), (10, 10, 10, 20)]:
        expected = frame[max(0, y1):min(37, y2), max(0, x1):min(width, x2)]
        got = DataLoader.read_region(path, x1, y1, x2, y2)
        assert got.shape == expected.shape and np.array_equal(got, expected)


def test_a_region_of_any_other_image_is_decoded_and_cut(tmp_path):
    frame = np.random.default_rng(1).integers(0, 256, (20, 30), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame.png"), frame)
    cv2.imwrite(str(tmp_path / "colour.bmp"), cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
    for name in ("frame.png", "colour.bmp"):
        assert np.array_equal(DataLoader.read_region(tmp_path / name, 3, 4, 13, 19), frame[4:19, 3:13])
