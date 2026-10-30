"""Mites put on the plates of a folder of frames after its first recording:
found on the first frame of every recording (classes/scoring/new_mites.py), at
least config.yaml's `detector.min_new_mites` in a zone at once, and analysed
from the recording they appear in, as a live run's added mites are.

A search reads one frame per recording, so what it found is kept in the
results folder (kept/NEW_MITES_NAME, beside the kept scores), until the recordings, the zones or the
detector's settings change. A session saved as the mites' ROIs (a live run, a
folder shrunk) has its added mites in its index instead.
"""

import dataclasses
from pathlib import Path

from classes import app_config
from classes.app_config import get_default_config
from classes.scoring.analyzer import Analyzer
from classes.scoring.motion_analysis import DETECTION_LOCK
from classes.scoring.new_mites import NewMites
from classes.plate.mite import Mite
from classes.storage.data_loader import DataLoader
from classes.storage.files import try_json, write_json
from classes.storage.kept_scores import KeptScores
from classes.storage.roi_recordings import is_roi_session
from pipeline import paths, plate_zones, preview_images

# Made with the search's results; another version is searched again.
VERSION = 1


def setting(data_dir):
    """What the label page shows of the search: {least: config.yaml's
    `detector.min_new_mites`, applies: whether `data_dir` is a folder of frames,
    the mites of a session saved as ROIs being those saved}."""
    return {"least": int(get_default_config().detector.min_new_mites),
            "applies": Path(data_dir).is_dir() and not is_roi_session(data_dir)}


def save_least(count):
    """Save `detector.min_new_mites` in config.yaml (0: no mites are looked for
    after the first recording)."""
    return app_config.save_min_new_mites(count)


def found(data_dir, coords_file=None, names=None, keep_in=None):
    """(boxes, starts) for a MotionAnalysis: the mites found on the first frame
    of a folder of frames (in the order detected), then those that appear
    later, each with the recording it appears in (0 for the first frame's).
    None when none appear, none are looked for (`min_new_mites` 0) or the
    folder is saved as ROIs. `names`: only those recordings; `keep_in`, a
    folder: the search is kept there and read back."""
    if is_roi_session(data_dir):
        return None
    analyzer = Analyzer()
    detector = analyzer.config.detector
    if detector.min_new_mites <= 0:
        return None
    loader = DataLoader(data_dir)
    names = [name for name in loader.recording_names if names is None or name in set(names)]
    if len(names) < 2:
        return None
    zone_manager = plate_zones.zones_of(data_dir, coords_file)
    key = {"version": VERSION, "recordings": names, "detector": dataclasses.asdict(detector),
           "zones": [[zone.id, *zone] for zone in zone_manager.zones]}
    kept = Path(keep_in) / KeptScores.DIRNAME / paths.NEW_MITES_NAME if keep_in is not None else None
    saved = try_json(kept) if kept is not None else None
    if not (isinstance(saved, dict) and saved.get("key") == key):
        saved = {"key": key, **_search(loader, names, zone_manager, analyzer)}
        if kept is not None:
            kept.parent.mkdir(parents=True, exist_ok=True)
            write_json(kept, saved)
    if not saved["added"]:
        return None
    boxes = [tuple(box) for box in saved["boxes"]] + [tuple(box) for _start, box in saved["added"]]
    starts = [0] * len(saved["boxes"]) + [start for start, _box in saved["added"]]
    return boxes, starts


def previews(data_dir, out_dir, n_recordings, starts):
    """The picture of the plate for each recording (preview_images.added_previews()):
    from a recording mites appeared in on, its first frame, written to `out_dir`."""
    loader = DataLoader(data_dir)
    names = loader.recording_names
    frames = {start: loader.read_image(loader.frame_paths(names[start])[0])
              for start in set(starts) if 0 < start < min(n_recordings, len(names))}
    return preview_images.found_previews(frames, out_dir, n_recordings)


def _search(loader, names, zone_manager, analyzer):
    """{boxes: the first frame's mites, added: [[recording, box], ...]}."""
    first = loader.read_image(loader.frame_paths(names[0])[0])
    with DETECTION_LOCK:  # a Mite counts the ids on
        Mite.reset_ids()
        mites = analyzer.detect(zone_manager.mask_image_to_valid_rois(first))
    boxes = [tuple(mite) for mite in mites]
    search = NewMites(zone_manager, analyzer, boxes, analyzer.config.detector.min_new_mites)
    for number, name in enumerate(names[1:], start=1):
        search.search(number, loader.read_image(loader.frame_paths(name)[0]))
    return {"boxes": [list(box) for box in boxes], "added": [[start, list(box)] for start, box in search.found]}
