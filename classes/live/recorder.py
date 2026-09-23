"""Writes the recordings of a live run to disk, the way the Discobox app does:

    <run folder>/<YYYY-MM-DD-HH-MM-SS>_fps-<fps>/<recording>_<frame id:06>.bmp

as 8-bit grey BMPs, in a thread of its own so writing never holds up the camera.
Only the frames of the recordings (the bursts) are written, never the live feed in
between. The run folder is then a session folder like any other: folder mode
reads it back and gets the live run's results exactly.

Each file is written under a temporary name and renamed once complete, so a
folder read while the run goes on (a clip on the results page) never sees half a
file.
"""

import logging
import os
import queue
import threading
from pathlib import Path

import cv2
import numpy as np

_logger = logging.getLogger(__name__)


def grey_or_colour(frame):
    """What to save of a Frame: the camera's grey frame, or a decoded frame's
    one channel when its three are identical, as for a replayed grey recording."""
    if frame.gray is not None:
        return frame.gray
    image = frame.image
    if image.ndim == 3 and np.array_equal(image[..., 0], image[..., 1]) and np.array_equal(image[..., 0], image[..., 2]):
        return image[..., 0]
    return image


class Recorder:
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.written = 0
        self.error = None
        self._queue = queue.Queue()
        self._pending = {}
        self._condition = threading.Condition()
        self._thread = threading.Thread(target=self._write_all, name="recorder", daemon=True)
        self._thread.start()

    def save(self, frame):
        with self._condition:
            name = frame.recording.name
            self._pending[name] = self._pending.get(name, 0) + 1
        self._queue.put(frame)

    def flush(self, recording_name, timeout=None):
        """Wait until every frame of the recording given so far is on disk."""
        with self._condition:
            return self._condition.wait_for(lambda: not self._pending.get(recording_name), timeout)

    def close(self):
        """Write what is left, then stop."""
        self._queue.put(None)
        self._thread.join()

    def _write_all(self):
        while True:
            frame = self._queue.get()
            if frame is None:
                return
            try:
                self._write(frame)
            except Exception as error:
                _logger.exception("Could not save %s", frame.filename)
                self.error = f"Could not save {frame.filename}: {error}"
            finally:
                with self._condition:
                    self._pending[frame.recording.name] -= 1
                    self._condition.notify_all()

    def _write(self, frame):
        folder = self.run_dir / frame.recording.name
        folder.mkdir(parents=True, exist_ok=True)
        ok, data = cv2.imencode(".bmp", grey_or_colour(frame))
        if not ok:
            raise ValueError("the frame could not be encoded")
        partial = folder / (frame.filename + ".part")
        partial.write_bytes(data.tobytes())
        os.replace(partial, folder / frame.filename)
        self.written += 1
