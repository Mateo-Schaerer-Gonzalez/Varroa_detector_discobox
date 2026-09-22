"""The analysis, as two functions.

This is the only module the user interface is allowed to call, and it knows nothing
about HTTP, sessions or browsers. Everything crossing this boundary is a plain dict,
list, string or number -- never a Zone, Mite, DataFrame or image array -- so the UI
can never reach into the analysis internals.

    open_session(...)   cheap: the zones to label and a preview image
    run_analysis(...)   the full pipeline, writing Excel and figures to out_dir
"""

import json
from pathlib import Path

import cv2
import numpy as np

import reporting
from classes.analyzer import Analyzer
from classes.data_loader import DataLoader
from classes.mite import Mite
from classes.zones import ZoneManager

# Zone type ids as they appear in the coordinates file.
ZONE_TYPES = {"0": "label", "1": "mite"}
EXCLUDED_TYPES = ["label"]

DEFAULT_COORDS_FILE = "coords_pixel.txt"
LABELS_FILENAME = "labels.json"
PREVIEW_NAME = "preview.jpg"


def _build_zone_manager(coords_file):
    return ZoneManager.from_coords_file(
        filepath=coords_file,
        zone_types=ZONE_TYPES,
        excluded_types=EXCLUDED_TYPES,
    )


def _describe_zones(zone_manager, labels):
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


def load_labels(data_dir):
    """Read previously saved zone labels for this recording session, if any."""
    path = Path(data_dir) / LABELS_FILENAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_labels(data_dir, labels):
    """Store zone labels next to the recordings so they survive a restart."""
    path = Path(data_dir) / LABELS_FILENAME
    path.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    return str(path)


def open_session(data_dir, out_dir, coords_file=DEFAULT_COORDS_FILE):
    """Describe a recording session so its zones can be labelled.

    Decodes a single frame, writes it to `out_dir` as a JPEG, and returns the zone
    rectangles in image pixel coordinates. Drawing is left to the caller: the UI
    gets numbers, not a picture with boxes burnt into it.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    loader = DataLoader(data_dir, grayscale=False)
    n_recordings = loader.count_recordings()
    if n_recordings == 0:
        raise FileNotFoundError(f"No recordings found in {data_dir}")

    frame = loader.load_preview_frame()
    cv2.imwrite(str(out_dir / PREVIEW_NAME), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

    zone_manager = _build_zone_manager(coords_file)

    return {
        "data_dir": str(data_dir),
        "preview": PREVIEW_NAME,
        "image": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
        "n_recordings": n_recordings,
        "zones": _describe_zones(zone_manager, load_labels(data_dir)),
    }


def run_analysis(data_dir, out_dir, labels=None, coords_file=DEFAULT_COORDS_FILE):
    """Run the whole pipeline and write its results to `out_dir`.

    `labels` maps zone id (as a string) to the group name the user typed, e.g.
    {"0": "venom 2x", "1": "control"}. Returns the output filenames, a summary, and
    the per-zone and per-mite results the UI browses.
    """
    # The mite id counter is shared process-wide; restart it so each run numbers
    # its mites from zero.
    Mite.reset_ids()

    loader = DataLoader(data_dir, grayscale=False)
    zone_manager = _build_zone_manager(coords_file)
    zone_manager.apply_labels(labels)
    analyzer = Analyzer()

    recording_bursts = loader.load_bursts()
    first_frame = loader.get_first_frame()

    masked = zone_manager.mask_image_to_valid_rois(first_frame)
    mites = analyzer.detect(masked)
    valid_mites = zone_manager.assign_mites(mites)
    analyzer.classify_motility(valid_mites, recording_bursts)

    # One timestamp per burst, in minutes from the start of the session.
    burst_minutes = np.array([times[0] for _frames, times in recording_bursts]) / 60
    mite_data = zone_manager.get_mite_scores(burst_minutes)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / PREVIEW_NAME), first_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

    annotated = zone_manager.draw(masked)
    results = reporting.write_outputs(mite_data, annotated, out_dir)

    results.update(
        {
            "n_recordings": len(recording_bursts),
            "times": [round(float(minute), 2) for minute in burst_minutes],
            "threshold": float(analyzer.config.mite.motion_threshold),
            "preview": PREVIEW_NAME,
            "image": {"width": int(first_frame.shape[1]), "height": int(first_frame.shape[0])},
            "zones": reporting.describe_zones(mite_data, _describe_zones(zone_manager, labels), burst_minutes),
            "mites": reporting.describe_mites(mite_data),
            "groups": reporting.describe_groups(mite_data, burst_minutes),
        }
    )
    return results
