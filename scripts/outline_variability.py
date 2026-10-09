"""Where on a mite do the pixels change? The measurements behind
notebooks/outline_variability.ipynb.

The outline_variability metric of classes/analyzer.py unrolls a mite around its
centre and takes the variance of its pixels over the frames along its outline.
Every mite of the longest labelled run in calibration_data/ gets that profile
for each recording (measure()): one variance for each of 64 directions. From it
come how much of the variance lies on one side (one_sided(), the vector sum
around the mite: the metric's score), how much the outline varies (amount()),
how clustered the variance is (one_sidedness(), share()) and on which side
(direction(), toward_own_side()).
measure() also keeps how far from the body's edge the variance lies and how
much the lamp flickers; disturbed() scores a sample of the recordings again
under a lamp that flickers more and on a plate that shakes.

The patches are those scripts/optuna_death_time.py cuts and keeps; what is
measured is kept beside them, so only the first run is slow (about a minute).

    python scripts/outline_variability.py     # measures, prints a summary
"""
import hashlib
import inspect
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import alive_dead_features as adf
import metric_agreement as ma
from classes import death_calibration
from classes.analyzer import Analyzer
from classes.death_calibration import LabelledRun
from optuna_death_time import MAX_PAD
from tune_optical_flow import shaken

METRIC = "outline_variability"
ANGLES = 64                                       # directions of the profile
ANGLE = np.arange(ANGLES) * 2 * np.pi / ANGLES    # 0: to the right in the image, going on clockwise
OFFSETS = np.arange(-5.0, 7.5, 0.5)               # pixels from the body's edge, outwards
# The scores disturbed() compares: {name: (metric, parameters that differ from config.yaml's)}.
DISTURBED = {"variability": ("variability", {}), "vector_variance": ("vector_variance", {}),
             "outline_movement": ("outline_movement", {}), METRIC: (METRIC, {}),
             f"{METRIC}, relative 1": (METRIC, {"relative": 1.0})}
WHOLE = "the outline's whole variance"            # amount(): not a metric of the app, set beside them in disturbed()


# ---- the outline of every mite in every recording ----

def _measure_mite(job):
    """One mite's outline in every recording: see measure()."""
    path, mite, height, width, params = job
    patches = np.load(path, mmap_mode="r")
    mine = np.asarray(patches[mite, :, :, :height + 2 * MAX_PAD, :width + 2 * MAX_PAD])
    profiles = np.zeros((len(mine), ANGLES), dtype=np.float32)
    by_distance = np.full((len(mine), len(OFFSETS)), np.nan, dtype=np.float32)
    lamp = np.zeros(len(mine), dtype=np.float32)
    frame = adf._frame(mine.shape[2:4], adf.EDGE)
    for at, roi in enumerate(mine):
        plate = np.median(roi[:, frame, 0], axis=1)
        lamp[at] = plate.std() / plate.mean()
        rays = Analyzer._outline_rays(roi, MAX_PAD)
        if rays is None:
            continue
        profiles[at] = Analyzer.outline_variability_profile(roi, params["width"], MAX_PAD)
        variance, edge, ray_step, _centre = rays
        for index, offset in enumerate(OFFSETS):
            point = edge + int(round(offset / ray_step))
            on_ray = (point >= 0) & (point < variance.shape[1])
            if on_ray.any():
                by_distance[at, index] = variance[on_ray, point[on_ray]].mean()
    return profiles, by_distance, lamp


def measure(run, cache=adf.CACHE, jobs=None):
    """What the metric sees of every mite in every recording, each (mites,
    recordings, ...):

        profiles     (..., ANGLES) the variance of the pixels on the outline
                     over the frames, in each direction from the mite's centre:
                     Analyzer.outline_variability_profile(), grey levels squared
        by_distance  (..., OFFSETS) the variance at each distance from the
                     body's edge, in the mean over the directions: negative
                     inside the body, positive outside; nan beyond the rays
        lamp         how much the plate's light varies over the frames of the
                     recording: its standard deviation as a share of the light

    Kept in `cache`."""
    params = ma.metric_params()[METRIC]
    source = inspect.getsource(Analyzer) + inspect.getsource(_measure_mite) + json.dumps(params, sort_keys=True) + run.path
    path = Path(cache) / f"outline_variability-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}.npz"
    if path.is_file():
        kept = np.load(path)
        return {name: kept[name] for name in kept.files}
    work = [(run.path, mite, *run.sizes[mite], params) for mite in range(len(run.mites))]
    with ProcessPoolExecutor(jobs or os.cpu_count()) as pool:
        rows = list(pool.map(_measure_mite, work))
    out = {name: np.array([row[index] for row in rows]) for index, name in enumerate(("profiles", "by_distance", "lamp"))}
    np.savez(path, **out)
    return out


# ---- what a profile says ----

def pull(profiles):
    """The outline's variances as vectors, each pointing in its direction,
    summed around the mite and divided by their number: a complex number
    (...), x + iy. Its length is the one-sided part of the variance, its angle
    the side that part is on."""
    return (profiles * np.exp(1j * ANGLE)).mean(axis=-1)


def amount(profiles):
    """How much the outline varies: the mean of its variances, wherever on it
    they are, in grey levels squared."""
    return profiles.mean(axis=-1)


def one_sided(profiles):
    """How much of the outline's variance lies on one side, in grey levels
    squared: the length of pull(), the vector sum around the mite. What is the
    same all round, or on two opposite sides, is not in it. The metric's
    score."""
    return np.abs(pull(profiles))


def one_sidedness(profiles):
    """How clustered the outline's variance is: the share of it that lies on
    one side, 0 to 1: one_sided() over amount(). 0: the same all the way
    round, or on two opposite sides. 1: all of it in one direction. The
    metric's score with relative 1."""
    total = amount(profiles)
    return np.where(total >= 1e-6, one_sided(profiles) / np.where(total >= 1e-6, total, 1), 0.0)


def score(profiles, relative=0.0):
    """The metric's score from the profiles, with its parameter `relative`:
    the one-sided part over the amount to that power."""
    total = amount(profiles)
    return np.where(total >= 1e-6, one_sided(profiles) / np.where(total >= 1e-6, total, 1) ** relative, 0.0)


def share(profiles, rays=ANGLES // 3):
    """Another way to say how clustered the outline's variance is: the share of
    it in the most variable stretch of `rays` neighbouring directions (a third
    of the outline): `rays` / ANGLES when it is the same all the way round, 1
    when all of it is in the stretch."""
    stretch = sum(np.roll(profiles, -shift, axis=-1) for shift in range(rays)).max(axis=-1)
    total = profiles.sum(axis=-1)
    return np.where(total > 0, stretch / np.where(total > 0, total, 1), rays / ANGLES)


def direction(profiles):
    """The side the one-sided part is on, in degrees: 0 to the right in the
    image, 90 down."""
    return np.degrees(np.angle(pull(profiles))) % 360


def toward_own_side(run, profiles, at_least=4):
    """Per mite and recording, whether the recording's variance is on the side
    the mite's variance is on in its other recordings labelled moving: the
    cosine of the angle between the two pull()s. 1: the same side, -1: the
    opposite one. nan for a mite with fewer than `at_least` such recordings."""
    arrows = pull(profiles)
    moving = np.where(run.moving, arrows, 0)
    others = moving.sum(axis=1, keepdims=True) - moving          # the recording itself left out
    cosine = (arrows * np.conj(others)).real / np.maximum(np.abs(arrows) * np.abs(others), 1e-12)
    enough = (run.moving.sum(axis=1, keepdims=True) - run.moving) >= at_least
    return np.where(enough, cosine, np.nan)


# ---- how well a score tells moving from still ----

def judged(values, run, still_called=0.001):
    """One score (mites, recordings) against the labels of a run:

        auc           the chance that a recording labelled moving scores higher
                      than one labelled still
        found         the share of the recordings labelled moving it finds at
                      the threshold that calls `still_called` of the still ones
                      moving
        death_error   the mean distance in recordings between a mite's death by
                      the score and by the labels, at the threshold that makes
                      it smallest (classes/death_calibration.py), and
        threshold     that threshold
        later, earlier  the mites the score has die later, earlier than the
                      labels at that threshold
        kappa         Cohen's kappa with the labels when it calls as many
                      recordings moving as they do (metric_agreement.kappa())
    """
    still = run.labelled & ~run.moving
    labelled = LabelledRun(values, run.moving, run.labelled)
    threshold, error = death_calibration.best_threshold([labelled])
    off = labelled.death_errors(values >= threshold)
    same_count = np.sort(values[run.labelled])[-int(run.moving.sum())]
    return {"auc": adf.auc(values[run.moving], values[still]),
            "found": float((values[run.moving] >= np.quantile(values[still], 1 - still_called)).mean()),
            "death_error": error, "threshold": threshold, "later": int((off > 0).sum()), "earlier": int((off < 0).sum()),
            "kappa": ma.kappa((values >= same_count)[run.labelled], run.moving[run.labelled])}


def drawn_again(first, second, run, times=500, seed=0):
    """How much of the difference between two scores is the luck of which mites
    were on the plate: the mites are drawn again `times` times (with
    replacement), and each time the AUC of `first` minus that of `second` is
    taken, and the difference of their mean death errors, each at its own best
    threshold on all the mites. Returns {auc, death_error}, each (times,)."""
    rng = np.random.default_rng(seed)
    still = run.labelled & ~run.moving
    errors = []
    for values in (first, second):
        labelled = LabelledRun(values, run.moving, run.labelled)
        threshold, _error = death_calibration.best_threshold([labelled])
        errors.append(np.abs(labelled.death_errors(values >= threshold)))
    out = {"auc": np.zeros(times), "death_error": np.zeros(times)}
    for again in range(times):
        mites = rng.integers(0, len(first), len(first))
        moving, quiet = run.moving[mites], still[mites]
        out["auc"][again] = adf.auc(first[mites][moving], first[mites][quiet]) - adf.auc(second[mites][moving], second[mites][quiet])
        out["death_error"][again] = errors[0][mites].mean() - errors[1][mites].mean()
    return out


# ---- a lamp that flickers, a plate that shakes ----

def sample(run, n_still=3000, seed=0):
    """The recordings disturbed() scores: every one labelled moving, and
    `n_still` of those labelled still, drawn at random: (mites, recordings)."""
    still = run.labelled & ~run.moving
    drawn = np.random.default_rng(seed).random(still.shape) < n_still / still.sum()
    return run.moving | (still & drawn)


def _disturb_mite(job):
    """One mite's scores in its sampled recordings, disturbed: {name: [score, ...]}."""
    path, mite, height, width, recordings, shake, flicker, seed, scores = job
    patches = np.load(path, mmap_mode="r")
    rng = np.random.default_rng(seed)
    out = {name: [] for name in scores}
    for at in recordings:
        roi = np.asarray(patches[mite, at, :, :height + 2 * MAX_PAD, :width + 2 * MAX_PAD])
        roi = shaken(roi, shake, rng)                       # without a shake too: the same resampling, moved by nothing
        if flicker:
            roi = roi * (1 + rng.normal(0, flicker, len(roi))).astype(np.float32)[:, None, None, None]
        for name, (metric, params) in scores.items():
            edge = MAX_PAD - Analyzer.roi_padding(metric, params)
            box = roi[:, edge:roi.shape[1] - edge, edge:roi.shape[2] - edge]
            out[name].append(float(Analyzer._motion_score(box, metric, params)))
        out.setdefault(WHOLE, []).append(float(Analyzer.outline_variability_profile(roi, scores[METRIC][1]["width"], MAX_PAD).mean()))
    return out


def disturbed(run, shake=0.0, flicker=0.0, cache=adf.CACHE, jobs=None, seed=0):
    """The scores of DISTURBED, and under WHOLE the outline's amount(), for the
    recordings of sample(), with the frames disturbed first: {name: (recordings
    of the sample,)}, in the order of np.argwhere(sample(run)).

    `shake`: every frame is moved by a random offset, in pixels (standard
    deviation), as a plate that shakes moves it (tune_optical_flow.shaken()).
    The patches were cut with the plate stabilised, and they are moved after
    that: it is a shake the stabiliser did not take out.
    `flicker`: every frame is made brighter or darker by a random share
    (standard deviation), as a lamp that flickers makes it.

    Kept in `cache`."""
    config = ma.metric_params()
    scores = {name: (metric, {**config[metric], **params}) for name, (metric, params) in DISTURBED.items()}
    chosen = sample(run, seed=seed)
    source = (inspect.getsource(Analyzer) + inspect.getsource(_disturb_mite) + inspect.getsource(shaken) + inspect.getsource(sample)
              + json.dumps([scores, shake, flicker, seed], sort_keys=True) + run.path)
    path = Path(cache) / f"outline_variability_disturbed-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}.npz"
    if path.is_file():
        kept = np.load(path)
        return {name: kept[name] for name in kept.files}
    work = [(run.path, mite, *run.sizes[mite], np.flatnonzero(chosen[mite]), shake, flicker, [seed, mite], scores)
            for mite in range(len(run.mites))]
    with ProcessPoolExecutor(jobs or os.cpu_count()) as pool:
        rows = list(pool.map(_disturb_mite, work))
    out = {name: np.concatenate([row[name] for row in rows]) for name in rows[0]}
    np.savez(path, **out)
    return out


def main():
    run = adf.load_run()
    seen = measure(run)
    profiles = seen["profiles"]
    table = ma.scores(run, legs=False)
    still = run.labelled & ~run.moving
    near = np.abs(OFFSETS) <= ma.metric_params()[METRIC]["width"]
    excess = np.nanmean(seen["by_distance"][run.moving], axis=0) - np.nanmean(seen["by_distance"][still], axis=0)
    print(f"{run.name}: {len(run.mites)} mites, {run.moving.shape[1]} recordings; {int(run.moving.sum())} labelled moving, {int(still.sum())} still")
    print(f"  of the variance a moving mite has more than a still one, {excess[near].sum() / excess.sum():.0%} is within "
          f"{ma.metric_params()[METRIC]['width']:g} px of the body's edge")
    print(f"  on one side: {np.median(one_sidedness(profiles)[run.moving]):.0%} of the outline's variance labelled moving, "
          f"{np.median(one_sidedness(profiles)[still]):.0%} still; in the most variable third of the outline: "
          f"{np.median(share(profiles)[run.moving]):.0%} and {np.median(share(profiles)[still]):.0%}")
    print(f"  {'score':<34}{'AUC':>8}{'found':>8}{'death error':>13}{'threshold':>11}{'later':>7}{'earlier':>9}{'kappa':>7}")
    rows = {"variability": table["variability"], "outline_movement": table["outline_movement"], METRIC: table[METRIC],
            f"{METRIC}, relative 1": one_sidedness(profiles), "the outline's whole variance": amount(profiles)}
    for name, values in rows.items():
        result = judged(values, run)
        print(f"  {name:<34}{result['auc']:>8.4f}{result['found']:>8.1%}{result['death_error']:>13.2f}{result['threshold']:>11.4g}"
              f"{result['later']:>7}{result['earlier']:>9}{result['kappa']:>7.3f}")
    runs = [run] + ma.other_runs(run)
    pooled = [LabelledRun(ma.scores(each, legs=False)[METRIC], each.moving, each.labelled) for each in runs]
    threshold, error = death_calibration.best_threshold(pooled)
    print(f"  best threshold for the deaths of all {len(runs)} labelled datasets: {threshold:.4g} (death error {error:.2f} recordings)")


if __name__ == "__main__":
    main()
