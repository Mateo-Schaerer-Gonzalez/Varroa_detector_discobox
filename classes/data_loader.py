import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from classes import settings_file

# An 8-bit BMP's grey palette: entry i is (i, i, i, 0), so its pixels are the grey levels.
_GREY_PALETTE = bytes(value for level in range(256) for value in (level, level, level, 0))


def _bmp_region(path, x1, y1, x2, y2):
    """The grey pixels [y1:y2, x1:x2] (cut off at the image's edge) of an 8-bit
    uncompressed BMP with a grey palette, as the Discobox saves its frames,
    read straight off the file: only the region's rows, nothing decoded. None
    for any other file."""
    with open(path, "rb") as f:
        head = f.read(54)
        if len(head) < 54 or head[:2] != b"BM":
            return None
        number = lambda start, signed=False: int.from_bytes(head[start:start + 4], "little", signed=signed)  # noqa: E731
        offset, info, width, height = number(10), number(14), number(18, True), number(22, True)
        bits, compression = int.from_bytes(head[28:30], "little"), number(30)
        if bits != 8 or compression != 0 or info < 40 or width <= 0 or height == 0 or (number(46) or 256) != 256:
            return None
        f.seek(14 + info)
        if f.read(1024) != _GREY_PALETTE:
            return None
        rows, stride = abs(height), (width + 3) & ~3
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(rows, y2)
        if x2 <= x1 or y2 <= y1:
            return np.empty((max(0, y2 - y1), max(0, x2 - x1)), dtype=np.uint8)
        f.seek(offset + (y1 if height < 0 else rows - y2) * stride)  # rows are stored bottom-up, unless the height is negative
        data = f.read((y2 - y1) * stride)
    if len(data) < (y2 - y1) * stride:
        return None  # cut short: let the decoder say so
    block = np.frombuffer(data, dtype=np.uint8).reshape(y2 - y1, stride)
    return np.ascontiguousarray((block if height < 0 else block[::-1])[:, x1:x2])


class DataLoader:
    # Recording folder names look like "2025-09-04-09-28-17_fps-30" or
    # "2025-09-04_15-25-04_fps-30" (date and time separated by "-" or "_").
    TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[-_](\d{2}-\d{2}-\d{2})_fps-(\d+)")

    def __init__(self, data_dir, grayscale=True):
        self.data_dir = Path(data_dir)
        self.grayscale = grayscale
        self.settings = settings_file.of_folder(self.data_dir)

    @property
    def recording_dirs(self):
        dirs = [d for d in self.data_dir.iterdir() if d.is_dir() and self.TIMESTAMP_RE.match(d.name)]
        return sorted(dirs, key=lambda d: d.name)

    @property
    def recording_names(self):
        return [d.name for d in self.recording_dirs]

    def covers(self, x1, y1, x2, y2):
        """Whether the frames hold all of (x1, y1)-(x2, y2): whole frames always do
        (see RoiRecordings.covers())."""
        return True

    def get_settings(self, name):
        """Session-level settings, overridden by the recording's own .settings.txt if present."""
        return {**self.settings, **settings_file.of_folder(self.data_dir / name)}

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
        return self.parse_start_time(name)

    @classmethod
    def parse_start_time(cls, name):
        """Wall-clock time a recording started, parsed from its folder name."""
        match = cls.TIMESTAMP_RE.match(name)
        if not match:
            raise ValueError(f"Could not parse timestamp from recording name: {name}")
        date_str, time_str, _ = match.groups()
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H-%M-%S")

    def frame_paths(self, name):
        """The frame files of one recording, in the order they are read: by name."""
        paths = sorted((self.data_dir / name).glob("*.bmp"))
        if not paths:
            raise FileNotFoundError(f"No .bmp images found in {self.data_dir / name}")
        return paths

    def _imread(self, path):
        return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE if self.grayscale else cv2.IMREAD_COLOR)

    def load_recording(self, name):
        with ThreadPoolExecutor() as executor:
            return np.stack(list(executor.map(self._imread, self.frame_paths(name))), axis=0)

    def count_frames(self, name):
        """Number of frames in one recording."""
        return len(list((self.data_dir / name).glob("*.bmp")))

    def load_recording_region(self, name, x1, y1, x2, y2, step=1):
        """Every `step`-th frame of one recording, cropped to (x1, y1)-(x2, y2).

        Crops each frame as soon as it is read, so looking at one plate of one
        recording never holds a whole recording of full frames in memory. In
        grey, a frame saved as the Discobox saves them is not even decoded: the
        region is read straight off its file (read_region()).
        """
        def read(path):
            if self.grayscale:
                return self.read_region(path, x1, y1, x2, y2)
            return _cut(self._imread(path), x1, y1, x2, y2)

        with ThreadPoolExecutor() as executor:
            return np.stack(list(executor.map(read, self.frame_paths(name)[::step])), axis=0)

    @staticmethod
    def read_image(path):
        """One frame file in grey, as cv2.imread(path, cv2.IMREAD_GRAYSCALE) decodes it."""
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"Could not read the image {path}")
        return image

    @classmethod
    def read_region(cls, path, x1, y1, x2, y2):
        """The grey pixels [y1:y2, x1:x2] of one frame file, cut off at the
        image's edge, exactly as cv2.imread(path, cv2.IMREAD_GRAYSCALE) gives
        them: read straight off an 8-bit grey BMP (a fraction of a
        millisecond, against several to decode the whole frame), any other
        file decoded and cut."""
        region = _bmp_region(path, x1, y1, x2, y2)
        if region is not None:
            return region
        return _cut(cls.read_image(path), x1, y1, x2, y2)

    def load_preview_frame(self):
        """Decode only the first image of the first recording, to find the mites
        on and to draw the plates."""
        dirs = self.recording_dirs
        if not dirs:
            raise FileNotFoundError(f"No recordings found in {self.data_dir}")
        return self._imread(self.frame_paths(dirs[0].name)[0])

    def count_recordings(self):
        """Number of recording bursts in this session."""
        return len(self.recording_dirs)


def _cut(frame, x1, y1, x2, y2):
    """A copy of [y1:y2, x1:x2] of `frame`, cut off at its edge."""
    height, width = frame.shape[:2]
    return frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)].copy()
