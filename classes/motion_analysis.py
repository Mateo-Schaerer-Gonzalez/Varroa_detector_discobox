"""The analysis core: find the mites on the first frame, then score each mite in
each recording, from all of its frames, whatever the frames come from.

Folder mode runs it over every recording of a folder at once. Live mode runs it as
the recordings are captured and reads its state in between (under its own lock: this class
takes none). It knows nothing about files, cameras or threads -- except that the
mite id counter is shared by the whole process, so detections are serialised by
DETECTION_LOCK and two of them never number their mites into each other.
"""

import threading
from contextlib import nullcontext

from classes.analyzer import Analyzer
from classes.frame_source import Frame, frame_times, recordings
from classes.mite import Mite

DETECTION_LOCK = threading.Lock()


def detect_mites(zone_manager, image, analyzer):
    """Find the mites on one frame and put each in its zone, which numbers them
    ("<zone id>.<number>", in reading order: ZoneManager.number_mites()).
    Returns the frame masked to the plates, which is what the detection saw."""
    with DETECTION_LOCK:
        Mite.reset_ids()
        masked = zone_manager.mask_image_to_valid_rois(image)
        zone_manager.assign_mites(analyzer.detect(masked))
    return masked


class MotionAnalysis:
    """Detection on the first frame of the stream, then one motion score per mite
    per recording.

    `recording_times` holds each recording's time: seconds from the start of the
    first recording to its own.
    """

    def __init__(self, zone_manager, analyzer=None, score=True):
        self.zone_manager = zone_manager
        self.analyzer = analyzer or Analyzer()
        self.score = score
        self.first_frame = None
        self.masked = None
        self.mites = []
        self.recording_times = []
        self._session_start = None
        self._zone_mites = {}

    @property
    def started(self):
        return self.first_frame is not None

    def run(self, events, lock=None):
        """Analyse a stream of Frames and RecordingEnds. With `lock`, it is held
        while the detection and each recording change this object's state, so
        another thread holding it reads a consistent state."""
        lock = lock or nullcontext()
        for frames in recordings(self._watch(events, lock)):
            with lock:
                self.add_recording(frames)

    def _watch(self, events, lock):
        # The mites are found on the first frame of the stream, before its
        # recording is complete.
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

    def add_recording(self, frames):
        """Score the mites over `frames`, every frame of one recording."""
        if not self.started:
            self._detect(frames[0])
        if self.score:
            self.analyzer.score_pool(self.mites, [frame.image for frame in frames])
        self.recording_times.append(frame_times(frames[:1], self._session_start)[0])

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
