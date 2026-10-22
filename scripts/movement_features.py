"""Candidate features of a mite in a recording, to combine into one probability
that it moved (logistic regression). What is behind
notebooks/movement_probability.ipynb.

Every labelled session saved as ROIs is read, every mite in every recording,
its box followed as a live run follows it today (scripts/poke_run_followed.py
replays that from the blobs saved per recording). Every frame is used. The
sessions of 2025 are 30 frames at 30 fps, those of October 2026 10 at 10 fps
(one second each): the frame rate is a feature, so the model can weigh the
others by it. It is the same as the session's year, so it also stands for
whatever else differs between them.

Per mite and recording (cut as the app cuts it, stabilized):

    outline_variability, outline_movement, topN_variability, mean_diff,
    max_diff, vector_variance, topN_temporal_range, optical_flow
                    the metrics of classes/analyzer.py, with config.yaml's
                    parameters (outline_variability is the score in use)
    step            how much a step (a change that stays) explains of the
                    outline pixels' change, the 3 best, in noise variances
    spike           the largest single-frame jump of the outline pixels, the 3
                    best, in noise standard deviations
    noise           the camera's noise per frame on the bare plate (grey levels)
    shake           how far the mite's centre moved within the recording (px)
    stray           how far it moved apart from the median of the plate's mites (px)
    contrast        how dark the body is against the plate (0 to 1)
    area            the body's size (px)
    light           the plate's light round the mite (grey levels)
    neighbour       px from the mite's box centre to the nearest other blob
    differential    the benchmark's measure as a number: the largest denoised
                    change from the first frame on the mite's box (grey levels)
    fps             the recording's frame rate (and frames: one second of them)

The labels are the saved ground truth, and for Ground_truth_oct_26_final also
the recordings checked by eye on 20 October 2026 (EYE). The long run of
September 2026 is left out: its labels are the old detector's calls.

    python scripts/movement_features.py     # a few minutes
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

import pipeline
from pipeline.calibration import dataset_library, movement_score, poke_test
from classes import calibration
from classes.analyzer import Analyzer
from classes.benchmark import Benchmark
from classes.plate_stabilizer import PlateStabilizer
from classes.roi_recordings import open_recordings
from poke_run_followed import followed_boxes, index_order

SESSIONS = ("GT_oct_2", "ground_truth_60min", "ground_truth_90min", "sample_data", "Ground_truth_oct_26_final")
TEST = "Ground_truth_oct_26_final"
METRICS = ("outline_variability", "outline_movement", "topN_variability", "mean_diff", "max_diff",
           "vector_variance", "topN_temporal_range", "optical_flow")
STEP_PAD = 8         # px round the box the outline's steps are read in
RIM = 4              # its outermost pixels: bare plate
# Recordings of the test run checked by eye on the Discobox (recording counted from 0): moved or not.
EYE = {("3.5", 22): True, ("3.5", 33): False, ("4.4", 35): False, ("4.4", 42): True, ("4.4", 43): True,
       ("4.1", 40): True, ("4.6", 38): True, ("4.5", 31): False}
OUT = Path(__file__).resolve().parent.parent / "results" / "scripts" / "movement_features"


def folder(name):
    """recordings/<name>, or recordings/<name>/<name> as the October sessions were copied."""
    root = pipeline.RECORDINGS_ROOT / name
    return root if (root / "rois").is_dir() else root / name


def outline_steps(frames):
    """{step, spike, noise, contrast, area, light} of one mite's cut (frames, h, w)."""
    n = len(frames)
    mean = frames.mean(axis=0)
    rim = np.ones(mean.shape, bool)
    rim[RIM:-RIM, RIM:-RIM] = False
    light = float(np.median(mean[rim]))
    dark = np.clip(1 - mean / max(light, 1e-6), 0, None)
    body = (dark > 0.5 * dark.max()).astype(np.uint8)
    grow = np.ones((3, 3), np.uint8)
    edge = cv2.dilate(body, grow, iterations=3).astype(bool) & ~cv2.erode(body, grow, iterations=1).astype(bool) & ~rim
    noise = float(np.median(np.abs(np.diff(frames[:, rim], axis=0))) / 0.6745 / np.sqrt(2)) + 1e-6
    x = frames[:, edge]
    if not x.size:
        return {"step": 0.0, "spike": 0.0, "noise": noise, "contrast": 0.0, "area": 0.0, "light": light}
    total = ((x - x.mean(axis=0)) ** 2).sum(axis=0)
    best = np.zeros(x.shape[1])
    for split in range(2, n - 1):  # two frames at least on each side: one odd frame is no step
        before, after = x[:split], x[split:]
        best = np.maximum(best, total - ((before - before.mean(0)) ** 2).sum(0) - ((after - after.mean(0)) ** 2).sum(0))
    spike = np.abs(x - np.median(x, axis=0)).max(axis=0) / noise
    return {"step": float(np.sort(best)[-3:].mean() / noise ** 2), "spike": float(np.sort(spike)[-3:].mean()),
            "noise": noise, "contrast": float(dark[body.astype(bool)].mean()) if body.any() else 0.0,
            "area": float(body.sum()), "light": light}


def measure_recording(job):
    """Every feature of every mite in one recording: [{feature: value}] in the order of `numbers`."""
    data_dir, name, numbers, rois, boxes, blobs, params, fps = job
    loader = open_recordings(data_dir)
    frames = []
    for number in numbers:
        f = loader.read_mite(name, number).astype(np.float32)
        frames.append(f.reshape(f.shape[:3]))
    local = [(x1 - roi[0], y1 - roi[1], x2 - roi[0], y2 - roi[1]) for (x1, y1, x2, y2), roi in zip(boxes, rois)]
    stabilizer = PlateStabilizer()
    own = [stabilizer._mite_shifts(f, box) for f, box in zip(frames, local)]
    found = [shifts for shifts in own if shifts is not None]
    plate = np.median(found, axis=0) if found else np.zeros((len(frames[0]), 2))
    shifts = [plate if s is None else s for s in own]
    blobs = np.array(blobs or [], dtype=float).reshape(-1, 2)
    out = []
    for f, box, s, (x1, y1, x2, y2) in zip(frames, local, shifts, boxes):
        row = {"fps": float(fps)}
        for metric in METRICS:
            cut = PlateStabilizer.cut(f, box, Analyzer.roi_padding(metric, params[metric]), s)
            row[metric] = float(Analyzer._motion_score(cut, metric, params[metric]))
        cut = PlateStabilizer.cut(f, box, STEP_PAD, s)
        row.update(outline_steps(cut.reshape(cut.shape[:3])))
        row["shake"] = float(np.hypot(*(s - s[0]).T).max())
        row["stray"] = float(np.hypot(*(s - plate).T).max())
        centre = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
        distance = np.sort(np.hypot(*(blobs - centre).T)) if len(blobs) else np.array([np.inf])
        # the nearest blob is the mite itself (within a few px), unless it was not found
        others = distance[distance > 4]
        row["neighbour"] = float(min(others[0] if len(others) else 100.0, 100.0))
        differential = Benchmark.differential([np.clip(frame, 0, 255).astype(np.uint8) for frame in f])
        bx1, by1, bx2, by2 = box
        row["differential"] = float(differential[max(0, by1):max(0, by2), max(0, bx1):max(0, bx2)].max(initial=0))
        out.append(row)
    return out


def measure(name, params):
    data_dir = folder(name)
    data = dataset_library.read_dataset(name, data_dir.parent)
    loader = open_recordings(data_dir)
    index = loader.index
    order = index_order(data, index)
    rois = [index["mites"][number]["roi"] for number in order]
    placed = followed_boxes(data, index, order)
    jobs = [(str(data_dir), recording["name"], order, rois, placed[at], recording.get("blobs"), params, recording["fps"])
            for at, recording in enumerate(index["recordings"])]
    with ProcessPoolExecutor(8) as pool:
        per_recording = list(pool.map(measure_recording, jobs))
    n = len(data["times"])
    ids = [mite["id"] for mite in data["mites"]]
    states = [calibration.per_recording(data["truth"].get(mite_id), n) for mite_id in ids]
    if name == TEST:
        for (mite_id, at), moved in EYE.items():
            states[ids.index(mite_id)][at] = calibration.MOVING if moved else calibration.STILL
    poke = poke_test._poke_of(data) if name == TEST else None
    return {
        "name": name, "ids": ids, "times": data["times"],
        "states": [[state or "" for state in row] for row in states],
        "features": {feature: [[per_recording[at][m][feature] for at in range(len(per_recording))] for m in range(len(ids))]
                     for feature in per_recording[0][0]},
        "poke": {"bounds": {mite_id: poke.bounds(mite_id) for mite_id in ids if poke.pokes(mite_id)}} if poke else None,
        "eye": [[mite_id, at, moved] for (mite_id, at), moved in EYE.items()] if name == TEST else [],
    }


def main():
    params = {metric: movement_score.resolve_metric(metric, None)[1] for metric in METRICS}
    OUT.mkdir(parents=True, exist_ok=True)
    for name in SESSIONS:
        result = measure(name, params)
        (OUT / f"{name}.json").write_text(json.dumps(result), encoding="utf-8")
        print(f"{name}: {len(result['ids'])} mites, {len(result['times'])} recordings", flush=True)


if __name__ == "__main__":
    main()
