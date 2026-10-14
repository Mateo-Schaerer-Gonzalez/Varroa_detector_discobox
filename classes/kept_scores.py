"""The scores of a run, kept with its results, so that analysing the same
recordings again reads them back instead of decoding and scoring every frame
again: to go on checking calls another day, or after the labels changed.

A score follows from the frames, from where the mites are, from the metric and
its parameters, from whether the plate is stabilised, and from the code and the
libraries that score. All of that goes into one key (KeptScores.key()), and the
scores are only read back under the very key they were kept under; anything
else, a frame replaced or a line of the scoring code changed, and the run scores
again. The frames are told apart by their names, sizes and times of writing, and
the first of them by its pixels.

Nothing but the scores, with what was measured with them (each mite's activity
and each recording's blobs, see classes/unusual_activity.py), is kept: the
mites are found again on the first frame, the times read from the recordings'
names, and the calls made from the scores with the threshold in use. The file is in a folder of its own beside the
results, kept/, as it is none of them, and can be deleted at any time.
"""

import hashlib
import inspect
import json
from pathlib import Path

import cv2
import numpy as np

from classes import analyzer, frame_source, mite, mite_look, motion_analysis, plate_stabilizer, rect, workers

# Whatever could change a score, were it changed.
_SCORING = (analyzer, plate_stabilizer, mite_look, motion_analysis, frame_source, mite, rect, workers)


class KeptScores:
    DIRNAME = "kept"
    FILENAME = "scores.json"

    def __init__(self, folder):
        self.path = Path(folder) / self.DIRNAME / self.FILENAME
        self.blobs = []  # per recording, as kept: what give() read back

    @staticmethod
    def key(mites, stabilize, frames, first_frame):
        """The key of the scores of `mites` (Mite objects, as detected, in
        order) over `frames` ([(recording, [(file, size, time written), ...]),
        ...], see FolderSource.frame_files()), the first of which decodes to
        `first_frame`."""
        code = "".join(inspect.getsource(module) for module in _SCORING)
        described = {
            "code": hashlib.sha1(code.encode("utf-8")).hexdigest(),
            "libraries": [cv2.__version__, np.__version__],
            "mites": [[list(m), m.metric, analyzer.Analyzer.check_metric_params(m.metric, m.metric_params)] for m in mites],
            "stabilize": bool(stabilize),
            "frames": frames,
            "first_frame": hashlib.sha1(np.ascontiguousarray(first_frame).tobytes()).hexdigest(),
        }
        return hashlib.sha1(json.dumps(described, sort_keys=True).encode("utf-8")).hexdigest()

    def give(self, key, mites, n_recordings):
        """Record on `mites` the scores kept under `key`, recording by recording,
        as scoring them would have; False, and nothing recorded, when there are
        none under that key for that many mites and recordings."""
        try:
            kept = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(kept, dict) or kept.get("key") != key:
            return False
        scores, brightness, activity = kept.get("scores"), kept.get("brightness"), kept.get("activity")
        blobs = kept.get("blobs")
        if not (isinstance(scores, list) and isinstance(brightness, list) and isinstance(activity, list)
                and len(scores) == len(brightness) == len(activity) == len(mites)
                and all(isinstance(values, list) and len(values) == n_recordings for values in (*scores, *brightness, *activity))
                and isinstance(blobs, list) and len(blobs) in (0, n_recordings)):
            return False
        for one, its_scores, its_brightness, its_activity in zip(mites, scores, brightness, activity):
            for score, bright, seen in zip(its_scores, its_brightness, its_activity):
                one.record_motion(score, brightness=bright, activity=seen)
        self.blobs = blobs
        return True

    def keep(self, key, mites, blobs=()):
        """Keep the scores recorded on `mites` under `key`, with their activity
        and the blobs of each recording. Never fails a run: the scores are only
        kept to save time."""
        kept = {"key": key, "scores": [list(m.motion_scores) for m in mites], "brightness": [list(m.brightness) for m in mites],
                "activity": [list(m.activity) for m in mites], "blobs": list(blobs)}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_name(self.path.name + ".part")
            partial.write_text(json.dumps(kept), encoding="utf-8")  # floats are written so that they read back the same
            partial.replace(self.path)
        except (OSError, TypeError, ValueError):
            pass
