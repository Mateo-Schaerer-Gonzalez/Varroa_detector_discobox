"""The plates and their zones, and the mites in them as the pages know them.

A recording's zones are those of the layout saved with it (one zone per plate,
coords_pixel.txt, or two, coords_pixel_2.txt; classes/zone_layout.py).
"""

from pathlib import Path

from classes.zone_layout import ZoneLayout
from classes.zones import ZoneManager


# Zone type ids as they appear in the coordinates file.
ZONE_TYPES = {"0": "label", "1": "mite"}
EXCLUDED_TYPES = ["label"]

# One zone per plate. Which file a recording uses is saved with it (classes/zone_layout.py).
DEFAULT_COORDS_FILE = "coords_pixel.txt"


def build_zone_manager(coords_file):
    return ZoneManager.from_coords_file(
        filepath=coords_file,
        zone_types=ZONE_TYPES,
        excluded_types=EXCLUDED_TYPES,
    )


def coords_file_of(data_dir, coords_file=None):
    """The zones of the recordings in `data_dir`: those of the layout saved with
    them, unless a `coords_file` is given."""
    return coords_file or ZoneLayout.of_folder(data_dir).coords_file


def zones_of(data_dir, coords_file=None):
    """The ZoneManager of the recordings in `data_dir`: the zones of the layout
    saved with them, unless a `coords_file` is given; no mites in them yet."""
    return build_zone_manager(coords_file_of(data_dir, coords_file))


def zones_per_plate(data_dir):
    """How many zones each plate of the recordings in `data_dir` is cut into."""
    return ZoneLayout.of_folder(data_dir).zones_per_plate


def layout_file(data_dir, name):
    return Path(data_dir) / ZoneLayout.of_folder(data_dir).filename(name)


def describe_zones(zone_manager, labels):
    """The plates in reading order, as plain rectangles in image pixels."""
    labels = {str(key): value for key, value in (labels or {}).items()}

    def text_zone(zone):
        # Where the plate's name is shown: its printed-label area, if it has one.
        area = zone_manager.text_zone_for(zone)
        return None if area is None else {"x1": area.x1, "y1": area.y1, "x2": area.x2, "y2": area.y2}

    return [
        {
            "id": zone.id,
            "x1": zone.x1,
            "y1": zone.y1,
            "x2": zone.x2,
            "y2": zone.y2,
            "text_zone": text_zone(zone),
            "label": labels.get(str(zone.id), ""),
        }
        for zone in zone_manager.labelled_zones
    ]


def mite_view(mite, zone_id, **more):
    """A detected mite (a Mite) as the pages and the ground truth know it: {id,
    zone_id, x, y (its centre), r (half its box's width)}, and `more`."""
    x, y = mite.home
    return {"id": mite.text, "zone_id": zone_id, "x": round(float(x), 1), "y": round(float(y), 1),
            "r": round(float((mite.x2 - mite.x1) / 2), 1), **more}
