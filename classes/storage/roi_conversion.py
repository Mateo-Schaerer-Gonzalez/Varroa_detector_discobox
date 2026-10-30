"""Shrinks a folder of whole frames (..._fps-30/*.bmp, as the Discobox app saves
them) to what a live run saves: the mites' ROIs, the first frame whole and the
blobs on each recording's first and last frame (classes/storage/roi_recordings.py).

It is what a live run would have saved of the same frames: the mites are found
on the first frame, the blobs on the whole frames while they are still there,
and the ROIs are lossless, so the folder's results stay the same, to the last
digit. Only then are the frames deleted.

The folder is converted in place, recording by recording, and a recording's
frames go only once the index lists it. Whatever stops it half way, the folder
is a session of the recordings converted so far, beside the frames of the
others; converting it again carries on with those. Recordings added to the
folder later (the same folder dropped again, with more) are added the same way,
with the mites found at first.

Mites put on the plates after the first recording are found first, on each
recording's first frame (classes/scoring/new_mites.py, as a folder of frames is
analysed), and saved as a live run saves the mites it added: from the recording
they appear in, with their place in each recording, and that recording's first
frame (`added_frames`, which pipeline/uploads.py writes). A folder converted
before gets no new ones.
"""

import logging
from pathlib import Path

from classes.storage.data_loader import DataLoader
from classes.storage.frame_source import Frame, FolderSource
from classes.scoring.motion_analysis import DETECTION_LOCK, MotionAnalysis
from classes.scoring.new_mites import NewMites
from classes.storage.files import remove_tree
from classes.storage.roi_recordings import RoiRecordings, RoiVideo, RoiWriter, is_roi_session

_logger = logging.getLogger(__name__)


class RoiConversion:
    def __init__(self, data_dir, zone_manager, analyzer=None):
        self.data_dir = Path(data_dir)
        self.analysis = MotionAnalysis(zone_manager, analyzer, score=False)
        # recording number (in those converted) -> its first frame, of each
        # recording mites appeared in after the first
        self.added_frames = {}

    def run(self):
        """Convert the recordings of whole frames not converted yet. Returns how
        many were; 0 when there were none, or no mite to keep the frames of,
        in which case the frames stay as they are."""
        frames = DataLoader(self.data_dir).recording_names
        saved = RoiRecordings(self.data_dir).recording_names if is_roi_session(self.data_dir) else []
        self._remove_frames([name for name in frames if name in saved])  # converted before something stopped it
        todo = [name for name in frames if name not in saved]
        if not todo:
            return 0
        if saved and todo[0] < saved[-1]:
            raise ValueError(f"{todo[0]} is older than the recordings of {self.data_dir} already shrunk to the "
                             "mites' surroundings, so it cannot be added to them.")
        RoiVideo.check_codec(self.data_dir)

        writer = RoiWriter(self.data_dir)
        later = []
        if saved:
            existing = RoiRecordings(self.data_dir)
            writer.index = existing.index
            self.analysis.boxes = existing.boxes
        else:
            later = self._later(todo)
        first = None
        number = -1  # the recording, of those converted now
        for event in FolderSource(self.data_dir, todo).events():
            if isinstance(event, Frame):
                if not writer.started:
                    self.analysis.detect(event)
                    if not self.analysis.mites and not later:
                        _logger.warning("No mites found in %s: its frames are kept whole.", self.data_dir)
                        return 0
                    homes = [tuple(mite) for mite in self.analysis.mites]
                    # with mites to add, saved as a live run saves them, the ROIs placed per recording
                    writer.start(event.image, homes, follow=bool(later))
                if first is None:
                    number += 1
                    if later:
                        writer.place(homes + [box for start, box in later if start <= number])
                        if any(start == number for start, _box in later):
                            self.added_frames[number] = event.image
                    first = event.image
                last = event.image
                writer.add(event.recording, event.image)
            else:
                writer.end(event.recording, self.analysis.blobs_on(first, last))
                first = None
        RoiRecordings(self.data_dir).stitch()
        self._remove_frames(todo)
        return len(todo)

    def _later(self, names):
        """[(recording, box)]: the mites that appear after the first of `names`
        (classes/scoring/new_mites.py); none when none are looked for."""
        analyzer = self.analysis.analyzer
        least = analyzer.config.detector.min_new_mites
        if least <= 0 or len(names) < 2:
            return []
        loader = DataLoader(self.data_dir)
        zone_manager = self.analysis.zone_manager
        image = loader.read_image(loader.frame_paths(names[0])[0])
        with DETECTION_LOCK:  # a Mite counts the ids on
            known = [tuple(mite) for mite in analyzer.detect(zone_manager.mask_image_to_valid_rois(image))]
        search = NewMites(zone_manager, analyzer, known, least)
        for number, name in enumerate(names[1:], start=1):
            search.search(number, loader.read_image(loader.frame_paths(name)[0]))
        return search.found

    def _remove_frames(self, names):
        for name in names:
            remove_tree(self.data_dir / name)
