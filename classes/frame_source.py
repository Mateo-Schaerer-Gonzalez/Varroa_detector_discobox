"""Where frames come from, as one stream the analysis reads the same way whatever
the source.

A source yields, recording by recording, each frame (a Frame) and then the end of
its recording (a RecordingEnd). A recording is one burst of frames, e.g. the
folder "2025-09-04-09-28-17_fps-30"; the analysis never needs to know whether it
was read from disk or is arriving from the camera right now.

Every frame is an (H, W) uint8 grey image: the camera's frame as it comes, or
a saved recording frame as cv2.imread(path, cv2.IMREAD_GRAYSCALE) decodes it, so
the scores of a live frame and of the same frame read back from disk are
identical. The Discobox camera and its recordings are grey; a frame is held in
one channel, not three identical ones, a third of the memory.

FolderSource reads a recording folder the way folder mode always has, RoiSource
a session saved as the mites' ROIs (classes/roi_recordings.py), and
open_source() whichever `data_dir` holds. The live source, the camera, is in
classes/live/.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path

import numpy as np

from classes.data_loader import DataLoader
from classes.roi_recordings import RoiRecordings, is_roi_session
from classes.workers import one_ahead


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
    saved under, in the recording's folder. `image` is (H, W) grey.
    """

    recording: Recording
    index: int
    filename: str
    image: np.ndarray = field(repr=False)


@dataclass(frozen=True)
class RecordingEnd:
    """No more frames of `recording` will come."""

    recording: Recording


def frame_times(frames, session_start):
    """Seconds from `session_start` (the start of the first recording) of each
    frame: its recording's start plus its index over the frame rate."""
    return [(frame.recording.start - session_start).total_seconds() + frame.index / frame.recording.fps for frame in frames]


def recordings(events):
    """Group a stream of Frames and RecordingEnds into recordings: every frame of
    each, in order, as soon as it has ended.

    A stream that stops without a RecordingEnd ends its last recording there.
    """
    current = []
    for event in events:
        if isinstance(event, RecordingEnd):
            if current:
                yield current
            current = []
            continue
        if not isinstance(event, Frame):
            raise TypeError(f"Expected a Frame or a RecordingEnd, got {event!r}")
        if current and event.recording != current[0].recording:
            raise ValueError(f"A frame of {event.recording.name} came before {current[0].recording.name} ended.")
        current.append(event)
    if current:
        yield current


class _SavedSource:
    """The recordings saved in a folder, read by `loader` (a DataLoader or a
    RoiRecordings), in name order."""

    FIRST = "first"  # for events(): decode only the first frame of the stream

    def __init__(self, data_dir, loader, names=None):
        """`names`: only the recordings of these names, e.g. those of a live run
        complete so far; every recording without."""
        self.data_dir = Path(data_dir)
        self.loader = loader
        self.names = None if names is None else set(names)

    def recordings(self):
        return [Recording.from_folder(self.loader, name) for name in self.loader.recording_names
                if self.names is None or name in self.names]


class FolderSource(_SavedSource):
    """The recordings of a session folder, in name order, each frame decoded in
    grey (cv2.IMREAD_GRAYSCALE, files sorted by name).

    A recording is decoded in parallel, and the one after it while it is worked
    on, so the session is never held in memory as a whole: the recording in
    work and the next one are.
    """

    def __init__(self, data_dir, names=None):
        super().__init__(data_dir, DataLoader(data_dir), names)

    def events(self, decode=True):
        """The stream of Frames and RecordingEnds. With `decode` False the Frames
        carry no image: enough to know which frames make which recording. With
        FolderSource.FIRST only the first frame of the stream does: enough to
        find the mites as well."""
        recordings = self.recordings()
        if not recordings:
            raise FileNotFoundError(f"No recordings found in {self.data_dir}")
        if decode is True:
            with ThreadPoolExecutor() as readers:
                loads = (partial(self._load, recording, readers) for recording in recordings)
                for recording, (paths, images) in zip(recordings, one_ahead(loads)):
                    for index, (path, image) in enumerate(zip(paths, images)):
                        yield Frame(recording, index, path.name, image)
                    yield RecordingEnd(recording)
            return
        first = decode == self.FIRST
        for recording in recordings:
            for index, path in enumerate(self.loader.frame_paths(recording.name)):
                yield Frame(recording, index, path.name, DataLoader.read_image(path) if first else None)
                first = False
            yield RecordingEnd(recording)

    def frame_files(self):
        """What tells this folder's frames from any others, without reading
        them: [[recording, [[file, size, time written], ...]], ...], in the
        order events() gives them."""
        return [[recording.name, [[path.name, (stat := path.stat()).st_size, stat.st_mtime_ns]
                                  for path in self.loader.frame_paths(recording.name)]]
                for recording in self.recordings()]

    def _load(self, recording, readers):
        """A recording's frame files and their images, decoded side by side."""
        paths = self.loader.frame_paths(recording.name)
        return paths, list(readers.map(DataLoader.read_image, paths))


class RoiSource(_SavedSource):
    """The recordings of a session saved as ROIs (classes/roi_recordings.py), as
    FolderSource gives those of a folder: each frame whole, black away from the
    mites, but for the first, which was saved whole. The scores, read only
    from the ROIs, are those of the whole frames.

    The mites are those found when the frames were saved (`boxes`), with those
    a live run added and where it followed them (`starts`, `placements()`), and the
    blobs on each recording's first and last frame those found then on the
    whole frames (`blobs()`): there is nothing to find them on again.
    """

    def __init__(self, data_dir, names=None):
        super().__init__(data_dir, RoiRecordings(data_dir), names)

    @property
    def boxes(self):
        return self.loader.boxes

    @property
    def starts(self):
        """The recording each mite was added in (RoiRecordings.starts)."""
        return self.loader.starts

    def placements(self, name):
        """Where each mite was in recording `name` (RoiRecordings.placements())."""
        return self.loader.placements(name)

    def blobs(self):
        return self.loader.blobs()

    def events(self, decode=True):
        """As FolderSource.events()."""
        recordings = self.recordings()
        if not recordings:
            raise FileNotFoundError(f"No recordings found in {self.data_dir}")
        whole_first = recordings[0].name == self.loader.recording_names[0]
        if decode is True:
            loads = (partial(self.loader.load_recording, recording.name) for recording in recordings)
            for number, (recording, frames) in enumerate(zip(recordings, one_ahead(loads))):
                for index, image in enumerate(frames):
                    if number == 0 and index == 0 and whole_first:
                        image = self.loader.load_preview_frame()
                    yield Frame(recording, index, _frame_name(recording, index), image)
                yield RecordingEnd(recording)
            return
        first = decode == self.FIRST
        for recording in recordings:
            for index in range(self.loader.count_frames(recording.name)):
                image = None
                if first:
                    image = (self.loader.load_preview_frame() if whole_first
                             else self.loader.load_recording_region(recording.name, 0, 0, *self.loader.image_size)[0])
                yield Frame(recording, index, _frame_name(recording, index), image)
                first = False
            yield RecordingEnd(recording)

    def frame_files(self):
        """As FolderSource.frame_files(): what tells these frames from others (RoiRecordings.files())."""
        return [entry for entry in self.loader.files() if entry[0] == "rois" or self.names is None or entry[0] in self.names]


def _frame_name(recording, index):
    return f"{recording.name}_{index:06}"


def open_source(data_dir, names=None):
    """The source of the recordings in `data_dir`, whichever way they were saved."""
    return RoiSource(data_dir, names) if is_roi_session(data_dir) else FolderSource(data_dir, names)
