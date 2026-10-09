"""The legs of every mite of the longest labelled run, found in every frame and
followed through the run (classes/leg_tracker.py): what is behind
notebooks/leg_tracking.ipynb.

The patches are those scripts/optuna_death_time.py cuts and keeps; the tracks
are kept beside them, so only the first run is slow (about 2 minutes).

    python scripts/leg_tracks.py     # follows the legs, prints a summary
"""
import hashlib
import inspect
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import alive_dead_features as adf
from classes import leg_tracker
from classes.leg_tracker import LegTracker, Tracks
from optuna_death_time import MAX_PAD

FIELDS = ("xy", "tip", "length", "mass", "centre", "axis", "count")


def _follow(job):
    """One mite's legs through every frame of the run, the recordings one
    after the other."""
    path, mite, height, width, settings = job
    patches = np.load(path, mmap_mode="r")
    grey = np.asarray(patches[mite, :, :, :height + 2 * MAX_PAD, :width + 2 * MAX_PAD]).mean(axis=-1)
    return LegTracker(**settings).track(grey.reshape(-1, *grey.shape[2:]))


def follow_run(run, cache=adf.CACHE, jobs=None, **settings):
    """Per mite, its Tracks over all the frames of the run (recordings x
    frames, in order). `settings` are LegTracker's. Kept in `cache`."""
    source = inspect.getsource(leg_tracker) + run.path + repr(sorted(settings.items()))
    path = Path(cache) / f"leg_tracks-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}.npz"
    if path.is_file():
        kept = np.load(path)
        return [Tracks(*(kept[f"{mite}/{field}"] for field in FIELDS)) for mite in range(len(run.mites))]
    work = [(run.path, mite, *run.sizes[mite], settings) for mite in range(len(run.mites))]
    with ProcessPoolExecutor(jobs or os.cpu_count()) as pool:
        tracks = list(pool.map(_follow, work))
    np.savez(path, **{f"{mite}/{field}": getattr(found, field) for mite, found in enumerate(tracks) for field in FIELDS})
    return tracks


def frames_per_recording(run):
    """The frames of one recording of the run."""
    return int(np.load(run.path, mmap_mode="r").shape[2])


# ---- per recording ----

def counts(found, per):
    """The legs found per frame, in the middle over each recording's frames: (recordings,)."""
    return found.count.reshape(-1, per).mean(axis=1)


def lengths(found, per):
    """How far the followed legs reach from the body's edge, in pixels: the
    mean over the legs and frames of each recording, nan without a leg."""
    if not len(found):
        return np.full(found.count.shape[0] // per, np.nan)
    length = found.length.reshape(len(found), -1, per)
    seen = np.isfinite(length).sum(axis=(0, 2))
    return np.where(seen > 0, np.nansum(length, axis=(0, 2)) / np.maximum(seen, 1), np.nan)


def place_change(found, per, at_least=3):
    """How far the legs are from where they were in the recording before, in
    pixels: (change, floor), each (recordings,). `change` is the largest, over
    the legs seen in `at_least` frames of both recordings, of how far the
    leg's place (LegTracker.places()) went; nan for the first recording, 0
    without such a leg. `floor` is what two recordings of legs that did
    nothing would give: the same between the mean of every other frame and
    the mean of the rest, brought to whole recordings."""
    n_recordings = found.count.shape[0] // per
    change, floor = np.zeros(n_recordings), np.zeros(n_recordings)
    change[0] = np.nan
    if not len(found):
        return change, floor
    points, seen = LegTracker._by_recording(found.xy, per)
    often = seen >= at_least
    places = LegTracker.places(found, per)
    went = np.linalg.norm(np.diff(places, axis=1), axis=-1)
    change[1:] = np.where(often[:, 1:] & often[:, :-1], went, 0).max(axis=0)
    halves = [np.nansum(points[:, :, start::2], axis=2) / np.maximum(np.isfinite(points[:, :, start::2, 0]).sum(axis=2), 1)[..., None]
              for start in (0, 1)]
    # the noise of a mean of n frames goes by 1/sqrt(n): halves differ by sqrt(4/n), whole recordings by sqrt(2/n)
    apart = np.linalg.norm(halves[0] - halves[1], axis=-1) / np.sqrt(2)
    floor[:] = np.where(seen == per, apart, 0).max(axis=0)
    return change, floor


def in_body_frame(found):
    """The legs' places turned with the mite, (legs, frames, 2) as (along,
    across): `along` is along the body's long axis, `across` at a right angle
    to it, pointing to the side that has the legs (the mite's front: a Varroa
    mite is wider than it is long). The side is chosen once for the mite, and
    the axis followed from frame to frame, so a mite that turns keeps it."""
    axis = found.axis.copy()
    known = np.isfinite(axis)
    if not len(found) or not known.any():
        return np.full(found.xy.shape, np.nan)
    axis = np.interp(np.arange(len(axis)), np.flatnonzero(known), np.unwrap(2 * axis[known]) / 2)  # an axis has no head: it is the same half a turn on
    along = found.xy[..., 0] * np.cos(axis) + found.xy[..., 1] * np.sin(axis)
    across = -found.xy[..., 0] * np.sin(axis) + found.xy[..., 1] * np.cos(axis)
    side = np.sign(np.nansum(across * found.mass)) or 1.0
    return np.stack([along, across * side], axis=-1)


def main():
    run = adf.load_run()
    tracks = follow_run(run)
    per = frames_per_recording(run)
    legs = np.array([counts(found, per) for found in tracks])      # (mites, recordings)
    movement = np.array([LegTracker.movement(found, per) for found in tracks])
    still = run.labelled & ~run.moving
    print(f"{run.name}: {len(run.mites)} mites, {run.moving.shape[1]} recordings of {per} frames")
    print(f"  legs found per frame: {np.median(legs[:, :5]):.1f} in the first 5 recordings, {np.median(legs[:, -5:]):.1f} in the last 5")
    print(f"  leg movement within a recording, pixels: {np.median(movement[run.moving]):.2f} labelled moving, "
          f"{np.median(movement[still]):.2f} labelled still; AUC {adf.auc(movement[run.moving], movement[still]):.3f}")


if __name__ == "__main__":
    main()
