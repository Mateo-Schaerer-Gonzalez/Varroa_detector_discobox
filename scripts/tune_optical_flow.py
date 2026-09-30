"""Search the parameters of the optical_flow movement score against the saved ground truth.

Every (mite, recording) labelled moving or still in calibration_data/ is scored
with Analyzer.dense_optical_flow for each combination in the grid below, exactly
as a calibration would score it. Combinations are ranked by AUC (threshold
free); each also gets its best threshold (Youden's J) and the accuracy there.

With few labelled mites the top of a big grid partly fits noise, so the mites
are also split into two halves: the best combination on one half is scored on
the other. If that held-out AUC is far below the top AUC, trust neither.

    python scripts/tune_optical_flow.py                 # the full grid
    python scripts/tune_optical_flow.py --samples 100   # 100 random combinations
    python scripts/tune_optical_flow.py --shake 1       # as if the plate shook

`pad` grows each mite's patch by that many pixels on each side, as the app does
when the metric's pad parameter is set.

--shake PX moves the whole plate by a random offset (standard deviation PX
pixels) in every frame, the same for every mite, before the patches are cut: a
still mite on a shaking plate should stay still, which `stabilize` 1 is for.

The ranking is written to calibration_data/reports/optical_flow_tuning_<time>.csv.
"""
import argparse
import csv
import itertools
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

import pipeline
from classes import calibration
from classes.analyzer import Analyzer
from classes.app_config import get_default_config
from classes.data_loader import DataLoader
from classes.plate_stabilizer import PlateStabilizer

METRIC = "optical_flow"

# poly_sigma follows poly_n as the OpenCV docs advise (5 -> 1.1, 7 -> 1.5).
GRID = {
    "pad": [0, 4, 8, 12],
    "window": [3, 5, 9],
    "n": [10, 20, 40],
    "step": [3, 5, 8, 10],
    "winsize": [7, 9, 15],
    "levels": [1, 2],
    "poly_n": [5, 7],
    "iterations": [3],
    "stabilize": [0, 1],
}
POLY_SIGMA = {5: 1.1, 7: 1.5}


def combinations(samples, seed):
    names = list(GRID)
    combos = [dict(zip(names, values)) for values in itertools.product(*GRID.values())]
    for combo in combos:
        combo["poly_sigma"] = POLY_SIGMA[combo["poly_n"]]
    if samples and samples < len(combos):
        combos = random.Random(seed).sample(combos, samples)
    return combos


SENSOR_ZOOM = 4


def shaken(frames, shake, rng):
    """The frames with the whole plate moved by a random offset in each: a
    shaking plate. Edges are mirrored in, so no black border appears.

    Each frame is moved as a camera would see it: enlarged SENSOR_ZOOM times,
    moved by whole enlarged pixels, and each camera pixel then averaged over
    its area. Moving the frame itself by a fraction of a pixel would instead
    blur it by an amount that changes with every frame, a change no camera
    makes."""
    out = np.empty_like(frames)
    for i, frame in enumerate(frames):
        dx, dy = np.round(rng.normal(0, shake, 2) * SENSOR_ZOOM)
        big = cv2.resize(frame, None, fx=SENSOR_ZOOM, fy=SENSOR_ZOOM, interpolation=cv2.INTER_CUBIC)
        big = cv2.warpAffine(big, np.float32([[1, 0, dx], [0, 1, dy]]), big.shape[1::-1],
                             flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REFLECT101)
        out[i] = cv2.resize(big, frame.shape[1::-1], interpolation=cv2.INTER_AREA)
    return out


def load_observations(pads, shake=0.0, seed=0, stabilize=None):
    """For every labelled (mite, recording) of every saved dataset whose
    recordings can still be read: its ROI cut at each padding in `pads`
    ({pad: [roi, ...]}), whether it moved, which mite it is ("<dataset>/<mite>")
    and the recording's index in its dataset. With `shake`, the plate is shaken
    first (see shaken()). With `stabilize` (by default, config.yaml's
    mite.stabilize_plate) the ROIs follow the plate as an analysis run cuts them."""
    if stabilize is None:
        stabilize = get_default_config().mite.stabilize_plate
    rng = np.random.default_rng(seed)
    rois, moving, mites, recording_index = {pad: [] for pad in pads}, [], [], []
    for summary in pipeline.list_calibration_datasets():
        dataset = pipeline._read_dataset(summary["id"], pipeline.CALIBRATION_LIBRARY)
        recordings_dir = pipeline._recordings_dir(dataset["data_dir"], pipeline.CALIBRATION_LIBRARY)
        if not recordings_dir.is_dir():
            print(f"  skipping {dataset['name']}: its recordings are gone")
            continue
        n_recordings = len(dataset["times"])
        labelled = {}
        for mite in dataset["mites"]:
            states = calibration.per_recording(dataset["truth"].get(mite["id"]), n_recordings)
            if not calibration.is_rejected(states):
                labelled[mite["id"]] = (mite, states)
        if not labelled:
            continue

        # The same boxes as pipeline._score_mites() cuts, at the largest padding,
        # with room around them for the shake and the stabilizer.
        margin = pipeline.STABILIZE_MARGIN if (shake or stabilize) else 0
        boxes = pipeline.mite_boxes([m for m, _states in labelled.values()], max(pads))
        x0 = max(0, min(b[0] for b in boxes.values()) - margin)
        y0 = max(0, min(b[1] for b in boxes.values()) - margin)
        x_end = max(b[2] for b in boxes.values()) + margin
        y_end = max(b[3] for b in boxes.values()) + margin
        local = {mite_id: (x1 - x0, y1 - y0, x2 - x0, y2 - y0) for mite_id, (x1, y1, x2, y2)
                 in pipeline.mite_boxes([m for m, _states in labelled.values()]).items()}

        loader = DataLoader(recordings_dir, grayscale=False)
        for index, recording in enumerate(dataset["recordings"]):
            frames = loader.load_recording_region(recording["name"], x0, y0, x_end, y_end)
            if shake:
                frames = shaken(frames, shake, rng)
            shifts = PlateStabilizer().shifts(frames, list(local.values())) if stabilize else None
            for mite_id, (x1, y1, x2, y2) in local.items():
                state = labelled[mite_id][1][index]
                if state not in (calibration.MOVING, calibration.STILL):
                    continue
                for pad in pads:
                    if shifts is None:
                        cut = frames[:, max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
                    else:
                        cut = PlateStabilizer.cut(frames, (x1, y1, x2, y2), pad, shifts)
                    rois[pad].append(np.ascontiguousarray(cut))
                moving.append(state == calibration.MOVING)
                mites.append(f"{summary['id']}/{mite_id}")
                recording_index.append(index)
        print(f"  {dataset['name']}: {len(labelled)} mites")
    return rois, np.array(moving), mites, recording_index


def score_all(rois, metric, params):
    return np.array([Analyzer._motion_score(roi, metric, params) for roi in rois])


def evaluate(scores, moving):
    threshold = calibration.best_threshold(scores, moving)
    return {
        "auc": calibration.auc(scores, moving),
        "threshold": threshold,
        "accuracy": calibration.confusion(scores, moving, threshold)["accuracy"],
    }


# Worker processes get the observations once, not with every combination.
_ROIS = None


def _init_worker(rois):
    global _ROIS
    _ROIS = rois


def _score_combo(params):
    return score_all(_ROIS[params["pad"]], METRIC, params)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", type=int, default=0, help="score this many random combinations instead of all")
    parser.add_argument("--jobs", type=int, default=os.cpu_count(), help="worker processes")
    parser.add_argument("--shake", type=float, default=0.0, help="shake the plate by this many pixels (std) per frame")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--stabilize-plate", type=int, choices=[0, 1], default=None,
                        help="follow a shaking plate (default: config.yaml's mite.stabilize_plate)")
    parser.add_argument("--top", type=int, default=15, help="rows of the ranking to print")
    args = parser.parse_args()

    config = get_default_config().mite
    baseline_params = config.params_for(config.metric)
    baseline_pad = Analyzer.roi_padding(config.metric, baseline_params)

    print("Loading labelled observations...")
    rois, moving, mites, _recordings = load_observations(sorted({*GRID["pad"], baseline_pad}), args.shake, args.seed, args.stabilize_plate)
    if not calibration.has_both_classes(moving):
        sys.exit("Need both moving and still labels in calibration_data/ to tune anything.")
    print(f"{len(moving)} observations ({moving.sum()} moving, {(~moving).sum()} still), {len(set(mites))} mites")
    for pad, cuts in rois.items():
        print(f"  pad {pad:>2}: ROIs about {int(np.median([r.shape[1] for r in cuts]))} px across")

    # Two halves by mite, so one mite's recordings never sit on both sides.
    keys = sorted(set(mites))
    random.Random(args.seed).shuffle(keys)
    half_a = set(keys[::2])
    in_a = np.array([m in half_a for m in mites])

    baseline = evaluate(score_all(rois[baseline_pad], config.metric, baseline_params), moving)
    print(f"\nBaseline (config.yaml): {config.metric} {baseline_params}  "
          f"AUC {baseline['auc']:.3f}  accuracy {baseline['accuracy']:.3f} at {baseline['threshold']:.3g}")

    combos = combinations(args.samples, args.seed)
    print(f"\nScoring {len(combos)} combinations with {args.jobs} workers...")
    started = time.time()
    results = []
    with ProcessPoolExecutor(args.jobs, initializer=_init_worker, initargs=(rois,)) as pool:
        for done, (params, scores) in enumerate(zip(combos, pool.map(_score_combo, combos)), 1):
            if not np.isfinite(scores).all():
                continue  # e.g. a step longer than a recording
            row = {**params, **evaluate(scores, moving)}
            row["auc_a"] = calibration.auc(scores[in_a], moving[in_a]) if calibration.has_both_classes(moving[in_a]) else np.nan
            row["auc_b"] = calibration.auc(scores[~in_a], moving[~in_a]) if calibration.has_both_classes(moving[~in_a]) else np.nan
            results.append(row)
            if done % 25 == 0 or done == len(combos):
                print(f"  {done}/{len(combos)}  ({time.time() - started:.0f} s)")

    results.sort(key=lambda r: r["auc"], reverse=True)
    names = [*GRID, "poly_sigma"]
    print(f"\nTop {args.top} by AUC (auc_a / auc_b: the two halves of the mites):")
    print("  ".join(f"{h:>8}" for h in [*names, "auc", "auc_a", "auc_b", "accuracy", "threshold"]))
    for r in results[:args.top]:
        print("  ".join(f"{r[k]:>8.3g}" for k in [*names, "auc", "auc_a", "auc_b", "accuracy", "threshold"]))

    # Honest estimate: pick on one half, judge on the other.
    for pick, judge in (("auc_a", "auc_b"), ("auc_b", "auc_a")):
        best = max(results, key=lambda r: r[pick])
        print(f"Best on half {pick[-1]} ({best[pick]:.3f}) scores {best[judge]:.3f} on half {judge[-1]}")

    best = results[0]
    params = {k: best[k] for k in names}
    print("\nFor config.yaml (or save it from the calibration report):")
    print(f"  metric: \"{METRIC}\"\n  metric_thresholds: {{..., {METRIC}: {best['threshold']:.4g}}}")
    print(f"  metric_params: {{..., {METRIC}: {params}}}")

    out = pipeline.CALIBRATION_REPORTS / f"optical_flow_tuning_{datetime.now():%Y-%m-%d_%H-%M-%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    print(f"\nFull ranking: {out}")


if __name__ == "__main__":
    main()
