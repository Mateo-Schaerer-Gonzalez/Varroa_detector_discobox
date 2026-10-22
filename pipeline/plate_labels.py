"""What the plates are: the group names typed beside them (labels.json), read
from the plates by Google Gemini on request, and the zones ticked as negative
controls (controls.json). Both are kept next to the recordings.
"""

from pathlib import Path

import cv2

from classes import app_config
from classes.app_config import get_default_config
from classes.files import read_json, try_json, write_json
from classes.label_reader import LabelReader
from pipeline import paths, plate_zones


def load_labels(data_dir):
    """Read previously saved zone labels for this recording session, if any."""
    return read_json(plate_zones.layout_file(data_dir, paths.LABELS_FILENAME), {})


def save_labels(data_dir, labels):
    """Store zone labels next to the recordings so they survive a restart."""
    path = plate_zones.layout_file(data_dir, paths.LABELS_FILENAME)
    write_json(path, labels, indent=2)
    return str(path)


def label_reading():
    """Whether the names written beside the plates can be read (it takes a Google
    Gemini API key, see classes/label_reader.py), and whether the label page
    does so: its box, off until ticked (save_label_reading)."""
    return {"available": LabelReader.saved_key() is not None, "enabled": bool(get_default_config().label_reader.enabled)}


def save_label_reading(enabled):
    """Read the names from the plates from now on, or stop: the tick of the label
    page's box, saved in config.yaml."""
    app_config.save_label_reading(bool(enabled))
    return label_reading()


def read_labels(data_dir, out_dir, mites, coords_file=None):
    """Read the names written by hand beside the plates of the recordings in
    `data_dir`, on the preview picture in `out_dir`: {zone id (a string): name},
    for the zones with a detection among the label page's `mites` and no name
    saved yet, where something is written. Nothing is saved: the page fills them
    in for the user to check. Raises LabelReadError without a key or the internet."""
    return read_zone_labels(plate_zones.zones_of(data_dir, coords_file), data_dir, out_dir, mites)


def read_zone_labels(zone_manager, data_dir, out_dir, mites):
    frame = cv2.imread(str(Path(out_dir) / paths.PREVIEW_NAME))
    if frame is None:
        raise FileNotFoundError("There is no picture of the plates to read the names from; open the folder again.")
    saved = {str(key): str(value).strip() for key, value in load_labels(data_dir).items()}
    with_mites = {mite["zone_id"] for mite in mites}
    areas = {}  # a label area and the zones it names: the two halves of a plate share one
    for zone in zone_manager.labelled_zones:
        area = zone_manager.text_zone_for(zone)
        if zone.id in with_mites and not saved.get(str(zone.id)) and area is not None:
            areas.setdefault(id(area), (area, []))[1].append(zone.id)
    if not areas:
        return {}
    reader = LabelReader(model=get_default_config().label_reader.model)
    names = reader.read(frame, [area for area, _zones in areas.values()], sorted(set(filter(None, saved.values()))))
    return {str(zone_id): name for (_area, zone_ids), name in zip(areas.values(), names) if name for zone_id in zone_ids}


def load_controls(data_dir):
    """The ids of the zones ticked as negative controls, which the survival of
    every other zone is compared with; none if nothing was ticked."""
    ids = try_json(plate_zones.layout_file(data_dir, paths.CONTROLS_FILENAME), [])
    return sorted({i for i in ids if isinstance(i, int)}) if isinstance(ids, list) else []


def save_controls(data_dir, controls):
    """Store the negative-control zones next to the recordings, beside the labels."""
    ids = sorted({int(i) for i in controls})
    write_json(plate_zones.layout_file(data_dir, paths.CONTROLS_FILENAME), ids)
    return ids
