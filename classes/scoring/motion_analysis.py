"""The analysis core: find the mites on the first frame, then score each mite in
each recording, from all of its frames, whatever the frames come from.

Folder mode runs it over every recording of a folder at once. Live mode runs it as
the recordings are captured and reads its state in between (under its own lock: this class
takes none). It knows nothing about files, cameras or threads -- except that the
mite id counter is shared by the whole process, so detections are serialised by
DETECTION_LOCK and two of them never number their mites into each other.

A live run does three things more, recording by recording, all decided when a
recording begins (its first frame), before any of its frames is scored or saved:

- it follows the mites (`follow`): every mite is moved to the blob the detector
  finds nearest it on the recording's first frame, in its own zone and at most
  `follow` pixels away; a mite with no such blob stays where it was. Within a
  recording its box stays put, as the score needs.
- it adds the mites given with add_mites() since the last recording, numbered
  after those of their zone.
- it no longer follows the mites stop() was given: counted dead, they are
  neither scored nor saved from then on.

A recording in which a mite is not followed records nothing on it
(Mite.record_absence()). A saved live run (RoiSource) gives back where each mite
was in each recording (`placements`) and when it was added (`starts`), so
analysing it again follows the mites exactly as the live run did.
"""

import threading
from contextlib import contextmanager, nullcontext

import numpy as np

from classes.scoring.analyzer import Analyzer
from classes.storage.frame_source import Frame, frame_times, recordings
from classes.plate.mite import Mite
from classes.plate.zones import mite_ids

DETECTION_LOCK = threading.Lock()
# Pixels: a blob nearer than this to a mite's centre leaves its box where it is;
# the detector finds the same mite a pixel or so off from one frame to the next.
FOLLOW_MIN_SHIFT = 2


def detect_mites(zone_manager, image, analyzer, boxes=None):
    """Find the mites on one frame and put each in its zone, which numbers them
    ("<zone id>.<number>", in reading order: ZoneManager.number_mites()).
    Returns the frame masked to the plates, which is what the detection saw.
    With `boxes`, (x1, y1, x2, y2) each, those are the mites: the ones found
    when the frames were saved as their ROIs, the only ones they hold."""
    with DETECTION_LOCK:
        Mite.reset_ids()
        masked = zone_manager.mask_image_to_valid_rois(image)
        mites = analyzer.detect(masked) if boxes is None else [Mite(*box, config=analyzer.config) for box in boxes]
        zone_manager.assign_mites(mites)
    return masked


@contextmanager
def _placed(mites, boxes):
    """The mites' boxes moved to `boxes` while the block runs, back where they
    were found after."""
    homes = [tuple(mite) for mite in mites]
    for mite, box in zip(mites, boxes):
        mite.x1, mite.y1, mite.x2, mite.y2 = box
    try:
        yield
    finally:
        for mite, box in zip(mites, homes):
            mite.x1, mite.y1, mite.x2, mite.y2 = box


class MotionAnalysis:
    """Detection on the first frame of the stream, then one motion score per mite
    per recording.

    `recording_times` holds each recording's time: seconds from the start of the
    first recording to its own. `mites` is every mite, in the order found and
    then added: the order of a saved run's mite videos.
    """

    def __init__(self, zone_manager, analyzer=None, score=True, boxes=None, known_blobs=None,
                 follow=None, starts=None, placements=None):
        """`boxes` and `known_blobs`, of frames saved as the mites' ROIs (a
        RoiSource's): the mites found then, and per recording name the blobs
        then found on its whole first and last frame, which are not saved.
        With them, `starts` is the recording each mite was added in (0 for
        those found on the first frame) and `placements(name)` gives each
        mite's box in that recording, None where it was not followed (or None
        for a recording that says nothing: every mite where it was found).
        `follow`: the most a mite's box moves from one recording to the next,
        in pixels, as a live run follows the mites; None: they stay put."""
        self.zone_manager = zone_manager
        self.analyzer = analyzer or Analyzer()
        self.score = score
        self.boxes = boxes
        self.known_blobs = known_blobs
        self.follow = follow
        self.starts = starts
        self.placements = placements
        self.first_frame = None
        self.masked = None
        self.mites = []
        self.recording_times = []
        # Per recording: {mite: box} of the mites followed in it.
        self.placed = []
        # Per recording: the blobs on its first and last frame (Analyzer.blobs()),
        # to tell where the mites are (classes/scoring/unusual_activity.py).
        self.blobs = []
        self.activity = None  # the UnusualActivity of the mites, once arranged
        self._session_start = None
        self._zone_mites = {}
        self._zone_of = {}       # id(mite) -> its zone
        self._pending = []       # boxes given to add_mites(), added when the next recording begins
        self._later = []         # (start, box): the saved mites added after the first recording
        self._begun = None       # the recording begun last

    @property
    def started(self):
        return self.first_frame is not None

    def restart(self, score=True):
        """Go through the stream again from its first recording, the mites
        already found: e.g. to score what was first only counted."""
        self.score = score
        self.recording_times = []
        self.placed = []
        self.blobs = []
        self._begun = None

    def run(self, events, lock=None):
        """Analyse a stream of Frames and RecordingEnds. With `lock`, it is held
        while the detection and each recording change this object's state, so
        another thread holding it reads a consistent state."""
        lock = lock or nullcontext()
        for frames in recordings(self._watch(events, lock)):
            with lock:
                self.add_recording(frames)
            # Let the recording's frames go now: kept until the loop takes the
            # next one, they would be held while that one is captured.
            del frames

    def _watch(self, events, lock):
        # The mites are found on the first frame of the stream, and placed on
        # the first frame of each recording, before its recording is complete.
        for event in events:
            if isinstance(event, Frame) and event.recording != self._begun:
                with lock:
                    self.begin(event)
            yield event

    def detect(self, frame):
        """Find the mites on `frame`, the first of the session."""
        self.first_frame = frame.image
        self._session_start = frame.recording.start
        boxes = self.boxes
        if boxes is not None and self.starts is not None:
            self._later = sorted(((start, box) for start, box in zip(self.starts, boxes) if start > 0),
                                 key=lambda item: item[0])
            boxes = [box for start, box in zip(self.starts, boxes) if start == 0]
        self.masked = detect_mites(self.zone_manager, frame.image, self.analyzer, boxes)
        self.mites = self.zone_manager.mites
        self._zone_mites = {id(zone): list(zone.mites) for zone in self.zone_manager.zones}
        self._zone_of = {id(mite): zone for zone in self.zone_manager.zones for mite in zone.mites}

    def begin(self, frame):
        """The first frame of a recording: the mites due are added, and those
        followed in it placed. Once per recording."""
        if frame.recording == self._begun:
            return
        self._begun = frame.recording
        if not self.started:
            self.detect(frame)
        number = len(self.recording_times)
        due = []
        while self._later and self._later[0][0] <= number:
            due.append(self._later.pop(0)[1])
        pending, self._pending = self._pending, []
        self._add_all(due + pending, number)
        self.placed.append(self._place(frame, number))

    def add_recording(self, frames):
        """Score the mites over `frames`, every frame of one recording."""
        self.begin(frames[0])
        if self.score:
            placed = self.placed[len(self.recording_times)]
            followed = [mite for mite in self.mites if mite in placed]
            with _placed(followed, [placed[mite] for mite in followed]):
                self.analyzer.score_pool(followed, [frame.image for frame in frames])
            for mite in self.mites:
                if mite not in placed:
                    mite.record_absence()
            if self.known_blobs is not None:
                self.blobs.append(self.known_blobs.get(frames[0].recording.name) or [])
            else:
                self.blobs.append(self.blobs_on(frames[0].image, frames[-1].image))
        self.recording_times.append(frame_times(frames[:1], self._session_start)[0])

    # --- what a live run changes as it goes

    def add_mites(self, boxes):
        """Mites to follow from the next recording on: (x1, y1, x2, y2) each,
        found while the run goes on. One outside every zone is left out."""
        self._pending.extend(tuple(int(value) for value in box) for box in boxes)

    def stop(self, mites, recording):
        """No longer follow `mites` from recording `recording` on: they count as dead."""
        for mite in mites:
            if mite.stopped is None:
                mite.stopped = max(recording, mite.start)

    def boxes_of(self, mite):
        """Per recording: the box the mite was scored in, None where it was not followed."""
        return [placed.get(mite) for placed in self.placed]

    def _add_all(self, boxes, number):
        """The mites of `boxes` added when recording `number` begins, in that
        order (a saved run's index has them so). Those of a zone are numbered
        after its mites in reading order, as the first frame's are
        (ZoneManager.number_mites()): left to right, line by line."""
        added = [mite for mite in (self._add(box, number) for box in boxes) if mite is not None]
        for zone in self.zone_manager.zones:
            new = [mite for mite in added if self._zone_of[id(mite)] is zone]
            for mite, text in mite_ids(new, zone.id, len(self._zone_mites.get(id(zone), [])) - len(new)):
                mite.text = text

    def _add(self, box, number):
        """A mite added when recording `number` begins, after the mites of its
        zone (numbered by _add_all()); None when it is in no zone."""
        with DETECTION_LOCK:
            mite = Mite(*box, config=self.analyzer.config)
        zone = self.zone_manager.zone_of(mite)
        if zone is None:
            return None
        mite.start = number
        self._zone_mites.setdefault(id(zone), []).append(mite)
        zone.add_mite(mite)
        self._zone_of[id(mite)] = zone
        self.mites.append(mite)
        if self.score:
            for _recording in range(number):
                mite.record_absence()
        return mite

    def _place(self, frame, number):
        """{mite: box} of the mites followed in recording `number`, `frame` its first."""
        if self.placements is not None:
            boxes = self.placements(frame.recording.name)
            if boxes is not None:
                for mite, box in zip(self.mites, boxes):
                    if box is None and mite.start <= number:
                        self.stop([mite], number)  # no longer followed when it was saved: counted dead then
                return {mite: tuple(box) for mite, box in zip(self.mites, boxes) if box is not None}
        last = self.placed[-1] if self.placed else {}
        there = [mite for mite in self.mites if mite.start <= number]
        boxes = {mite: last.get(mite, tuple(mite)) for mite in there}
        if self.follow and number > 0 and frame.image is not None:
            boxes = self._followed(frame.image, boxes)
        return {mite: box for mite, box in boxes.items() if mite.followed_in(number)}

    def _followed(self, image, boxes):
        """`boxes` ({mite: box}) moved to the blobs on `image`: each to the
        nearest in its zone at most `follow` px away, nearest pairs first; a
        mite no longer followed takes its blob too, but stays put."""
        blobs = np.asarray(self.analyzer.blobs(self.zone_manager.mask_image_to_valid_rois(image)), dtype=float).reshape(-1, 2)
        mites = list(boxes)
        pairs = []
        for m, mite in enumerate(mites):
            x1, y1, x2, y2 = boxes[mite]
            centre = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
            zone = self._zone_of.get(id(mite))
            for b, blob in enumerate(blobs):
                distance = float(np.hypot(*(blob - centre)))
                if distance <= self.follow and (zone is None or zone.contains_point(*blob)):
                    pairs.append((distance, m, b))
        moved, taken = {}, set()
        for distance, m, b in sorted(pairs):
            mite = mites[m]
            if mite in moved or b in taken:
                continue
            taken.add(b)
            moved[mite] = boxes[mite]
            if distance >= FOLLOW_MIN_SHIFT and mite.stopped is None:
                x1, y1, x2, y2 = boxes[mite]
                dx = int(round(blobs[b][0] - (x1 + x2) / 2))
                dy = int(round(blobs[b][1] - (y1 + y2) / 2))
                moved[mite] = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
        return {mite: moved.get(mite, box) for mite, box in boxes.items()}

    # ---

    def blobs_on(self, *images):
        """The blobs on `images` (a recording's first and last frame), those of
        the later one within 1 px of one of the earlier left out."""
        found = []
        for image in images:
            for blob in self.analyzer.blobs(self.zone_manager.mask_image_to_valid_rois(image)):
                if all(abs(blob[0] - x) > 1 or abs(blob[1] - y) > 1 for x, y in found):
                    found.append(blob)
        return found

    def zone_mites(self, zone):
        """Every mite detected in `zone`, the ones left out too."""
        return list(self._zone_mites.get(id(zone), []))

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
