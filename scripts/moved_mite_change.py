"""Does a mite's change between two recordings still tell alive from dead when
the mite has been moved between them, as opening the box to poke it or to
check it by eye moves it? What is behind notebooks/moved_mite_change.ipynb.

Every mite of the longest labelled run is moved on purpose in every recording
(move()), as a rigid body: shifted, turned, or both, by a fresh random amount
each time, so every pair of recordings sees a move. The moves are by whole
pixels and quarter turns, which move the pixels as they are: a real move gives
a fresh picture of the mite, not one interpolated, and interpolating blurs the
legs (a turn of 37 degrees halves the legs the tracker finds). ANY_ANGLE moves
by any amount and angle, interpolated: what a real move costs at most. Four measures then compare
each recording with the next (measure_mite()):

    image_change    classes/recording_change.py as it is: the mean difference
                    of the two images, the plate's shift (the median over the
                    mites) taken out
    aligned_change  the same difference after each mite is laid on itself:
                    its own shift and turn found (a turn every COARSE degrees,
                    then ECC), the comparison kept to the mite and a little
                    around it
    outline_change  classes/outline_change.py: the outline as rays from its centre, its shape
                    only (no size, no shift), compared at the turn that fits
                    best: no image is warped
    leg_shift       the legs (classes/leg_tracker.py) found in each recording,
                    their places turned into the body's own frame, paired with
                    those of the recording before: how far the pairs are apart
                    (largest and median), nan without a leg in either

A mite's move takes the plate's texture around it with it, which a real move
does not; the two comparisons of images keep mostly to the mite for that reason.

The patches are cut once from the recordings (the ROI videos of a live run or
whole frames, pipeline._measure_mites()) into the system's temporary folder;
the measures are kept in results/scripts/, so only the first run is slow.

    python scripts/moved_mite_change.py     # cuts, moves, measures, prints the table
"""
import hashlib
import inspect
import json
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.stats import rankdata

import pipeline
import script_data
from classes import leg_tracker, outline_change as outline_module, plate_stabilizer, recording_change
from classes.app_config import get_default_config
from classes.leg_tracker import LegTracker
from classes.outline_change import centre, darkness, outline, outline_change
from classes.recording_change import RecordingChange

CACHE = Path(tempfile.gettempdir()) / "varroa_death_time_patches"
PAD = 16             # pixels kept around each mite's box
MARGIN = 8           # pixels around the box image_change compares (as notebooks/dead_mite_change.ipynb)
ANY_ANGLE = "moved, any angle"
CONDITIONS = ("untouched", "shifted", "turned", "moved", ANY_ANGLE)
SHIFT = (2.0, 6.0)   # px a mite is shifted by, at random in between
COARSE = 10          # degrees between the turns tried before ECC
MITE_DARK = 0.15     # darker than this share of the plate's light is the mite
LEG_CAP = 3.0        # px: a leg further than this from its pair counts as this far
DEATH_MINUTES = 500  # a mite still this long after its last movement is dead (dead_mite_change.ipynb)
LONG_DEAD = 1000
SEED = 7
MEASURES = ("image_change", "aligned_change", "outline_change", "leg_shift", "leg_shift_median")


# ---- the run ----

def load_run(cache=CACHE):
    """The longest labelled run saved in recordings/: {name, ids, times
    (minutes), moving, labelled (mites, recordings), shapes (each mite's
    patch, (height, width)), path (the patches, (mites, recordings, frames,
    side, side) float32 grey, each in the top left corner of its square)}."""
    dataset = script_data.longest_dataset()
    n_recordings = len(dataset["times"])
    kept_mites, moving, labelled = script_data.labels_of(dataset)
    kept = [mite["id"] for mite in kept_mites]
    stabilize = get_default_config().mite.stabilize_plate
    names = [recording["name"] for recording in dataset["recordings"]]
    version = hashlib.sha1(json.dumps([inspect.getsource(plate_stabilizer), PAD, bool(stabilize), names,
                                       list(pipeline.mite_boxes(dataset["mites"]).values())]).encode("utf-8")).hexdigest()[:12]
    path = Path(cache) / f"moved_mite-{dataset['name']}-{version}.npy"
    shapes_path = path.with_suffix(".shapes.json")
    if not path.is_file():
        Path(cache).mkdir(parents=True, exist_ok=True)
        part, patches, shapes = path.with_suffix(".part.npy"), None, None
        # a stabilized cut comes with a channel axis of one
        cuts = pipeline._measure_mites(dataset, Path(dataset["data_dir"]),
                                       lambda roi: np.asarray(roi, dtype=np.float32).reshape(roi.shape[:3]), PAD, stabilize)
        for at, recording in enumerate(cuts):
            if patches is None:
                shapes = [recording[mite_id].shape[1:] for mite_id in kept]
                side = max(max(shape) for shape in shapes)
                n_frames = recording[kept[0]].shape[0]
                patches = np.lib.format.open_memmap(part, mode="w+", dtype=np.float32,
                                                    shape=(len(kept), n_recordings, n_frames, side, side))
            for index, mite_id in enumerate(kept):
                cut = recording[mite_id]
                patches[index, at, :, :cut.shape[1], :cut.shape[2]] = cut
            print(f"\r  cutting the patches: {at + 1} of {n_recordings} recordings", end="", flush=True)
        print()
        patches.flush()
        del patches
        part.replace(path)
        shapes_path.write_text(json.dumps([list(map(int, shape)) for shape in shapes]))
    return {"name": dataset["name"], "ids": kept, "times": np.array(dataset["times"], dtype=float),
            "moving": moving, "labelled": labelled, "shapes": json.loads(shapes_path.read_text()), "path": str(path)}


def patches_of(run, mite):
    """One mite's patches, (recordings, frames, side, side) float32, square
    (a quarter turn needs it: the odd row or column of plate is left out)."""
    side = min(run["shapes"][mite])
    return np.asarray(np.load(run["path"], mmap_mode="r")[mite, :, :, :side, :side])


# ---- moving a mite ----

def poses(condition, n_recordings, mite, seed=SEED):
    """(recordings, 3): the move (dx, dy, degrees turned) given the mite in
    each recording under `condition`; the same for the same mite and seed.
    Whole pixels and quarter turns, but for ANY_ANGLE."""
    rng = np.random.default_rng([seed, mite, CONDITIONS.index(condition)])
    distance, direction = rng.uniform(*SHIFT, n_recordings), rng.uniform(0, 2 * np.pi, n_recordings)
    shift = np.stack([distance * np.cos(direction), distance * np.sin(direction)], axis=1)
    out = np.zeros((n_recordings, 3))
    if condition == ANY_ANGLE:
        out[:, :2], out[:, 2] = shift, rng.uniform(0, 360, n_recordings)
        return out
    if condition in ("shifted", "moved"):
        out[:, :2] = np.round(shift)
    if condition in ("turned", "moved"):
        out[:, 2] = 90 * rng.integers(0, 4, n_recordings)
    return out


def move(frames, pose):
    """Every frame of one recording, (frames, side, side), the mite turned
    about the patch's centre and shifted by `pose` (dx, dy, degrees). Whole
    pixels and quarter turns move the pixels as they are; anything else is
    interpolated."""
    frames = np.asarray(frames, dtype=np.float32)
    if not np.any(pose):
        return frames
    if np.all(pose[:2] == np.round(pose[:2])) and pose[2] % 90 == 0:
        # np.rot90 turns from x to -y: counter-clockwise on the screen, as cv2's positive angle
        # the plate that comes in at an edge is that edge's mirror: brought round from the
        # other edge, a plate lit unevenly would bring a band of other light
        turned = np.ascontiguousarray(np.rot90(frames, int(pose[2] // 90) % 4, axes=(1, 2)))
        shift = np.float32([[1, 0, pose[0]], [0, 1, pose[1]]])
        return np.array([cv2.warpAffine(frame, shift, frame.shape[::-1], flags=cv2.INTER_NEAREST,
                                        borderMode=cv2.BORDER_REFLECT101) for frame in turned])
    side = frames.shape[1]
    matrix = cv2.getRotationMatrix2D(((side - 1) / 2, (side - 1) / 2), float(pose[2]), 1.0)
    matrix[:, 2] += pose[:2]
    return np.array([cv2.warpAffine(frame, matrix, (side, side), flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_REFLECT101) for frame in frames])


# ---- one recording's image ----

def on_mite(dark):
    """The mite and three pixels around it: where its legs can be."""
    return cv2.dilate((dark > MITE_DARK).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=3).astype(bool)


def leg_places(tracker, frames):
    """The legs found in one recording, (legs, 2): each leg's mean place in the
    body's own frame (along its long axis, across it towards the legs), so a
    mite shifted or turned keeps its legs where they were. A body's axis has
    no head: the side with the legs is taken as the front, which also undoes a
    turn of half a circle."""
    found = tracker.track(frames)
    axes = found.axis[np.isfinite(found.axis)]
    if not len(found) or not len(axes):
        return np.zeros((0, 2))
    xy, mass = np.nanmean(found.xy, axis=1), np.nanmean(found.mass, axis=1)
    axis = 0.5 * np.angle(np.exp(2j * axes).mean())
    along = xy[:, 0] * np.cos(axis) + xy[:, 1] * np.sin(axis)
    across = -xy[:, 0] * np.sin(axis) + xy[:, 1] * np.cos(axis)
    side = np.sign(np.sum(across * mass)) or 1.0
    return np.stack([along * side, across * side], axis=1)


# ---- two recordings compared ----

def _warp(degrees, from_centre, to_centre):
    """The 2x3 matrix that takes a point of the earlier image to the later one:
    turned by `degrees` about `from_centre`, which lands on `to_centre`."""
    turn = np.radians(degrees)
    rotation = np.array([[np.cos(turn), -np.sin(turn)], [np.sin(turn), np.cos(turn)]])
    return np.hstack([rotation, (to_centre - rotation @ from_centre)[:, None]]).astype(np.float32)


def align(earlier, later):
    """The later image laid on the earlier: (aligned image, turn in degrees).
    The turn is found every COARSE degrees on the darkness, the centres laid
    on each other, then refined with ECC (a shift and a turn)."""
    dark_a, plate_a = darkness(earlier)
    dark_b, plate_b = darkness(later)
    size = earlier.shape[::-1]
    centre_a, centre_b = centre(dark_a), centre(dark_b)
    region = on_mite(dark_a)
    errors = []
    for degrees in range(0, 360, COARSE):
        back = cv2.warpAffine(dark_b, _warp(degrees, centre_a, centre_b), size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
        errors.append(float(((dark_a - back)[region] ** 2).sum()))
    warp = _warp(COARSE * int(np.argmin(errors)), centre_a, centre_b)
    # ECC refines from the coarse fit what is left, a small shift and turn: it
    # reads its turn back as an arcsine, so it cannot start from one past 90 degrees.
    coarse = cv2.warpAffine(dark_b, warp, size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    try:
        _rho, rest = cv2.findTransformECC(dark_a, coarse, np.eye(2, 3, dtype=np.float32), cv2.MOTION_EUCLIDEAN,
                                          (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4), None, 1)
        warp = (np.vstack([warp, [0, 0, 1]]) @ np.vstack([rest, [0, 0, 1]]))[:2].astype(np.float32)
    except cv2.error:
        pass  # ECC did not converge: the coarse fit stands
    aligned = cv2.warpAffine(np.asarray(later, dtype=np.float32) * (plate_a / plate_b), warp, size,
                             flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT101)
    return aligned, float(np.degrees(np.arctan2(warp[1, 0], warp[0, 0])))


def aligned_change(earlier, later):
    """(change, turn): the mean absolute difference, in grey levels, of the
    earlier image and the later laid on it, over the mite in either and three
    pixels around it; and the turn that laid it."""
    aligned, turn = align(earlier, later)
    region = on_mite(darkness(earlier)[0]) | on_mite(darkness(aligned)[0])
    return float(np.abs(earlier - aligned)[region].mean()), turn


def leg_shift(earlier, later):
    """(largest, median) distance, in px, between the legs of two recordings
    (leg_places()) paired so the total is smallest, each capped at LEG_CAP;
    nan without a leg in either. A leg found in one only is not counted: the
    tracker finds a leg in one recording and misses it in the next often."""
    if not len(earlier) or not len(later):
        return np.nan, np.nan
    apart = np.minimum(np.linalg.norm(earlier[:, None] - later[None], axis=-1), LEG_CAP)
    rows, columns = linear_sum_assignment(apart)
    return float(apart[rows, columns].max()), float(np.median(apart[rows, columns]))


# ---- every mite, every condition ----

def measure_mite(job):
    """One mite, every condition: {condition: {images (recordings, h, w),
    aligned_change, turn, outline_change, leg_shift, leg_shift_median
    (recordings - 1), legs (recordings)}}."""
    run, mite = job
    patches = patches_of(run, mite)
    tracker = LegTracker()
    out = {}
    for condition in CONDITIONS:
        pose = poses(condition, len(patches), mite)
        images, legs = [], []
        for at, frames in enumerate(patches):
            moved = move(frames, pose[at])
            images.append(moved.mean(axis=0))
            legs.append(leg_places(tracker, moved))
        images = np.array(images)
        profiles = [outline(image) for image in images]
        aligned = np.array([aligned_change(images[at], images[at + 1]) for at in range(len(images) - 1)])
        shifts = np.array([leg_shift(legs[at], legs[at + 1]) for at in range(len(legs) - 1)])
        out[condition] = {"images": images, "aligned_change": aligned[:, 0], "turn": aligned[:, 1],
                          "outline_change": np.array([outline_change(profiles[at], profiles[at + 1])
                                                      for at in range(len(profiles) - 1)]),
                          "leg_shift": shifts[:, 0], "leg_shift_median": shifts[:, 1],
                          "legs": np.array([len(found) for found in legs])}
    return out


def measures(run, jobs=None):
    """{condition: {measure: (mites, recordings - 1), legs: (mites, recordings),
    turn: (mites, recordings - 1)}} for the whole run. Kept in results/scripts/."""
    source = "".join(inspect.getsource(module) for module in (sys.modules[__name__], leg_tracker, outline_module, recording_change))
    version = hashlib.sha1((source + run["path"]).encode("utf-8")).hexdigest()[:12]
    path = pipeline.SCRIPTS_OUTPUT / f"moved_mite_change-{version}.npz"
    if path.is_file():
        kept = np.load(path)
        return {condition: {name.split("/")[1]: kept[name] for name in kept.files if name.startswith(condition + "/")}
                for condition in CONDITIONS}
    with ProcessPoolExecutor(jobs or os.cpu_count()) as pool:
        per_mite = []
        for mite, found in enumerate(pool.map(measure_mite, [(run, mite) for mite in range(len(run["ids"]))])):
            per_mite.append(found)
            print(f"\r  measuring: {mite + 1} of {len(run['ids'])} mites", end="", flush=True)
    print()
    edge = PAD - MARGIN
    out = {}
    for condition in CONDITIONS:
        table = {name: np.array([found[condition][name] for found in per_mite])
                 for name in ("aligned_change", "turn", "outline_change", "leg_shift", "leg_shift_median", "legs")}
        table["image_change"] = RecordingChange(MARGIN).changes(
            [np.ascontiguousarray(found[condition]["images"][:, edge:-edge, edge:-edge]) for found in per_mite])
        out[condition] = table
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **{f"{condition}/{name}": values for condition, table in out.items() for name, values in table.items()})
    return out


# ---- alive or dead, by the labels ----

def pairs(run):
    """Which pairs of recordings (each with the next) show a mite alive or dead,
    by its labels, each (mites, recordings - 1): recording_change.groups()
    (alive, waiting, dead), with `long_dead` (dead, LONG_DEAD minutes or more
    after the last movement) and `alive_still` (alive, labelled still in both)."""
    moving, times = run["moving"], run["times"]
    group = recording_change.groups(moving, times, DEATH_MINUTES)
    moved = moving.any(axis=1)
    last = np.where(moved, moving.shape[1] - 1 - np.argmax(moving[:, ::-1], axis=1), 0)
    since = np.where(moved[:, None], times[None, :-1] - times[last][:, None], np.nan)
    with np.errstate(invalid="ignore"):
        group["long_dead"] = group["dead"] & (since >= LONG_DEAD)
    group["alive_still"] = group["alive"] & ~(moving[:, :-1] | moving[:, 1:])
    return group


def auc(high, low):
    """The chance a value of `high` is above one of `low`, ties half; nan
    values left out."""
    high, low = high[np.isfinite(high)], low[np.isfinite(low)]
    if not len(high) or not len(low):
        return np.nan
    ranks = rankdata(np.concatenate([high, low]))
    return float((ranks[:len(high)].sum() - len(high) * (len(high) + 1) / 2) / (len(high) * len(low)))


def summary(found, group, limit_share=99.0):
    """Per measure and condition: how well it tells alive pairs from dead ones,
    and how many dead pairs a move makes look changed. The limit of a measure
    is the `limit_share` percentile of its untouched dead pairs: what a mite
    left alone stays under (at the limit counts as over: leg_shift stops at
    LEG_CAP, where the limit can be)."""
    rows = []
    for measure in MEASURES:
        limit = np.nanpercentile(found["untouched"][measure][group["dead"]], limit_share)
        for condition in CONDITIONS:
            values = found[condition][measure]
            dead, alive = values[group["dead"]], values[group["alive"]]
            with np.errstate(invalid="ignore"):
                rows.append({
                    "measure": measure, "condition": condition,
                    "AUC alive / dead": auc(alive, dead),
                    "AUC alive still / long dead": auc(values[group["alive_still"]], values[group["long_dead"]]),
                    "dead over the limit": np.mean(dead[np.isfinite(dead)] >= limit),
                    "alive over the limit": np.mean(alive[np.isfinite(alive)] >= limit),
                    "measured, dead": np.isfinite(dead).mean(), "measured, alive": np.isfinite(alive).mean(),
                })
    return pd.DataFrame(rows).set_index(["measure", "condition"])


def main():
    run = load_run()
    print(f"{run['name']}: {len(run['ids'])} mites, {run['moving'].shape[1]} recordings")
    found = measures(run)
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.precision", 3):
        print(summary(found, pairs(run)))


if __name__ == "__main__":
    main()
