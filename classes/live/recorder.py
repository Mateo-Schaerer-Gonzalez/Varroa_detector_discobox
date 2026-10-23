"""Saves the recordings of a live run: only what the analysis reads of them, each
mite's surroundings (its ROI), as one continuous lossless video per mite, and
the first frame whole (classes/storage/roi_recordings.py). In a thread of its own, so
saving never holds up the camera. Only the frames of the recordings (the bursts)
are saved, never the live feed in between. The run folder is then a session like
any other: folder mode reads it back and gets the live run's results exactly.

The mites are those the analysis finds on the first frame, so the analysis tells
the recorder about them (start()) before the first frame is saved, and where it
follows each of them in each recording (place(): their boxes, those added, and
None for those no longer followed) before its first frame, and the blobs
it finds on each recording's whole first and last frame (end_recording()),
which are not saved.

Each recording is saved under a temporary name and renamed once complete, so a
session read while the run goes on (a mite's clip, the ground truth) never sees
half a recording. Once the run is over (close()), the recordings are stitched
into each mite's video.
"""

import logging
import queue
import threading

from classes.storage.frame_source import Frame
from classes.storage.roi_recordings import RoiRecordings, RoiWriter

_logger = logging.getLogger(__name__)


class Recorder:
    def __init__(self, run_dir):
        self.writer = RoiWriter(run_dir)
        self.written = 0
        self.error = None
        self.started = False  # given the mites
        self._queue = queue.Queue()
        self._pending = {}
        self._condition = threading.Condition()
        self._thread = threading.Thread(target=self._write_all, name="recorder", daemon=True)
        self._thread.start()

    @property
    def run_dir(self):
        return self.writer.data_dir

    def start(self, first_image, boxes, follow=False):
        """The first frame, whole, and the boxes (x1, y1, x2, y2) of the mites
        found on it, whose ROIs are saved from here on. With `follow`, each
        recording is placed (place()) before its first frame."""
        self._queue.put(("start", first_image, [tuple(box) for box in boxes], follow))
        self.started = True

    def place(self, boxes):
        """Where each mite is in the recording about to begin (RoiWriter.place())."""
        self._queue.put(("place", [None if box is None else tuple(box) for box in boxes]))

    def save(self, frame):
        with self._condition:
            name = frame.recording.name
            self._pending[name] = self._pending.get(name, 0) + 1
        self._queue.put(frame)

    def end_recording(self, recording, blobs=None):
        """Every frame of `recording` was given: it is complete, with `blobs`."""
        with self._condition:
            self._pending[recording.name] = self._pending.get(recording.name, 0) + 1
        self._queue.put(("end", recording, blobs))

    def flush(self, recording_name, timeout=None):
        """Wait until the recording, as far as it was given, is saved."""
        with self._condition:
            return self._condition.wait_for(lambda: not self._pending.get(recording_name), timeout)

    def close(self):
        """Save what is left, stitch the recordings into each mite's video, then stop."""
        self._queue.put(None)
        self._thread.join()

    def _write_all(self):
        while True:
            item = self._queue.get()
            if item is None:
                self._finish()
                return
            name = item.recording.name if isinstance(item, Frame) else item[1].name if item[0] == "end" else None
            try:
                self._write(item)
            except Exception as error:
                what = item.filename if isinstance(item, Frame) else name or "the first frame"
                _logger.exception("Could not save %s", what)
                self.error = f"Could not save {what}: {error}"
            finally:
                if name is not None:
                    with self._condition:
                        self._pending[name] -= 1
                        self._condition.notify_all()

    def _write(self, item):
        if isinstance(item, Frame):
            if not self.writer.started:
                raise RuntimeError("the mites were not given before the first frame")
            self.writer.add(item.recording, item.image)
            self.written += 1
        elif item[0] == "start":
            self.writer.start(item[1], item[2], item[3])
        elif item[0] == "place":
            self.writer.place(item[1])
        elif item[0] == "end":
            self.writer.end(item[1], item[2])

    def _finish(self):
        try:
            self.writer.abandon()  # a recording never ended: the analysis failed
            if self.writer.started:
                RoiRecordings(self.writer.data_dir).stitch()
        except Exception as error:
            _logger.exception("Could not stitch the recordings")
            self.error = f"Could not stitch the recordings: {error}"
