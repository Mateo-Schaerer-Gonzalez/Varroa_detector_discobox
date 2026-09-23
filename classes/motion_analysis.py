"""The analysis core: find the mites on the first frame, then score each mite in
each pool of frames, pool by pool, whatever the frames come from.

Folder mode runs it over every pool of a folder at once. Live mode runs it as the
pools are captured and reads its state in between (under its own lock: this class
takes none). It knows nothing about files, cameras or threads -- except that the
mite id counter is shared by the whole process, so detections are serialised by
DETECTION_LOCK and two of them never number their mites into each other.
"""

import threading
from contextlib import nullcontext

from classes.analyzer import Analyzer
from classes.frame_source import Frame, frame_times
from classes.mite import Mite
from classes.pooling import pools

DETECTION_LOCK = threading.Lock()


def detect_mites(zone_manager, image, analyzer):
    """Find the mites on one frame, numbered from 0, and put each in its zone.
    Returns the frame masked to the plates, which is what the detection saw."""
    with DETECTION_LOCK:
        Mite.reset_ids()
        masked = zone_manager.mask_image_to_valid_rois(image)
        zone_manager.assign_mites(analyzer.detect(masked))
    return masked


class MotionAnalysis:
    """Detection on the first frame of the stream, then one motion score per mite
    per pool.

    `pool_times` holds each pool's time: seconds from the start of the first
    recording to the pool's first frame. `pool_frames` holds, per pool, its
    recording's name, the index of its first frame and its number of frames.
    """

    def __init__(self, zone_manager, analyzer=None, score=True):
        self.zone_manager = zone_manager
        self.analyzer = analyzer or Analyzer()
        self.score = score
        self.first_frame = None
        self.masked = None
        self.mites = []
        self.pool_times = []
        self.pool_frames = []
        self._session_start = None
        self._zone_mites = {}

    @property
    def started(self):
        return self.first_frame is not None

    def run(self, events, pool_size=None, on_pool=None, lock=None):
        """Analyse a stream of Frames and RecordingEnds, calling `on_pool(pool)`
        after each pool is scored. With `lock`, it is held while the detection
        and each pool change this object's state, so another thread holding it
        reads a consistent state."""
        lock = lock or nullcontext()
        for pool in pools(self._watch(events, lock), pool_size):
            with lock:
                self.add_pool(pool)
            if on_pool is not None:
                on_pool(pool)

    def _watch(self, events, lock):
        # The mites are found on the first frame of the stream, before any pool is
        # complete, so a pool size never changes which frame that is.
        for event in events:
            if not self.started and isinstance(event, Frame):
                with lock:
                    self._detect(event)
            yield event

    def _detect(self, frame):
        self.first_frame = frame.image
        self._session_start = frame.recording.start
        self.masked = detect_mites(self.zone_manager, frame.image, self.analyzer)
        self.mites = [mite for zone in self.zone_manager.zones for mite in zone.mites]
        self._zone_mites = {id(zone): list(zone.mites) for zone in self.zone_manager.zones}

    def add_pool(self, pool):
        if not self.started:
            self._detect(pool.frames[0])
        if self.score:
            self.analyzer.score_pool(self.mites, [frame.image for frame in pool.frames])
        self.pool_times.append(frame_times(pool.frames[:1], self._session_start)[0])
        self.pool_frames.append((pool.recording.name, pool.first_index, len(pool.frames)))

    def arrange(self, labels=None, reject=None):
        """Put every mite detected back in its zone, name the zones by `labels`
        (zone id -> group), then leave out the mites `reject(zone_manager)`
        returns. Returns the mites that remain.

        Can be called again whenever the labels or the rejections change: nothing
        is lost, since scores stay on the mites."""
        for zone in self.zone_manager.zones:
            zone.mites = list(self._zone_mites.get(id(zone), []))
        for zone in self.zone_manager.valid_zones:
            zone.label = None
        self.zone_manager.apply_labels(labels)
        return self.zone_manager.remove_mites(reject(self.zone_manager) if reject else [])
