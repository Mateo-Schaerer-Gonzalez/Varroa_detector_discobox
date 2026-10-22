"""Shrinks a folder of whole frames (..._fps-30/*.bmp, as the Discobox app saves
them) to what a live run saves: the mites' ROIs, the first frame whole and the
blobs on each recording's first and last frame (classes/roi_recordings.py).

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
"""

import logging
from pathlib import Path

from classes.data_loader import DataLoader
from classes.frame_source import Frame, FolderSource
from classes.motion_analysis import MotionAnalysis
from classes.files import remove_tree
from classes.roi_recordings import RoiRecordings, RoiVideo, RoiWriter, is_roi_session

_logger = logging.getLogger(__name__)


class RoiConversion:
    def __init__(self, data_dir, zone_manager, analyzer=None):
        self.data_dir = Path(data_dir)
        self.analysis = MotionAnalysis(zone_manager, analyzer, score=False)

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
        if saved:
            existing = RoiRecordings(self.data_dir)
            writer.index = existing.index
            self.analysis.boxes = existing.boxes
        first = None
        for event in FolderSource(self.data_dir, todo).events():
            if isinstance(event, Frame):
                if not writer.started:
                    self.analysis.detect(event)
                    if not self.analysis.mites:
                        _logger.warning("No mites found in %s: its frames are kept whole.", self.data_dir)
                        return 0
                    writer.start(event.image, [tuple(mite) for mite in self.analysis.mites])
                if first is None:
                    first = event.image
                last = event.image
                writer.add(event.recording, event.image)
            else:
                writer.end(event.recording, self.analysis.blobs_on(first, last))
                first = None
        RoiRecordings(self.data_dir).stitch()
        self._remove_frames(todo)
        return len(todo)

    def _remove_frames(self, names):
        for name in names:
            remove_tree(self.data_dir / name)
