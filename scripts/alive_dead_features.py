"""What tells a live mite from a dead one, other than whether it moves within a
recording: the measurements behind notebooks/alive_dead_*.ipynb.

Every mite of the longest labelled run in calibration_data/ gets, per recording,
a set of numbers of three kinds (features()):

    silhouette   what the mite looks like in the mean image of the recording:
                 how much of its patch it darkens, its area, size, position,
                 direction, sharpness
    within       what happens over the frames of the recording: the movement
                 score in use, and how the pixels' noise is ordered in time
    between      what changed since the recording before: the whole image
                 (classes/recording_change.py), the position, the direction

and the notebooks ask of each how well it separates the recordings in which a
mite is alive from those in which it is dead (groups(), separation()).

The patches are those scripts/optuna_death_time.py cuts and keeps; the features
are kept beside them, so only the first run is slow (a few minutes).

    python scripts/alive_dead_features.py     # cuts and measures, prints the ranking
"""
import hashlib
import inspect
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from scipy.ndimage import median_filter
from scipy.optimize import nnls

import pipeline
from classes.analyzer import Analyzer
from classes.app_config import get_default_config
from classes.recording_change import RecordingChange, noise_floor
from optuna_death_time import MAX_PAD, load_dataset

CACHE = Path(tempfile.gettempdir()) / "varroa_death_time_patches"
EDGE = 6        # the outermost pixels of a patch: the plate, never the mite
MARGIN = 8      # pixels around a mite's box that still count as the mite (legs)
LONG_DEAD = 100  # recordings after its last movement from which a mite is taken as dead
BASELINE = 3    # recordings at the start a mite's silhouette is compared with


@dataclass
class Run:
    name: str
    mites: list           # their ids
    times: np.ndarray     # minutes, per recording
    moving: np.ndarray    # (mites, recordings), by the labels
    labelled: np.ndarray
    sizes: np.ndarray     # (mites, 2): each box's (height, width)
    path: str             # the patches, see optuna_death_time.load_dataset()

    def __post_init__(self):
        self.moved = self.moving.any(axis=1)
        n_recordings = self.moving.shape[1]
        # the last recording in which each mite moved, by the labels; -1 for none
        self.last = np.where(self.moved, n_recordings - 1 - np.argmax(self.moving[:, ::-1], axis=1), -1)
        self._patches = None

    def grey(self, mite):
        """One mite's patches, (recordings, frames, height, width) float32 in
        grey: its box with MAX_PAD pixels around it."""
        if self._patches is None:
            self._patches = np.load(self.path, mmap_mode="r")
        height, width = self.sizes[mite]
        return np.asarray(self._patches[mite, :, :, :height + 2 * MAX_PAD, :width + 2 * MAX_PAD]).mean(axis=-1)


def load_run(cache=CACHE, jobs=None):
    """The longest labelled run saved in calibration_data/."""
    saved = {summary["id"]: pipeline._read_dataset(summary["id"], pipeline.CALIBRATION_LIBRARY)
             for summary in pipeline.list_calibration_datasets()}
    dataset_id = max(saved, key=lambda key: len(saved[key]["times"]))
    Path(cache).mkdir(parents=True, exist_ok=True)
    dataset = load_dataset({"id": dataset_id}, cache, get_default_config().mite.stabilize_plate, jobs or os.cpu_count())
    return Run(dataset["name"], dataset["mites"], np.array(saved[dataset_id]["times"], dtype=float),
               dataset["moving"], dataset["labelled"], dataset["sizes"], dataset["path"])


# ---- what a mite looks like in one recording ----

def _frame(shape, width):
    """True on the outermost `width` pixels of an image."""
    mask = np.ones(shape, dtype=bool)
    mask[width:-width, width:-width] = False
    return mask


def darkness(images):
    """How much of the plate's light each pixel takes away, 0 to 1: `images`
    (..., height, width) divided by the plate's brightness around the mite (the
    median of the patch's outermost pixels), so a lamp a little brighter or
    darker in one recording changes nothing. Returns (darkness, plate)."""
    plate = np.median(images[..., _frame(images.shape[-2:], EDGE)], axis=-1)
    return np.clip(1 - images / plate[..., None, None], 0, None), plate


def silhouette_features(images):
    """Per recording, from one mite's mean images (recordings, height, width):

        silhouette  the sum of the darkness over the mite: the pixels it would
                    cover if it were black all over
        area_15, area_30  the pixels at least 15%, 30% darker than the plate
        peak        the darkness of its 30 darkest pixels
        size        how far its darkness lies from its centre (radius of gyration)
        x, y        its centre in the patch, in pixels
        angle       the direction of its long axis, in radians
        elongation  its long axis over its short one
        edge        the steepness of its outline (the 40 largest gradients)
    """
    dark, plate = darkness(images)
    inside = ~_frame(images.shape[-2:], MAX_PAD - MARGIN)
    weight = dark * inside
    total = weight.sum(axis=(1, 2))
    yy, xx = np.mgrid[:images.shape[1], :images.shape[2]].astype(np.float32)
    x = (weight * xx).sum(axis=(1, 2)) / total
    y = (weight * yy).sum(axis=(1, 2)) / total
    dx, dy = xx - x[:, None, None], yy - y[:, None, None]
    mxx, myy, mxy = ((weight * product).sum(axis=(1, 2)) / total for product in (dx * dx, dy * dy, dx * dy))
    spread = np.hypot((mxx - myy) / 2, mxy)
    gradient = [np.hypot(cv2.Sobel(image, cv2.CV_32F, 1, 0), cv2.Sobel(image, cv2.CV_32F, 0, 1)) for image in images]
    return {
        "silhouette": total,
        "area_15": (dark[:, inside] > 0.15).sum(axis=1).astype(float),
        "area_30": (dark[:, inside] > 0.30).sum(axis=1).astype(float),
        "peak": np.sort(dark.reshape(len(dark), -1), axis=1)[:, -30:].mean(axis=1),
        "size": np.sqrt(mxx + myy),
        "x": x, "y": y,
        "angle": 0.5 * np.arctan2(2 * mxy, mxx - myy),
        "elongation": np.sqrt(((mxx + myy) / 2 + spread) / np.maximum((mxx + myy) / 2 - spread, 1e-6)),
        "edge": np.array([np.sort(g.ravel())[-40:].mean() for g in gradient]),
        "plate": plate,
    }


# ---- what happens within one recording ----

def within_features(patches, images):
    """Per recording, from one mite's frames (recordings, frames, height, width)
    and their means:

        movement_score  the score in use (config.yaml's metric and parameters)
        order           whether the pixels' deviations from their mean follow
                        each other from frame to frame (lag-1 autocorrelation,
                        over the mite): about -1/frames for pure noise, higher
                        when something drifts slowly
        trend           how much of the pixels' variation over the frames is a
                        steady drift (F statistic of a straight line; 1 for noise)
        half_change     the largest differences between the mean of the first
                        and of the second half of the frames, smoothed
        one_pattern     the share of the variation that one single pattern of
                        change explains: high when the pixels change together
        noise_floor     classes/recording_change.py: what image_change would be
                        between two recordings of a mite that did nothing
    """
    mite = get_default_config().mite
    params = mite.params_for(mite.metric)
    pad = MAX_PAD - Analyzer.roi_padding(mite.metric, params)
    n_recordings, n_frames = patches.shape[:2]
    residual = patches - images[:, None]
    dark, _plate = darkness(images)
    time = np.arange(n_frames) - (n_frames - 1) / 2
    time /= np.sqrt((time ** 2).sum())
    out = {name: np.zeros(n_recordings) for name in ("movement_score", "order", "trend", "half_change", "one_pattern")}
    grow = np.ones((3, 3), np.uint8)
    for at in range(n_recordings):
        box = patches[at, :, pad:patches.shape[2] - pad, pad:patches.shape[3] - pad]
        out["movement_score"][at] = Analyzer._motion_score(box[..., None], mite.metric, params)
        # the mite and three pixels around it
        on_mite = cv2.dilate((dark[at] > 0.3 * dark[at].max()).astype(np.uint8), grow, iterations=3).astype(bool)
        on_mite &= ~_frame(on_mite.shape, MAX_PAD - MARGIN)
        here = residual[at][:, on_mite]                          # (frames, pixels)
        energy = (here ** 2).sum()
        out["order"][at] = (here[1:] * here[:-1]).sum() / energy
        drift = ((here * time[:, None]).sum(axis=0) ** 2).sum()
        out["trend"][at] = drift / max(energy - drift, 1e-9) * (n_frames - 2)
        half = cv2.GaussianBlur(patches[at, n_frames // 2:].mean(axis=0) - patches[at, :n_frames // 2].mean(axis=0), (0, 0), 1.0)
        out["half_change"][at] = np.sort(np.abs(half[on_mite]))[-10:].mean()
        singular = np.linalg.svd(here, compute_uv=False)
        out["one_pattern"][at] = singular[0] ** 2 / (singular ** 2).sum()
    out["noise_floor"] = noise_floor(patches[:, :, MAX_PAD:-MAX_PAD, MAX_PAD:-MAX_PAD])
    return out


# ---- what changed since the recording before ----

def _since_before(values):
    """(mites, recordings - 1) as (mites, recordings), nothing for the first."""
    return np.concatenate([np.full((len(values), 1), np.nan), values], axis=1)


def between_features(images, silhouettes):
    """Per mite and recording, against the recording before. The plate sits a
    fraction of a pixel elsewhere in each recording; every mite moves with it,
    so the median over the mites is taken out of each difference.

        image_change   classes/recording_change.py: the mean difference of the
                       two images, in grey levels
        moved_by       how far the mite's centre moved, in pixels
        turned_by      how far its long axis turned, in radians
        silhouette_change  how much its silhouette grew or shrank, in pixels
    """
    x, y, angle, total = (np.array([s[name] for s in silhouettes]) for name in ("x", "y", "angle", "silhouette"))
    dx, dy = np.diff(x, axis=1), np.diff(y, axis=1)
    dx, dy = dx - np.median(dx, axis=0), dy - np.median(dy, axis=0)
    turn = (np.diff(angle, axis=1) + np.pi / 2) % np.pi - np.pi / 2  # an axis has no head: the turn is within a quarter
    turn -= np.median(turn, axis=0)
    edge = MAX_PAD - MARGIN
    change = RecordingChange(MARGIN).changes([np.ascontiguousarray(image[:, edge:-edge, edge:-edge]) for image in images])
    return {"image_change": _since_before(change), "moved_by": _since_before(np.hypot(dx, dy)),
            "turned_by": _since_before(np.abs(turn)), "silhouette_change": _since_before(np.abs(np.diff(total, axis=1)))}


def features(run, cache=CACHE):
    """Every feature of every mite in every recording: {name: (mites,
    recordings)}, and `images`, each mite's mean image per recording (a list,
    as the mites' boxes differ in size). Kept in `cache`."""
    version = hashlib.sha1((inspect.getsource(sys.modules[__name__]) + run.path).encode("utf-8")).hexdigest()[:12]
    path = Path(cache) / f"alive_dead_features-{version}.npz"
    if path.is_file():
        kept = np.load(path)
        table = {name: kept[name] for name in kept.files if not name.startswith("image/")}
        return table, [kept[f"image/{mite}"] for mite in range(len(run.mites))]
    images, silhouettes, within = [], [], []
    for mite in range(len(run.mites)):
        patches = run.grey(mite)
        images.append(np.ascontiguousarray(patches.mean(axis=1)))
        silhouettes.append(silhouette_features(images[-1]))
        within.append(within_features(patches, images[-1]))
    table = {name: np.array([s[name] for s in silhouettes]) for name in silhouettes[0]}
    table.update({name: np.array([w[name] for w in within]) for name in within[0]})
    table.update(between_features(images, silhouettes))
    np.savez(path, **table, **{f"image/{mite}": image for mite, image in enumerate(images)})
    return table, images


def since_start(values, baseline=BASELINE):
    """Each mite's values against its own start: the change, as a share, from
    the median of its first `baseline` recordings. Negative: smaller than then."""
    return values / np.median(values[:, :baseline], axis=1, keepdims=True) - 1


def below_highest(values, window=5):
    """Each mite's values against the highest level it has had so far: the
    change, as a share, from the highest of its running medians (over the last
    `window` recordings) up to each recording. 0 while it is at its highest,
    negative below it. It looks only back, so it can be had during a run, and
    a mite whose first recordings were not its usual self is not held to them."""
    level = np.stack([median_filter(row, window, mode="nearest", origin=window // 2) for row in values])
    return values / np.maximum.accumulate(level, axis=1) - 1


# ---- the outline, followed directly ----

ANGLES = 64          # rays around the mite's centre
REACH = 13.0         # how far out a ray goes, in pixels
RAY_STEP = 0.25


def outline_profiles(run, table, cache=CACHE):
    """Each mite's outline in every frame, unrolled: (mites, recordings,
    frames, ANGLES) float32. From the mite's centre in that recording a ray
    goes out at each angle, and the darkness along it is summed: the length,
    in pixels, the mite would cover on that ray if it were black. A leg makes
    the rays that cross it longer, and when it moves, other rays are. Angle 0
    points right in the image, and they go on clockwise. Kept in `cache`."""
    source = inspect.getsource(outline_profiles) + inspect.getsource(darkness)
    version = hashlib.sha1((source + run.path).encode("utf-8")).hexdigest()[:12]
    path = Path(cache) / f"alive_dead_outlines-{version}.npy"
    if path.is_file():
        return np.load(path)
    angle = np.arange(ANGLES) * 2 * np.pi / ANGLES
    along = np.arange(0, REACH, RAY_STEP)
    out = None
    for mite in range(len(run.mites)):
        patches = run.grey(mite)
        if out is None:
            out = np.zeros((len(run.mites), *patches.shape[:2], ANGLES), dtype=np.float32)
        for at in range(len(patches)):
            dark = np.clip(1 - patches[at] / table["plate"][mite, at], 0, None).astype(np.float32)
            map_x = (table["x"][mite, at] + np.outer(np.cos(angle), along)).astype(np.float32)
            map_y = (table["y"][mite, at] + np.outer(np.sin(angle), along)).astype(np.float32)
            out[mite, at] = [cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR).sum(axis=1) * RAY_STEP for frame in dark]
    np.save(path, out)
    return out


def shape_only(profiles):
    """Outline profiles, or differences of them, (..., ANGLES), without what
    is the same all the way round (a brighter lamp, a bigger mite) and
    without a shift of the whole mite (longer on one side, shorter on the
    other): the first two harmonics in the angle are taken out. What is left
    is a change of shape, as a leg makes."""
    harmonics = np.fft.rfft(profiles, axis=-1)
    harmonics[..., :2] = 0
    return np.fft.irfft(harmonics, n=profiles.shape[-1], axis=-1)


def over_angles(profiles, width=3):
    """Outline profiles averaged over `width` neighbouring rays."""
    return sum(np.roll(profiles, shift, axis=-1) for shift in range(-(width // 2), width // 2 + 1)) / width


def outline_movement(differences, rays=4):
    """How far an outline moved, in pixels: the mean of the `rays` largest
    absolute differences (..., ANGLES) of shape_only() profiles."""
    return np.sort(np.abs(differences), axis=-1)[..., -rays:].mean(axis=-1)


# ---- alive or dead, by the labels ----

def groups(run, long_dead=LONG_DEAD):
    """Which recordings show a mite alive or dead, by its labels, each (mites,
    recordings):

        alive         up to its last labelled movement
        alive_still   alive, and labelled still in that recording
        alive_moving  alive, and labelled moving
        dead          `long_dead` recordings or more after its last movement
        waiting       in between: after the last movement, not yet taken as dead
        never         the mites never labelled moving, in none of the others
    """
    recording = np.arange(run.moving.shape[1])[None]
    last, moved = run.last[:, None], run.moved[:, None]
    alive = moved & (recording <= last)
    dead = moved & (recording >= last + long_dead)
    return {"alive": alive, "alive_still": alive & ~run.moving & run.labelled, "alive_moving": alive & run.moving,
            "dead": dead, "waiting": moved & ~alive & ~dead, "never": np.broadcast_to(~moved, run.moving.shape)}


def both(group):
    """The recordings of a group whose recording before is in it too: for the
    features that compare the two."""
    out = np.zeros_like(group)
    out[:, 1:] = group[:, 1:] & group[:, :-1]
    return out


def auc(positive, negative):
    """The chance that a value of `positive` is higher than one of `negative`
    (ties count half): 0.5 says nothing, 1 or 0 separates them fully."""
    positive, negative = positive[np.isfinite(positive)], negative[np.isfinite(negative)]
    if not len(positive) or not len(negative):
        return np.nan
    ranks = np.argsort(np.argsort(np.concatenate([positive, negative]), kind="stable"), kind="stable") + 1.0
    both_ = np.concatenate([positive, negative])
    # mean rank of ties
    order = np.argsort(both_, kind="stable")
    sorted_values = both_[order]
    starts = np.flatnonzero(np.concatenate([[True], sorted_values[1:] != sorted_values[:-1]]))
    ends = np.append(starts[1:], len(both_))
    for first, end in zip(starts, ends):
        ranks[order[first:end]] = (first + 1 + end) / 2
    return float((ranks[:len(positive)].sum() - len(positive) * (len(positive) + 1) / 2) / (len(positive) * len(negative)))


def auc_same_time(values, positive, negative, at_least=3):
    """auc() among the mites of one recording, averaged over the recordings
    that have `at_least` mites on each side (weighted by their pairs). Alive
    and dead are then compared at the same moment of the run, so nothing that
    drifts with the hours (the lamp, the room, the plate) can separate them."""
    scores, weights = [], []
    for at in range(values.shape[1]):
        p, n = values[positive[:, at], at], values[negative[:, at], at]
        p, n = p[np.isfinite(p)], n[np.isfinite(n)]
        if len(p) >= at_least and len(n) >= at_least:
            scores.append(auc(p, n))
            weights.append(len(p) * len(n))
    return float(np.average(scores, weights=weights)) if scores else np.nan


def auc_same_mite(values, positive, negative, at_least=5):
    """auc() within each mite (its own alive recordings against its own dead
    ones), averaged over the mites: nothing that differs from mite to mite (its
    size, its place on the plate) can separate them."""
    scores = [auc(values[mite, positive[mite]], values[mite, negative[mite]]) for mite in range(len(values))
              if np.isfinite(values[mite, positive[mite]]).sum() >= at_least
              and np.isfinite(values[mite, negative[mite]]).sum() >= at_least]
    return float(np.mean(scores)) if scores else np.nan


def distance(positive, negative):
    """How far apart the two are, in units of their own spread (d'): the
    difference of the medians over the root mean square of the two spreads,
    each 1.48 x the median absolute deviation."""
    positive, negative = positive[np.isfinite(positive)], negative[np.isfinite(negative)]
    spreads = [1.4826 * np.median(np.abs(values - np.median(values))) for values in (positive, negative)]
    return float((np.median(positive) - np.median(negative)) / max(np.sqrt(np.mean(np.square(spreads))), 1e-12))


def separation(values, positive, negative):
    """How well `values` (mites, recordings) tell the recordings of `positive`
    from those of `negative`: {auc, same_time, same_mite, distance}."""
    return {"auc": auc(values[positive], values[negative]),
            "same_time": auc_same_time(values, positive, negative),
            "same_mite": auc_same_mite(values, positive, negative),
            "distance": distance(values[positive], values[negative])}


# ---- when a mite died, by what its image does ----

def last_change(image_change, limit):
    """Per mite, the last recording whose image changed from the one before
    by more than `limit`, the one before it having changed too (one changed
    pair alone may be anything: a mite walking past, a speck of dust); 0 when
    there is none."""
    changed = np.nan_to_num(image_change) > limit
    twice = changed[:, 1:] & changed[:, :-1]
    last = image_change.shape[1] - 1 - np.argmax(twice[:, ::-1], axis=1)
    return np.where(twice.any(axis=1), last, 0)


def shrink_onset(shrunk, half_lives=(8, 16, 32, 64)):
    """Where one mite's silhouette starts to shrink: `shrunk` (its
    since_start(), per recording) is fitted with a level up to the onset and,
    from it, a fall that slows down (an exponential approach, plus a slow
    straight fall). Returns (onset, fit, drop): the recording, the fitted
    curve, and how far the exponential part falls."""
    values = median_filter(np.asarray(shrunk, dtype=float), 3, mode="nearest")
    at = np.arange(len(values))
    best = None
    for onset in range(len(values) - 5):
        since = np.clip(at - onset, 0, None)
        for half_life in half_lives:
            # level (either sign), exponential fall, straight fall: the falls can only fall
            terms = np.c_[np.ones(len(values)), -np.ones(len(values)), -(1 - np.exp(-since / half_life)), -since / 100.0]
            weights, _residual = nnls(terms, values)
            fit = terms @ weights
            error = float(((values - fit) ** 2).sum())
            if best is None or error < best[0]:
                best = (error, onset, fit, float(weights[2]))
    return best[1], best[2], best[3]


def main():
    run = load_run()
    table, _images = features(run)
    group = groups(run)
    relative = {"silhouette": since_start(table["silhouette"]), "area_15": since_start(table["area_15"]),
                "size": since_start(table["size"]), "elongation": since_start(table["elongation"])}
    print(f"{run.name}: {len(run.mites)} mites, {run.moving.shape[1]} recordings; alive against dead "
          f"({LONG_DEAD} recordings or more after the last movement)")
    print(f"  {'feature':<28}{'AUC':>7}{'same time':>11}{'same mite':>11}{'distance':>10}")
    rows = []
    for name, values in {"silhouette below its highest": below_highest(table["silhouette"]),
                         **{f"{k} since start": v for k, v in relative.items()}, **table}.items():
        pair = name in ("image_change", "moved_by", "turned_by", "silhouette_change")
        alive, dead = (both(group[side]) if pair else group[side] for side in ("alive", "dead"))
        rows.append((name, separation(values, alive, dead)))
    for name, result in sorted(rows, key=lambda row: -abs(row[1]["same_time"] - 0.5)):
        print(f"  {name:<28}{result['auc']:>7.3f}{result['same_time']:>11.3f}{result['same_mite']:>11.3f}{result['distance']:>10.2f}")


if __name__ == "__main__":
    main()
