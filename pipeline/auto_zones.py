"""The automatic zone mask (zone_masks.AUTO): each slide and the zone on it where
the writing is, found on a recording's first frame (classes/plate/slide_finder.py),
once, and kept with the recordings as zones_auto.txt, a coordinates file like any
mask's. Where no slide is found, it holds the zones of zone_masks.FALLBACK. A live
run finds them on its lit frame until it starts (live_runs.find_auto_zones()).
"""

from pathlib import Path

from classes.plate import slide_finder, zone_masks
from classes.storage import files
from classes.storage.roi_recordings import open_recordings
from pipeline import paths


def coords_file(data_dir):
    """The automatic zones of the recordings in `data_dir`, found on their first
    frame the first time they are asked for; FALLBACK's file while there is no
    frame to find them on."""
    path = Path(data_dir) / paths.AUTO_ZONES_NAME
    if path.is_file():
        return path
    try:
        frame = open_recordings(data_dir).load_preview_frame()
    except (OSError, ValueError):
        return zone_masks.coords_file(zone_masks.FALLBACK)
    return find(data_dir, frame)


def kept(data_dir):
    """The automatic zones kept in `data_dir`, FALLBACK's file if none are yet;
    nothing is looked for."""
    path = Path(data_dir) / paths.AUTO_ZONES_NAME
    return path if path.is_file() else zone_masks.coords_file(zone_masks.FALLBACK)


def find(data_dir, frame):
    """Find the slides on `frame` and keep their zones in `data_dir` (FALLBACK's
    zones if there are none), replacing any found before. Returns the file."""
    lines = slide_finder.coords_lines(slide_finder.find_slides(frame))
    if not lines:
        lines = zone_masks.coords_file(zone_masks.FALLBACK).read_text(encoding="utf-8").splitlines(keepends=True)
    path = Path(data_dir) / paths.AUTO_ZONES_NAME
    files.write_text(path, "".join(lines))
    return path
