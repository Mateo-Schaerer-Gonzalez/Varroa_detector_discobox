"""The outline score as one coefficient of a discrete Fourier series, and the
rest of that series: can it tell a live mite from a dead one? Behind
notebooks/outline_fourier.ipynb.

The app's score (Analyzer._outline_variability) is harmonic 1 of the outline's
variance profile round the mite: score = |C_1| (report/fourier_and_brownian_motion.md).
The variance on each ray is itself a sum over the frames' frequencies
(Parseval: the variance of N frames is the sum of the power of their DFS terms
f = 1 .. N/2). So each (mite, recording) has a two-dimensional series,

    C[f, h] = (1/K) sum_k P[f, k] exp(-i h theta_k)

where P[f, k] is the power at frame frequency f on the outline of ray k (the
mean over the ray's outline points, in multiples of the noise floor), and
h = 0 .. HARMONICS the harmonic round the mite. Summed over f it is the series
of the app's profile, and |sum_f C[f, 1]| is the app's score (`check`).

Data, the frames cut and stabilised as the app cuts them (PlateStabilizer):

    Ground_truth_oct_26_final  poke test: alive through the round a mite moved
                               when poked (after recording 29), dead from the
                               recording after the round it did not
    the long run               by its labels, as scripts/alive_dead_features.py:
                               alive up to the last labelled movement, dead
                               LONG_DEAD recordings or more after it (the labels
                               are the detector's calls, CLAUDE.md)
    LABELLED                   moving or still by their labels only (no deaths):
                               what a rule built on the series costs in calls

    python scripts/outline_fourier.py          # writes results/scripts/outline_fourier_<dataset>.npz

Run in discobox_env (a few minutes; the mites in parallel).
"""
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import pipeline  # noqa: E402
from pipeline.calibration import dataset_library, score_cache  # noqa: E402
from classes.ground_truth.poke_test import MOVED, UNMOVED, PokeTest  # noqa: E402
from classes.scoring import analyzer as an  # noqa: E402
from classes.scoring.analyzer import Analyzer, NoNoiseWarning  # noqa: E402
from classes.scoring.plate_stabilizer import DARKEST_N, PlateStabilizer  # noqa: E402
from classes.storage import files  # noqa: E402
import script_data  # noqa: E402
from pipeline_optuna import PAD, _region  # noqa: E402

cv2.setNumThreads(1)
HARMONICS = an.ANGLES // 2   # every harmonic round the mite: 128 rays give h = 0 .. 64 (C_-h is the conjugate of C_h)
LONG_DEAD = 100     # the long run: recordings after its last movement from which a mite counts as dead
LONG_RUN = "test_run_2026-09-08_Mathis_last_dsRNA"
POKE_RUN = "Ground_truth_oct_26_final"
# the labelled moving/still datasets, for what a rule built on the series costs in calls
LABELLED = {"poke_test_oct": pipeline.RECORDINGS_ROOT / "poke_test_oct", "GT_oct_2": pipeline.RECORDINGS_ROOT / "GT_oct_2",
            "ground_truth_60min": pipeline.RECORDINGS_ROOT, "ground_truth_90min": pipeline.RECORDINGS_ROOT,
            "sample_data": pipeline.RECORDINGS_ROOT}
DATASETS = {POKE_RUN: pipeline.RECORDINGS_ROOT / POKE_RUN, LONG_RUN: pipeline.RECORDINGS_ROOT, **LABELLED}
OUT = pipeline.SCRIPTS_OUTPUT


# ---------------------------------------------------------------- the series of one recording
def outline_frames(roi):
    """Analyzer._outline_rays() up to the frames' rays: (unrolled (N, K, points),
    on_outline (K, points), noise floor, radius), or None for a patch without a
    mite. The radius is the mean distance of the body's edge from the centre, in
    pixels: the mite's size as the rays see it.
    A copy of the app's steps that keeps the frames instead of their variance."""
    gray = Analyzer.grey(roi).astype(np.float32)
    height, width = gray.shape[1:]
    lit = Analyzer._lit(gray)
    if lit is None:
        return None
    lit, light, rim = lit
    dark = np.clip(1 - lit / light, 0, None)
    still = dark.mean(axis=0)
    margin = max(PAD - 8, 0)
    near = np.zeros((height, width), dtype=bool)
    near[margin:height - margin, margin:width - margin] = True
    darkest = np.sort(still.ravel())[-DARKEST_N:].mean()
    if not near.any() or still[near].max() <= 0:
        return None
    dark_enough = (still > an.BODY_SHARE * darkest) & near
    pieces = cv2.connectedComponents(dark_enough.astype(np.uint8))[1]
    yy, xx = np.mgrid[:height, :width]
    from_middle = np.hypot(yy - (height - 1) / 2, xx - (width - 1) / 2)
    body = (pieces == pieces.ravel()[np.where(dark_enough, from_middle, np.inf).argmin()]).astype(np.uint8)
    weight = dark * body
    total = weight.sum(axis=(1, 2))
    if total.min() <= 0:
        return None
    centre_x, centre_y = (weight * xx).sum(axis=(1, 2)) / total, (weight * yy).sum(axis=(1, 2)) / total
    reach = min(an.REACH, centre_x.min(), centre_y.min(), width - 1 - centre_x.max(), height - 1 - centre_y.max())
    if reach < 2:
        return None
    angle = np.arange(an.ANGLES) * (2 * np.pi / an.ANGLES)
    along = np.arange(0, reach, an.RAY_STEP)
    ray_x, ray_y = np.outer(np.cos(angle), along), np.outer(np.sin(angle), along)
    unrolled = np.array([
        cv2.remap(frame, (x + ray_x).astype(np.float32), (y + ray_y).astype(np.float32), cv2.INTER_LINEAR)
        for frame, x, y in zip(lit, centre_x.tolist(), centre_y.tolist())
    ])
    past_body = 1 - unrolled.mean(axis=0) / light < an.EDGE_SHARE * darkest
    body_ends = np.where(past_body.any(axis=1), past_body.argmax(axis=1), len(along) - 1)
    away = np.abs(np.arange(unrolled.shape[2])[None] - body_ends[:, None]) * an.RAY_STEP
    on_outline = away <= 1.04   # the app's `width` (config.default.yaml)
    noise = float(np.median(lit[:, rim].var(axis=0)))
    return unrolled, on_outline, noise, float(body_ends.mean() * an.RAY_STEP)


def series(roi):
    """C (N // 2, HARMONICS + 1) complex: the outline's power at frame
    frequency f = 1 .. N // 2 (rows) taken apart round the mite (columns), in
    multiples of the noise floor; the noise floor; and the outline's radius
    (outline_frames()). Zeros where the app scores 0 (no mite found, frames all
    the same), and a radius NaN where no mite is found."""
    n = len(roi)
    empty = np.zeros((n // 2, HARMONICS + 1), np.complex64)
    found = outline_frames(roi)
    if found is None:
        return empty, 0.0, np.nan
    unrolled, on_outline, noise, radius = found
    spectrum = np.fft.rfft(unrolled.astype(np.float64), axis=0)[1:]
    power = np.abs(spectrum) ** 2 / n ** 2
    power[: (n - 1) // 2] *= 2          # f and -f; the Nyquist term (n even) once
    by_ray = (power * on_outline).sum(axis=2) / on_outline.sum(axis=1)   # (f, K)
    if by_ray.sum(axis=0).mean() < 1e-6:
        return empty, noise, radius
    if noise > 0:
        by_ray = by_ray / noise
    return (np.fft.fft(by_ray, axis=1)[:, : HARMONICS + 1] / by_ray.shape[1]).astype(np.complex64), noise, radius


# ---------------------------------------------------------------- a dataset
def _read(name):
    return dataset_library.read_dataset(name, DATASETS[name])


def _mite(job):
    """Every recording of one mite: (series, app score, noise floor, shake, radius),
    and the frames per recording. The shake is how far the stabiliser moved
    the mite's frames within the recording (the standard deviation of its
    shifts, x plus y, in pixels)."""
    name, index = job
    dataset = _read(name)
    loader = score_cache.open_recordings(Path(dataset["data_dir"]))
    mite = dataset["mites"][index]
    out, app, noise, shake, radius, length = [], [], [], [], [], 0
    for recording in range(len(dataset["recordings"])):
        frames, box = _region(dataset, dataset["data_dir"], loader, mite, recording)
        if frames.size == 0 or len(frames) < 2:
            out.append(None), app.append(np.nan), noise.append(np.nan), shake.append(np.nan), radius.append(np.nan)
            continue
        shifts = PlateStabilizer().shifts(frames, [box])[0]
        shake.append(float(np.std(shifts, axis=0).sum()))
        roi = PlateStabilizer.cut(frames, box, PAD, shifts)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NoNoiseWarning)
            app.append(float(Analyzer._motion_score(roi, "outline_variability")))
        c, floor, size = series(roi)
        out.append(c), noise.append(floor), radius.append(size)
        length = max(length, len(roi))
    return out, app, noise, shake, radius, length


def _poke_truth(dataset, mites, n):
    """alive, dead (mites, recordings) by the poke test."""
    poked = PokeTest(mites, n, files.read_json(Path(dataset["data_dir"]) / "poke_test.json"))
    alive, dead = np.zeros((len(mites), n), bool), np.zeros((len(mites), n), bool)
    index = {mite["id"]: i for i, mite in enumerate(mites)}
    for poke in poked.rounds:
        for mite_id, state in poke["states"].items():
            if state == MOVED:
                alive[index[mite_id], : poke["after"] + 1] = True
            elif state == UNMOVED:
                dead[index[mite_id], poke["after"] + 1:] = True
    return alive, dead


def _label_truth(moving, long_dead=LONG_DEAD):
    """alive, dead (mites, recordings) by the labels: up to the last movement,
    and `long_dead` recordings or more after it."""
    moved = moving.any(axis=1)
    last = np.where(moved, moving.shape[1] - 1 - np.argmax(moving[:, ::-1], axis=1), -1)[:, None]
    recording = np.arange(moving.shape[1])[None]
    return moved[:, None] & (recording <= last), moved[:, None] & (recording >= last + long_dead)


def build(name, workers):
    started = time.perf_counter()
    dataset = _read(name)
    mites, moving, labelled = script_data.labels_of(dataset)
    n = len(dataset["recordings"])
    if name == POKE_RUN:
        alive, dead = _poke_truth(dataset, mites, n)
    else:
        alive, dead = _label_truth(moving)
    keep = labelled.any(axis=1) | alive.any(axis=1) | dead.any(axis=1)
    order = {mite["id"]: i for i, mite in enumerate(dataset["mites"])}
    jobs = [(name, order[mite["id"]]) for mite, kept in zip(mites, keep) if kept]
    with ProcessPoolExecutor(workers) as pool:
        done = list(pool.map(_mite, jobs))
    length = max(d[5] for d in done)
    shape = (length // 2, HARMONICS + 1)
    c = np.array([[x if x is not None else np.full(shape, np.nan, np.complex64) for x in d[0]] for d in done])
    app, noise = np.array([d[1] for d in done]), np.array([d[2] for d in done])
    np.savez_compressed(
        OUT / f"outline_fourier_{name}.npz", series=c,
        app=app, noise=noise, shake=np.array([d[3] for d in done]), radius=np.array([d[4] for d in done]),
        mites=np.array([mite["id"] for mite, kept in zip(mites, keep) if kept]),
        moving=moving[keep], labelled=labelled[keep], alive=alive[keep], dead=dead[keep],
        times=np.array(dataset["times"], float), frames=length, fps=float(dataset["recordings"][0]["fps"]))
    total = np.abs(np.nansum(c[..., 1], axis=2))
    worst = np.nanmax(np.abs(total - app))
    print(f"{name}: {len(jobs)} mites x {n} recordings, {time.perf_counter() - started:.0f} s; "
          f"largest |app score - |sum_f C[f, 1]|| = {worst:.2e}", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in DATASETS:
        build(name, min(8, os.cpu_count()))


if __name__ == "__main__":
    main()
