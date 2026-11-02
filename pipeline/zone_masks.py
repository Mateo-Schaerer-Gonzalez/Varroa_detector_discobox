"""The Zones page: the zone masks, made and changed there
(classes/plate/zone_masks.py), how the analysis will number their zones, and
the pictures to draw them on, the first frame of a recording kept.
"""

from pathlib import Path

import cv2

from classes.plate import zone_masks
from classes.storage.roi_recordings import open_recordings
from pipeline import paths, plate_zones


def list_masks():
    """Every zone mask with zones of its own, the built-in ones first: [{name,
    title, built_in, n_mite_zones, n_text_zones}]. Not the automatic one, whose
    zones each recording finds itself (pipeline/auto_zones.py)."""
    masks = []
    for name in zone_masks.names():
        if name == zone_masks.AUTO:
            continue
        zones = zone_masks.read(name)
        masks.append({"name": name, "title": zone_masks.title(name), "built_in": name in zone_masks.BUILT_IN,
                      "n_mite_zones": sum(zone["type"] == "mite" for zone in zones),
                      "n_text_zones": sum(zone["type"] == "text" for zone in zones)})
    return masks


def read_mask(name):
    """The mask `name` with its zones ([{type, x1, y1, x2, y2}]) and how the
    analysis numbers them (number_mask())."""
    name = zone_masks.check(name)
    if name == zone_masks.AUTO:
        raise FileNotFoundError("The automatic mask's zones are found on each recording's first frame.")
    zones = zone_masks.read(name)
    return {"name": name, "title": zone_masks.title(name), "built_in": name in zone_masks.BUILT_IN,
            "zones": zones, **number_mask(zones)}


def save_mask(name, zones):
    """Keep `zones` as the mask `name` (never a built-in one); read_mask() of it."""
    return read_mask(zone_masks.save(name, zones))


def delete_mask(name):
    """Remove the mask `name`; the recordings that used it go back to the default one."""
    zone_masks.delete(name)
    return {"deleted": name, "masks": list_masks()}


def number_mask(zones):
    """How the analysis numbers `zones` ([{type, x1, y1, x2, y2}]): {ids, text_of}
    (plate_zones.mask_numbers())."""
    for number, zone in enumerate(zones, start=1):
        if zone.get("type") not in zone_masks.TYPES:
            raise ValueError(f"Zone {number} is neither a mite zone nor a text zone.")
    return plate_zones.mask_numbers(zones)


def recording_picture(name, recordings_root=paths.RECORDINGS_ROOT):
    """The first frame of the recordings `name` in `recordings_root`, as JPEG bytes."""
    data_dir = Path(recordings_root) / str(name)
    if Path(str(name)).name != str(name) or str(name) in ("", ".", "..") or not data_dir.is_dir():
        raise FileNotFoundError(f"No recordings {name!r} in {recordings_root}.")
    frame = open_recordings(data_dir).load_preview_frame()
    found, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not found:
        raise FileNotFoundError(f"The first frame of {name} could not be read.")
    return encoded.tobytes()
