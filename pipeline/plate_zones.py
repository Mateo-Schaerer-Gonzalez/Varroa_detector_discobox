"""The plates and their zones, and the mites in them as the pages know them.

A recording's zones are those of the zone mask saved with it (one zone per
plate, coords_pixel.txt, two, coords_pixel_2.txt, one made on the Zones page,
or the automatic one, found on the recordings' first frame, pipeline/auto_zones.py;
classes/plate/zone_layout.py, classes/plate/zone_masks.py).
"""

from pathlib import Path

from classes.plate import zone_masks
from classes.plate.zone_layout import ZoneLayout
from classes.plate.zones import Zone, ZoneManager
from pipeline import auto_zones, hand_mites


# Zone type ids as they appear in the coordinates file.
ZONE_TYPES = {"0": "label", "1": "mite"}
EXCLUDED_TYPES = ["label"]

# One zone per plate. Which mask a recording uses is saved with it (classes/plate/zone_layout.py).
DEFAULT_COORDS_FILE = "coords_pixel.txt"


def build_zone_manager(coords_file):
    return ZoneManager.from_coords_file(
        filepath=coords_file,
        zone_types=ZONE_TYPES,
        excluded_types=EXCLUDED_TYPES,
    )


def coords_file_of(data_dir, coords_file=None):
    """The zones of the recordings in `data_dir`: those of the mask saved with
    them (the automatic one's found on their first frame, once), unless a
    `coords_file` is given."""
    if coords_file:
        return coords_file
    layout = ZoneLayout.of_folder(data_dir)
    return auto_zones.coords_file(data_dir) if layout.mask == zone_masks.AUTO else layout.coords_file


def zones_of(data_dir, coords_file=None):
    """The ZoneManager of the recordings in `data_dir`: the zones of the mask
    saved with them, unless a `coords_file` is given; no mites in them yet, but
    the mites placed by hand there, which the detection finds with its own."""
    zone_manager = build_zone_manager(coords_file_of(data_dir, coords_file))
    zone_manager.by_hand = hand_mites.points(data_dir)
    return zone_manager


def zone_mask(data_dir):
    """The name of the zone mask the recordings in `data_dir` are cut into."""
    return ZoneLayout.of_folder(data_dir).mask


def mask_numbers(zones):
    """How the analysis numbers the zones of a mask drawn on the Zones page:
    `zones` [{type ("mite" or "text"), x1, y1, x2, y2}] -> {ids: per zone its id
    (a mite zone's, in reading order; None for a text zone), text_of: per zone
    the index of the text zone its plate's name is read from (None for a text
    zone, or a mite zone without one)}. As build_zone_manager() reads the file."""
    built = [Zone(int(float(zone["x1"])), int(float(zone["y1"])), int(float(zone["x2"])), int(float(zone["y2"])),
                  type=ZONE_TYPES[zone_masks.TYPES[zone["type"]]]) for zone in zones]
    zone_manager = ZoneManager(zones=list(built), excluded_types=EXCLUDED_TYPES)
    index = {id(zone): number for number, zone in enumerate(built)}
    text_of = []
    for zone in built:
        area = None if zone.id is None else zone_manager.text_zone_for(zone)
        text_of.append(None if area is None else index[id(area)])
    return {"ids": [zone.id for zone in built], "text_of": text_of}


def layout_file(data_dir, name):
    return Path(data_dir) / ZoneLayout.of_folder(data_dir).filename(name)


def mask_choices(data_dir):
    """The zone mask of the recordings in `data_dir` and every mask they can
    take, as the label page offers them."""
    return {"zone_mask": zone_mask(data_dir), "zone_masks": ZoneLayout.choices()}


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
    zone_id, x, y (its centre), r (half its box's width)}, by_hand: true for
    a mite placed by hand (classes/plate/hand_mites.py), and `more`."""
    x, y = mite.home
    view = {"id": mite.text, "zone_id": zone_id, "x": round(float(x), 1), "y": round(float(y), 1),
            "r": round(float((mite.x2 - mite.x1) / 2), 1)}
    if getattr(mite, "by_hand", False):
        view["by_hand"] = True
    return {**view, **more}
