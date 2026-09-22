import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


class DataLoader:
    # Recording folder names look like "2025-09-04-09-28-17_fps-30" or
    # "2025-09-04_15-25-04_fps-30" (date and time separated by "-" or "_").
    TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[-_](\d{2}-\d{2}-\d{2})_fps-(\d+)")

    def __init__(self, data_dir, grayscale=True):
        self.data_dir = Path(data_dir)
        self.grayscale = grayscale

        settings_path = self.data_dir / ".settings.txt"
        self.settings = self._parse_settings_file(settings_path) if settings_path.exists() else {}

    @staticmethod
    def _parse_settings_file(path):
        settings = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            try:
                settings[key] = int(value)
            except ValueError:
                settings[key] = value
        return settings

    @property
    def recording_dirs(self):
        dirs = [d for d in self.data_dir.iterdir() if d.is_dir() and self.TIMESTAMP_RE.match(d.name)]
        return sorted(dirs, key=lambda d: d.name)

    def get_settings(self, name):
        """Session-level settings, overridden by the recording's own .settings.txt if present."""
        merged = dict(self.settings)
        recording_settings_path = self.data_dir / name / ".settings.txt"
        if recording_settings_path.exists():
            merged.update(self._parse_settings_file(recording_settings_path))
        return merged

    def get_fps(self, name):
        settings = self.get_settings(name)
        if "fps" in settings:
            return settings["fps"]
        match = re.search(r"_fps-(\d+)", name)
        if match:
            return int(match.group(1))
        raise ValueError(f"Could not determine fps for recording '{name}'")

    def get_start_time(self, name):
        """Wall-clock time the recording started, parsed from its folder name."""
        match = self.TIMESTAMP_RE.match(name)
        if not match:
            raise ValueError(f"Could not parse timestamp from recording name: {name}")
        date_str, time_str, _ = match.groups()
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H-%M-%S")

    def load_recording(self, name):
        recording_dir = self.data_dir / name
        image_paths = sorted(recording_dir.glob("*.bmp"))
        if not image_paths:
            raise FileNotFoundError(f"No .bmp images found in {recording_dir}")
        flag = cv2.IMREAD_GRAYSCALE if self.grayscale else cv2.IMREAD_COLOR
        with ThreadPoolExecutor() as executor:
            frames = list(executor.map(lambda p: cv2.imread(str(p), flag), image_paths))
        return np.stack(frames, axis=0)

    def count_frames(self, name):
        """Number of frames in one recording."""
        return len(list((self.data_dir / name).glob("*.bmp")))

    def load_recording_region(self, name, x1, y1, x2, y2, step=1):
        """Every `step`-th frame of one recording, cropped to (x1, y1)-(x2, y2).

        Crops each frame as soon as it is read, so looking at one plate of one
        recording never holds a whole recording of full frames in memory.
        """
        image_paths = sorted((self.data_dir / name).glob("*.bmp"))[::step]
        if not image_paths:
            raise FileNotFoundError(f"No .bmp images found in {self.data_dir / name}")
        flag = cv2.IMREAD_GRAYSCALE if self.grayscale else cv2.IMREAD_COLOR

        def read(path):
            frame = cv2.imread(str(path), flag)
            height, width = frame.shape[:2]
            return frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)].copy()

        with ThreadPoolExecutor() as executor:
            return np.stack(list(executor.map(read, image_paths)), axis=0)

    def load_all(self):
        return {d.name: self.load_recording(d.name) for d in self.recording_dirs}

    def load_folder(self):
        """Stack every recording's frames and compute each frame's wall-clock time
        (in seconds, relative to the first frame of the first recording)."""
        dirs = self.recording_dirs
        if not dirs:
            raise FileNotFoundError(f"No recordings found in {self.data_dir}")

        base_time = self.get_start_time(dirs[0].name)
        frame_chunks = []
        time_chunks = []
        for d in dirs:
            frames = self.load_recording(d.name)
            fps = self.get_fps(d.name)
            offset = (self.get_start_time(d.name) - base_time).total_seconds()
            time_chunks.append(offset + np.arange(frames.shape[0]) / fps)
            frame_chunks.append(frames)

        self.frames = np.concatenate(frame_chunks, axis=0)
        self.times = np.concatenate(time_chunks, axis=0)

        return self.frames, self.times

    def load_bursts(self):
        """Split the concatenated frames/times from load_folder back into a list of
        (frames, times) tuples, one per recording burst, in recording order."""
        if not hasattr(self, "frames"):
            self.load_folder()

        bursts = []
        start = 0
        for d in self.recording_dirs:
            n = len(list(d.glob("*.bmp")))
            end = start + n
            bursts.append((self.frames[start:end], self.times[start:end]))
            start = end
        return bursts

    def load_preview_frame(self):
        """Decode only the first image of the first recording.

        `get_first_frame` decodes every frame in the session to return one of them,
        which is far too expensive just to draw a preview for zone labelling.
        """
        dirs = self.recording_dirs
        if not dirs:
            raise FileNotFoundError(f"No recordings found in {self.data_dir}")

        image_paths = sorted(dirs[0].glob("*.bmp"))
        if not image_paths:
            raise FileNotFoundError(f"No .bmp images found in {dirs[0]}")

        flag = cv2.IMREAD_GRAYSCALE if self.grayscale else cv2.IMREAD_COLOR
        return cv2.imread(str(image_paths[0]), flag)

    def count_recordings(self):
        """Number of recording bursts in this session."""
        return len(self.recording_dirs)

    def get_first_frame(self):
        """Returns the first frame of the first recording burst."""
        if not hasattr(self, "frames"):
            self.load_folder()
        return self.frames[0]

    def get_times(self):
        return self.times
