"""What the scripts read again and again: the longest labelled dataset, a
dataset's labels as arrays, and their own caches of what they measured.

A cache is named after what it was worked out with (`source`: the code and the
settings, as text), so a change to either works it out again; it can be deleted
at any time.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import pipeline  # noqa: E402
from classes import calibration  # noqa: E402


def longest_dataset():
    """The saved dataset (pipeline._read_dataset()) with the most recordings."""
    saved = {summary["id"]: pipeline._read_dataset(summary["id"]) for summary in pipeline.list_calibration_datasets()}
    return saved[max(saved, key=lambda key: len(saved[key]["times"]))]


def labels_of(dataset):
    """(mites, moving, labelled) of a dataset, the mites marked not a mite left
    out: the mites, and as (mites, recordings) whether each is labelled moving,
    and whether it is labelled at all (moving or still)."""
    kept = pipeline._mite_states(dataset)
    states = np.array([states for _mite, states in kept], dtype=object)
    moving = states == calibration.MOVING
    return [mite for mite, _states in kept], moving, moving | (states == calibration.STILL)


def cache_path(cache, name, source, suffix=".npz"):
    """`cache`/<name>-<12 hex digits of `source`><suffix>."""
    return Path(cache) / f"{name}-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}{suffix}"


def kept_arrays(cache, name, source, make):
    """The arrays make() works out ({key: array}), kept in cache_path() and
    read back from there after."""
    path = cache_path(cache, name, source)
    if path.is_file():
        with np.load(path) as kept:
            return {key: kept[key] for key in kept.files}
    arrays = make()
    np.savez(path, **arrays)
    return arrays
