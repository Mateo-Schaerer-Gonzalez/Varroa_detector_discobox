"""Recordings kept as each mite's surroundings, not as whole frames.

A live run saves, next to its settings and labels:

    first_frame.png            the first frame of the first recording, whole:
                               the mites are found on it, the zones labelled on it
    rois/index.json            the image's size, each mite's box and the region
                               kept around it (its ROI), and per recording its
                               name, frame rate, number of frames and the blobs
                               on its first and last frame
    rois/mite_000.mkv ...      per mite, its ROI in every frame of every
                               recording, one recording after the other: one
                               continuous lossless (FFV1) grey video
    rois/parts/<recording>/    during a run: the ROIs of each recording since the
                               last stitch, one short video per mite

A video can't be added to once written, nor safely read while it is, so each
recording is written as its own short videos (under a temporary name, renamed
once complete) and stitch() patches them onto the end of each mite's video once
the run is over. Whatever stops it half way, the session reads the same: the
index says how many recordings the mite videos hold (`stitched`), and the rest
are read from their parts.

A frame is given back as the whole image it was cut from with only the ROIs in
it, black around them. Every step that scores a mite reads only its box grown by
the metric's pad and by STABILIZE_MARGIN (the plate's shift and the stabilizer's
reach), which the ROI holds: the scores are those of the whole frames, exactly.

Whole frames are what an older recording folder holds (DataLoader). open_recordings()
reads either kind.
"""

import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from classes.data_loader import DataLoader
from classes.workers import side_by_side

ROI_DIRNAME = "rois"
INDEX_NAME = "index.json"
PARTS_DIRNAME = "parts"
FIRST_FRAME_NAME = "first_frame.png"
VERSION = 1
# Pixels kept around each mite's box: the largest metric pad (16) and the
# reach of plate stabilization beyond it (pipeline.STABILIZE_MARGIN, 16).
ROI_MARGIN = 32
# Pixels kept around each mite's centre, at least: a mite's clip on the pages
# (pipeline.MITE_CLIP_REACH).
CENTRE_REACH = 40
_FOURCC = cv2.VideoWriter_fourcc(*"FFV1")  # lossless, every frame on its own


def is_roi_session(data_dir):
    return (Path(data_dir) / ROI_DIRNAME / INDEX_NAME).is_file()


def open_recordings(data_dir):
    """The reader of the recordings in `data_dir`: RoiRecordings for a session
    saved as ROIs, else DataLoader (a folder of whole frames per recording)."""
    return RoiRecordings(data_dir) if is_roi_session(data_dir) else DataLoader(data_dir)


def roi_rect(box, width, height, margin=ROI_MARGIN):
    """[x1, y1, x2, y2]: the region kept of a mite of box (x1, y1, x2, y2) in an
    image of `width` x `height`: the box grown by `margin`, and at least
    CENTRE_REACH round its centre, inside the image. Its width and height are
    even, as the video's encoder wants them."""
    x1, y1, x2, y2 = (int(value) for value in box)
    cx, cy = int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2))
    rect = [max(0, min(x1 - margin, cx - CENTRE_REACH)), max(0, min(y1 - margin, cy - CENTRE_REACH)),
            min(width, max(x2 + margin, cx + CENTRE_REACH)), min(height, max(y2 + margin, cy + CENTRE_REACH))]
    for low, high, size in ((0, 2, width), (1, 3, height)):
        if (rect[high] - rect[low]) % 2:
            if rect[high] < size:
                rect[high] += 1
            elif rect[low] > 0:
                rect[low] -= 1
            else:
                rect[high] -= 1  # the whole image, of an odd size: one line less
    return rect


def remove_tree(path, ignore_errors=False):
    """shutil.rmtree(), read-only files and folders too (OneDrive marks folders
    so); nothing when `path` is not there. With `ignore_errors`, what cannot
    be removed even so (a file a reader has open, on Windows) stays."""
    def again(remove, failed, _error):
        try:
            os.chmod(failed, stat.S_IWRITE)
            remove(failed)
        except OSError:
            if not ignore_errors:
                raise

    if Path(path).exists():
        shutil.rmtree(path, onexc=again)


def _replace(partial, path):
    """os.replace(), again for a moment while Windows refuses it: a reader has
    the file open."""
    for attempt in range(40):
        try:
            os.replace(partial, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05)


def _write_json(path, data):
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(data), encoding="utf-8")
    _replace(partial, path)


class RoiVideo:
    """One mite's ROI over frames: an FFV1 grey video, lossless."""

    @staticmethod
    def writer(path, width, height, fps):
        writer = cv2.VideoWriter(str(path), cv2.CAP_FFMPEG, _FOURCC, float(fps), (int(width), int(height)),
                                 [cv2.VIDEOWRITER_PROP_IS_COLOR, 0])
        if not writer.isOpened():
            raise OSError(f"Could not write the video {path}: this OpenCV has no FFV1 encoder.")
        return writer

    @staticmethod
    def frames(path, start=0, count=None):
        """Frames `start` to `start + count` of the video, (h, w) uint8 each, one
        at a time; every frame on with no `count`."""
        capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        try:
            if not capture.isOpened():
                raise FileNotFoundError(f"Could not read the video {path}")
            if start:
                capture.set(cv2.CAP_PROP_POS_FRAMES, start)
            given = 0
            while count is None or given < count:
                ok, frame = capture.read()
                if not ok:
                    break
                given += 1
                yield np.ascontiguousarray(frame[:, :, 0]) if frame.ndim == 3 else frame  # grey, decoded as three equal channels
        finally:
            capture.release()
        if count is not None and given < count:
            raise ValueError(f"{path} holds {start + given} frames, not the {start + count} its index says.")

    @classmethod
    def read(cls, path, start=0, count=None):
        """(n, h, w) uint8: frames() as one stack."""
        frames = list(cls.frames(path, start, count))
        return np.stack(frames) if frames else np.empty((0, 0, 0), dtype=np.uint8)

    @classmethod
    def check_codec(cls, folder):
        """Raise unless a video written in `folder` reads back exactly, so a run
        never saves frames it can't give back. The video is written in a folder
        of its own there, removed after; a virus scanner holding it a moment
        longer only leaves it behind."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        frames = np.random.default_rng(0).integers(0, 256, (3, 6, 8), dtype=np.uint8)
        with tempfile.TemporaryDirectory(prefix="codec_check_", dir=folder, ignore_cleanup_errors=True) as check:
            path = Path(check) / "check.mkv"
            try:
                writer = cls.writer(path, 8, 6, 10)
                for frame in frames:
                    writer.write(frame)
                writer.release()
                same = np.array_equal(cls.read(path), frames)
            except (OSError, ValueError) as error:
                raise RuntimeError(f"The frames cannot be saved: {error}") from error
        if not same:
            raise RuntimeError("The frames cannot be saved: this OpenCV's FFV1 videos do not read back exactly.")


class RoiWriter:
    """Writes a session as ROIs, recording by recording (see the top of this file).
    Not thread safe: the live run's RoiRecorder calls it from its own thread."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.rois_dir = self.data_dir / ROI_DIRNAME
        self.index = None
        self._recording = None  # the recording being written, its writers, frames so far
        self._writers = []
        self._frames = 0

    @property
    def started(self):
        return self.index is not None

    def start(self, first_image, boxes):
        """Begin with the first frame, whole, and the boxes of the mites found on
        it ((x1, y1, x2, y2), in the order they were found)."""
        height, width = first_image.shape[:2]
        self.rois_dir.mkdir(parents=True, exist_ok=True)
        partial = self.data_dir / f"partial_{FIRST_FRAME_NAME}"
        if not cv2.imwrite(str(partial), first_image):
            raise OSError(f"Could not write {partial}")
        _replace(partial, self.data_dir / FIRST_FRAME_NAME)
        self.index = {
            "version": VERSION,
            "image": [int(width), int(height)],
            "margin": ROI_MARGIN,
            "mites": [{"box": [int(v) for v in box], "roi": roi_rect(box, width, height)} for box in boxes],
            "recordings": [],
            "stitched": 0,
        }
        _write_json(self.rois_dir / INDEX_NAME, self.index)

    def add(self, recording, image):
        """One more frame of `recording` (a frame_source.Recording); its ROIs are
        cut and written at once."""
        if self._recording != recording:
            self.abandon()
            folder = self._part_dir(recording.name, writing=True)
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
            self._writers = [RoiVideo.writer(folder / _video_name(number), x2 - x1, y2 - y1, recording.fps)
                             for number, (x1, y1, x2, y2) in enumerate(mite["roi"] for mite in self.index["mites"])]
            self._recording, self._frames = recording, 0
        for writer, mite in zip(self._writers, self.index["mites"]):
            x1, y1, x2, y2 = mite["roi"]
            writer.write(np.ascontiguousarray(image[y1:y2, x1:x2]))
        self._frames += 1

    def end(self, recording, blobs=None):
        """`recording` is complete: its videos take their name, and the index
        lists it, with `blobs`, those on its first and last frame."""
        if self._recording != recording:
            return
        for writer in self._writers:
            writer.release()
        folder = self._part_dir(recording.name)
        shutil.rmtree(folder, ignore_errors=True)
        _replace(self._part_dir(recording.name, writing=True), folder)
        self.index["recordings"].append({"name": recording.name, "fps": recording.fps, "frames": self._frames,
                                         "blobs": blobs})
        _write_json(self.rois_dir / INDEX_NAME, self.index)
        self._recording, self._writers, self._frames = None, [], 0

    def abandon(self):
        """Drop the recording being written, unfinished."""
        if self._recording is None:
            return
        for writer in self._writers:
            writer.release()
        shutil.rmtree(self._part_dir(self._recording.name, writing=True), ignore_errors=True)
        self._recording, self._writers, self._frames = None, [], 0

    def _part_dir(self, name, writing=False):
        return self.rois_dir / PARTS_DIRNAME / (f"{name}.part" if writing else name)


def _video_name(number):
    return f"mite_{number:03d}.mkv"


class RoiRecordings:
    """Reads a session saved as ROIs, as DataLoader reads a folder of whole frames:
    the same methods, giving the same frames, black away from the mites."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.rois_dir = self.data_dir / ROI_DIRNAME
        self.index = json.loads((self.rois_dir / INDEX_NAME).read_text(encoding="utf-8"))
        settings_path = self.data_dir / ".settings.txt"
        self.settings = DataLoader._parse_settings_file(settings_path) if settings_path.exists() else {}
        self._recordings = {recording["name"]: number for number, recording in enumerate(self.index["recordings"])}

    # What DataLoader gives too.

    @property
    def recording_names(self):
        return [recording["name"] for recording in self.index["recordings"]]

    def count_recordings(self):
        return len(self.index["recordings"])

    def get_settings(self, name):
        return dict(self.settings)

    def get_fps(self, name):
        return self._recording(name)["fps"]

    def get_start_time(self, name):
        return DataLoader.parse_start_time(name)

    def count_frames(self, name):
        return self._recording(name)["frames"]

    def load_preview_frame(self):
        image = cv2.imread(str(self.data_dir / FIRST_FRAME_NAME), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise FileNotFoundError(f"Could not read {self.data_dir / FIRST_FRAME_NAME}")
        return image

    def load_recording_region(self, name, x1, y1, x2, y2, step=1):
        """Every `step`-th frame of one recording, cut to (x1, y1)-(x2, y2) inside
        the image: the ROIs that reach into it, black elsewhere."""
        width, height = self.index["image"]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
        n = len(range(0, self.count_frames(name), step))
        out = np.zeros((n, max(0, y2 - y1), max(0, x2 - x1)), dtype=np.uint8)
        numbers = [number for number, mite in enumerate(self.index["mites"]) if _overlap(mite["roi"], (x1, y1, x2, y2))]
        for number, frames in zip(numbers, side_by_side(lambda number: self.read_mite(name, number)[::step], numbers)):
            rx1, ry1, rx2, ry2 = self.index["mites"][number]["roi"]
            ox1, oy1, ox2, oy2 = max(rx1, x1), max(ry1, y1), min(rx2, x2), min(ry2, y2)
            out[:, oy1 - y1:oy2 - y1, ox1 - x1:ox2 - x1] = frames[:, oy1 - ry1:oy2 - ry1, ox1 - rx1:ox2 - rx1]
        return out

    def load_recording(self, name):
        width, height = self.index["image"]
        return self.load_recording_region(name, 0, 0, width, height)

    # What only a session of ROIs has.

    @property
    def image_size(self):
        return tuple(self.index["image"])

    @property
    def boxes(self):
        """The mites' boxes (x1, y1, x2, y2), in the order they were found."""
        return [tuple(mite["box"]) for mite in self.index["mites"]]

    @property
    def rois(self):
        return [tuple(mite["roi"]) for mite in self.index["mites"]]

    def blobs(self):
        """Recording name to the blobs on its first and last frame, as the analysis
        found them on the whole frames (MotionAnalysis.blobs); None where not."""
        return {recording["name"]: recording.get("blobs") for recording in self.index["recordings"]}

    def covers(self, x1, y1, x2, y2):
        """Whether one ROI holds all of (x1, y1)-(x2, y2), inside the image."""
        width, height = self.index["image"]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
        return any(rx1 <= x1 and ry1 <= y1 and x2 <= rx2 and y2 <= ry2 for rx1, ry1, rx2, ry2 in self.rois)

    def check_margin(self, margin):
        """Raise if the mites are to be read `margin` pixels round their boxes,
        beyond what was kept."""
        if margin > self.index["margin"]:
            raise ValueError(f"Only {self.index['margin']} pixels round each mite were saved, and the "
                             f"analysis reads {margin}: lower the metric's pad.")

    def read_mite(self, name, number):
        """(frames, h, w): mite `number`'s ROI in every frame of one recording."""
        return RoiVideo.read(*self._where(name, number))

    def _where(self, name, number):
        """(video, first frame, frames) of mite `number` in recording `name`."""
        at = self._recordings[name]
        recording = self.index["recordings"][at]
        if at < self.index["stitched"]:
            start = sum(r["frames"] for r in self.index["recordings"][:at])
            return self.rois_dir / _video_name(number), start, recording["frames"]
        return self.rois_dir / PARTS_DIRNAME / name / _video_name(number), 0, recording["frames"]

    def files(self):
        """What tells these frames from any others, without reading them (as
        FolderSource.frame_files() for whole frames): per recording, its name and
        number of frames, and the mites' ROIs. Saved frames are never written
        again, only moved into the mite videos, which changes none of them."""
        return [["rois", self.rois]] + [[recording["name"], recording["frames"]] for recording in self.index["recordings"]]

    def stitch(self):
        """Patch every recording since the last stitch onto the end of each mite's
        video, then remove their parts (see the top of this file). Not while a
        recording is being added."""
        recordings = self.index["recordings"]
        stitched = self.index["stitched"]
        if stitched < len(recordings):
            work = self.rois_dir / "stitching"
            remove_tree(work)
            work.mkdir()
            kept = sum(recording["frames"] for recording in recordings[:stitched])

            def one(number):
                x1, y1, x2, y2 = self.index["mites"][number]["roi"]
                writer = RoiVideo.writer(work / _video_name(number), x2 - x1, y2 - y1, recordings[0]["fps"])
                try:
                    pieces = [(self.rois_dir / _video_name(number), 0, kept)] if kept else []
                    pieces += [self._where(recording["name"], number) for recording in recordings[stitched:]]
                    for piece in pieces:  # a frame at a time: a long run's video does not fit in memory
                        for frame in RoiVideo.frames(*piece):
                            writer.write(frame)
                finally:
                    writer.release()

            side_by_side(one, range(len(self.index["mites"])))
            # The videos first: until the index says so, only their first
            # `stitched` recordings are read, which they hold as before.
            for number in range(len(self.index["mites"])):
                _replace(work / _video_name(number), self.rois_dir / _video_name(number))
            remove_tree(work, ignore_errors=True)
            self.index["stitched"] = len(recordings)
            _write_json(self.rois_dir / INDEX_NAME, self.index)
        for recording in recordings:  # a part a reader still has open goes at the next stitch
            remove_tree(self.rois_dir / PARTS_DIRNAME / recording["name"], ignore_errors=True)
        parts = self.rois_dir / PARTS_DIRNAME
        if parts.is_dir() and not any(parts.iterdir()):
            remove_tree(parts, ignore_errors=True)

    def _recording(self, name):
        if name not in self._recordings:
            raise FileNotFoundError(f"No recording {name} in {self.data_dir}")
        return self.index["recordings"][self._recordings[name]]


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
