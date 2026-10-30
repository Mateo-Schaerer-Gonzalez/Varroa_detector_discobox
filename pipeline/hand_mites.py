"""Mites placed by hand on the label page, where the detector missed them: kept
in a folder's mites_by_hand.json, as points (classes/plate/hand_mites.py).

plate_zones.zones_of() gives a folder's ZoneManager its points, so every
detection on its whole frames finds them with the detector's mites. A session
saved as the mites' ROIs has no frames away from the mites found when it was
saved: those placed by hand before are among its boxes, and no more can be.
"""

from pathlib import Path

from classes.app_config import get_default_config
from classes.plate import hand_mites, positions
from classes.storage.files import read_json, write_json
from classes.storage.roi_recordings import is_roi_session
from pipeline import paths


def saved(data_dir):
    """Every mite placed by hand in `data_dir`, [{x, y, size}]."""
    return [] if data_dir is None else read_json(Path(data_dir) / paths.HAND_MITES_FILENAME, [])


def points(data_dir):
    """The mites placed by hand in `data_dir` that a detection is to find; none
    for a session saved as ROIs (they are among its boxes)."""
    if data_dir is None or is_roi_session(data_dir):
        return []
    return saved(data_dir)


def can_place(data_dir):
    """Whether mites can be placed by hand in `data_dir`: it holds whole frames."""
    return not is_roi_session(data_dir)


def check_whole(data_dir):
    if not can_place(data_dir):
        raise ValueError("These recordings keep only the surroundings of the mites found when they were saved, so a "
                         "mite elsewhere has no frames to be scored on.")


def where(zone_manager, image, x, y, others):
    """{x, y, size}: a mite placed by hand at (x, y) on `image`, its centre the
    darkest spot near (hand_mites.centre_near()), its box the size of the
    detector's in `zone_manager`. Refused outside a plate, on its label, or
    within positions.TOLERANCE of `others` ((x, y) each: the mites there)."""
    mite = get_default_config().mite
    x, y = hand_mites.centre_near(image, float(x), float(y))
    size = hand_mites.box_size(zone_manager.mites, mite.radius)
    if zone_manager.zone_of(hand_mites.box_at(x, y, size)) is None or zone_manager.is_excluded(x, y):
        raise ValueError("A mite is placed inside a plate, clear of its edge and of its label.")
    if not positions.away_from_all({"x": x, "y": y}, [{"x": ox, "y": oy} for ox, oy in others]):
        raise ValueError("There is a mite there already.")
    return {"x": x, "y": y, "size": size}


def place(data_dir, zone_manager, image, x, y):
    """Keep a mite placed by hand at (x, y) on `image`, the first frame of
    `data_dir`, whose mites `zone_manager` holds (where()). Returns it."""
    check_whole(data_dir)
    point = where(zone_manager, image, x, y, [mite.home for mite in zone_manager.mites])
    write_json(Path(data_dir) / paths.HAND_MITES_FILENAME, [*points(data_dir), point])
    return point


def remove(data_dir, x, y):
    """Forget the mite placed by hand nearest (x, y), within positions.TOLERANCE."""
    check_whole(data_dir)
    saved = points(data_dir)
    nearest = positions.nearest(saved, float(x), float(y))
    if nearest is None:
        raise ValueError("No mite was placed by hand there.")
    write_json(Path(data_dir) / paths.HAND_MITES_FILENAME, [point for point in saved if point is not nearest])
