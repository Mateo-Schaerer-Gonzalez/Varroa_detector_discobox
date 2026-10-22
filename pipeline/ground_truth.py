"""A recording folder's ground_truth.json: by mite position, what the user saw
each mite do in each recording ("moving", "still"), or that a detection is not
a mite. The analysis reads the "not a mite" marks, the calibration everything.
"""

from pathlib import Path

from classes import calibration
from classes.files import read_json, write_json
from pipeline import paths


def load_ground_truth(data_dir):
    """Saved ground truth for a recording session: a list of {x, y, truth}, where
    truth holds one status per recording, as every window reads it."""
    return read_json(Path(data_dir) / paths.GROUND_TRUTH_FILENAME, [])


def write_truth(data_dir, entries):
    """Save ground truth (entries by position, as load_ground_truth() reads them)
    next to the recordings in `data_dir`."""
    write_json(Path(data_dir) / paths.GROUND_TRUTH_FILENAME, entries)


def rejected_detections(zone_manager, saved):
    """The detected mites the user marked as not being mites."""
    rejected = [entry for entry in saved if calibration.is_rejected(entry.get("truth"))]
    if not rejected:
        return []
    mites = zone_manager.mites
    described = [{"id": index, "x": m.home[0], "y": m.home[1]} for index, m in enumerate(mites)]
    matched = calibration.match_ground_truth(described, rejected, n_recordings=1)
    return [mites[index] for index in matched]


def mite_states(dataset, truth=None):
    """[(mite, its statuses per recording, see calibration.per_recording())] of a
    dataset or a calibration session (`truth` by mite id, the dataset's own by
    default), the mites marked not a mite left out."""
    truth = dataset["truth"] if truth is None else truth
    n_recordings = len(dataset["times"])
    states = ((mite, calibration.per_recording(truth.get(mite["id"]), n_recordings)) for mite in dataset["mites"])
    return [(mite, mite_states) for mite, mite_states in states if not calibration.is_rejected(mite_states)]


def labelled(entries):
    """Whether ground truth (load_ground_truth()) labels any mite, as moving,
    still or not a mite."""
    return any(any(entry.get("truth") if isinstance(entry.get("truth"), list) else [entry.get("truth")])
               for entry in entries if isinstance(entry, dict))
