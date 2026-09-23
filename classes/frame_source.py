"""Where frames come from, as one stream the analysis reads the same way whatever
the source.

A source yields, recording by recording, each frame (a Frame) and then the end of
its recording (a RecordingEnd). A recording is one burst of frames, e.g. the
folder "2025-09-04-09-28-17_fps-30"; the analysis never needs to know whether it
was read from disk, replayed or is arriving from the camera right now.

Every frame is an (H, W, 3) uint8 image exactly as cv2.imread(path,
cv2.IMREAD_COLOR) decodes a saved recording frame, so the scores of a live frame
and of the same frame read back from disk are identical. A grey camera frame gets
its three identical channels from as_analysis_image().

FolderSource reads a recording folder the way folder mode always has. The live
sources (the camera, and ReplaySource, which replays a folder as if it were the
camera) are in classes/live/.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from classes.data_loader import DataLoader


@dataclass(frozen=True)
class Recording:
    """One burst of frames: its folder name, when it started, and its frame rate."""

    name: str
    start: datetime
    fps: float

    @classmethod
    def from_folder(cls, loader, name):
        return cls(name=name, start=loader.get_start_time(name), fps=loader.get_fps(name))

    @classmethod
    def from_name(cls, name, fps):
        """A recording being captured now: its start is read from its name, as
        folder mode will read it from the folder's name later."""
        return cls(name=name, start=DataLoader.parse_start_time(name), fps=fps)


@dataclass(frozen=True, eq=False)
class Frame:
    """One frame of a recording.

    `index` is its position in the recording in the order folder mode reads the
    recording's files (sorted by name), and `filename` the name it has, or is
    saved under, in the recording's folder. `gray` is the camera's own
    single-channel frame, when the frame comes from the camera.
    """

    recording: Recording
    index: int
    filename: str
    image: np.ndarray = field(repr=False)
    gray: np.ndarray = field(default=None, repr=False)


@dataclass(frozen=True)
class RecordingEnd:
    """No more frames of `recording` will come."""

    recording: Recording


def as_analysis_image(frame):
    """A frame as the analysis reads it: (H, W, 3) uint8. A grey (H, W) frame
    becomes three identical channels, which is exactly what cv2.imread() with
    IMREAD_COLOR gives for the same frame saved as an 8-bit grey BMP."""
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return frame


def frame_times(frames, session_start):
    """Seconds from `session_start` (the start of the first recording) of each
    frame: its recording's start plus its index over the frame rate."""
    return [(frame.recording.start - session_start).total_seconds() + frame.index / frame.recording.fps for frame in frames]


class FolderSource:
    """The recordings of a session folder, in name order, each frame decoded as
    folder mode always has (cv2.IMREAD_COLOR, files sorted by name).

    One recording is decoded at a time, in parallel, so the session is never held
    in memory as a whole.
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.loader = DataLoader(self.data_dir, grayscale=False)

    def recordings(self):
        return [Recording.from_folder(self.loader, d.name) for d in self.loader.recording_dirs]

    def events(self, decode=True):
        """The stream of Frames and RecordingEnds. With `decode` False the Frames
        carry no image: enough to know which frames make which pool."""
        recordings = self.recordings()
        if not recordings:
            raise FileNotFoundError(f"No recordings found in {self.data_dir}")
        with ThreadPoolExecutor() as executor:
            for recording in recordings:
                paths = sorted((self.data_dir / recording.name).glob("*.bmp"))
                if not paths:
                    raise FileNotFoundError(f"No .bmp images found in {self.data_dir / recording.name}")
                read = (lambda path: cv2.imread(str(path), cv2.IMREAD_COLOR)) if decode else (lambda path: None)
                for index, (path, image) in enumerate(zip(paths, executor.map(read, paths))):
                    if decode and image is None:
                        raise ValueError(f"Could not read the image {path}")
                    yield Frame(recording, index, path.name, image)
                yield RecordingEnd(recording)
