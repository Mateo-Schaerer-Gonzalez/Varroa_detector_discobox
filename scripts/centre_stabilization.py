"""Does each mite's own centre take a shaking plate out as well as the plate's shift?

Every labelled (mite, recording) of every recording folder with ground truth is
read from its saved ROI video, shaken (or not), and scored with the score in use
(outline_variability) five ways:

    none          the patch cut where the mite was found, nothing moved back
    plate_ecc     moved back by the plate's shift: the median over all mites of
                  their phase correlation + ECC shifts (what the app did until
                  16 October 2026; ecc_shifts() below)
    plate_centre  moved back by the median over all mites of their centres' shifts
    own_centre    moved back by the mite's own centre's shift
                  (classes/plate_stabilizer.py, what the app does since)
    own_ecc       moved back by the mite's own phase correlation + ECC shift

The shakes are synthetic, made as a camera would see them (tune_optical_flow.shaken()):
per frame a random offset of standard deviation PX pixels, in quarter pixels,
the same for every mite (rigid), or one per plate (each plate its own, as when
the plates sit loose in the holder). Per method, how far the shift it moved the
patch back by was from the shake made is kept too (max over the frames, px).

    python scripts/centre_stabilization.py               # every dataset with ground truth
    python scripts/centre_stabilization.py --datasets sample_data

Writes results/scripts/centre_stabilization.csv.gz (one row per labelled mite,
recording and shake; read by notebooks/centre_stabilization.ipynb).
"""
import argparse
import os
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# The defaults everyone has, not this machine's config.yaml (only read).
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import cv2
import numpy as np
import pandas as pd

import pipeline
from classes import calibration
from classes.analyzer import Analyzer
from classes.app_config import METRIC, get_default_config
from classes.plate_stabilizer import PlateStabilizer, _gray, _patches
from classes.roi_recordings import RoiRecordings

METHODS = ("none", "plate_ecc", "plate_centre", "own_centre", "own_ecc")
# (name, kind, px): kind "rigid" shakes every mite alike, "plate" each plate on its own.
SHAKES = [("still", "rigid", 0.0), ("rigid 0.5 px", "rigid", 0.5), ("rigid 1 px", "rigid", 1.0),
          ("rigid 2 px", "rigid", 2.0), ("per plate 1 px", "plate", 1.0), ("per plate 2 px", "plate", 2.0)]
SENSOR_ZOOM = 4  # as tune_optical_flow.shaken(): offsets in quarter pixels
MEASURE_PAD = PlateStabilizer().pad
OUT = pipeline.SCRIPTS_OUTPUT / "centre_stabilization.csv.gz"


# --- a mite's shift, both ways ---------------------------------------------------------


def centre_shifts(frames, box):
    """Per frame, how far the mite's centre moved since the first frame, (N, 2),
    as the app measures it (PlateStabilizer)."""
    return PlateStabilizer()._mite_shifts(frames, box)


def ecc_shifts(frames, box, pad=MEASURE_PAD):
    """Per frame, how far the mite's patch moved since the first frame by phase
    correlation + ECC, (N, 2): PlateStabilizer._mite_shifts() until 16 October
    2026 (commit 4fb8b25), whose median over the mites was the plate's shift."""
    patches = _gray(_patches(frames, box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))
    window = cv2.createHanningWindow(patches.shape[:0:-1], cv2.CV_32F)  # the same for every frame
    return [PlateStabilizer._shift(patches[0], patch, window) for patch in patches]


# --- shaking -----------------------------------------------------------------------


def shake_offsets(rng, n_frames, px):
    """(N, 2): a random offset per frame, standard deviation `px`, in quarter pixels."""
    return np.round(rng.normal(0, px, (n_frames, 2)) * SENSOR_ZOOM) / SENSOR_ZOOM


def shaken(frames, offsets):
    """The frames, each moved by its offset as a camera would see it (as
    tune_optical_flow.shaken(), with the offsets given): enlarged SENSOR_ZOOM
    times, moved by whole enlarged pixels, each camera pixel averaged back."""
    out = np.empty_like(frames)
    for i, (frame, (dx, dy)) in enumerate(zip(frames, offsets * SENSOR_ZOOM)):
        big = cv2.resize(frame, None, fx=SENSOR_ZOOM, fy=SENSOR_ZOOM, interpolation=cv2.INTER_CUBIC)
        big = cv2.warpAffine(big, np.float32([[1, 0, dx], [0, 1, dy]]), big.shape[1::-1],
                             flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REFLECT101)
        out[i] = cv2.resize(big, frame.shape[1::-1], interpolation=cv2.INTER_AREA)
    return out


# --- one dataset's recordings --------------------------------------------------------

_datasets = {}


def _dataset(name):
    """(dataset, ROI reader, mites as (id, zone, ROI number, box in the ROI), labels by mite id)."""
    if name not in _datasets:
        dataset = pipeline._read_dataset(name)
        loader = RoiRecordings(dataset["data_dir"])
        saved = np.array(loader.boxes, dtype=float)
        mites = []
        for mite_id, box in pipeline.mite_boxes(dataset["mites"]).items():
            # the ROI video saved for this mite: its box, give or take a rounding
            number = int(np.abs(saved - np.array(box)).sum(axis=1).argmin())
            rx1, ry1, rx2, ry2 = loader.rois[number]
            width, height = loader.image_size
            margin = Analyzer.roi_padding(METRIC, get_default_config().mite.params_for(METRIC)) + pipeline.STABILIZE_MARGIN
            if not (rx1 <= max(0, box[0] - margin) and ry1 <= max(0, box[1] - margin)
                    and min(width, box[2] + margin) <= rx2 and min(height, box[3] + margin) <= ry2):
                raise ValueError(f"{name}: mite {mite_id}'s ROI does not hold its box and {margin} px round it")
            zone = next(m["zone_id"] for m in dataset["mites"] if m["id"] == mite_id)
            mites.append((mite_id, zone, number, (box[0] - rx1, box[1] - ry1, box[2] - rx1, box[3] - ry1)))
        n = len(dataset["recordings"])
        labels = {}
        for mite_id, truth in dataset["truth"].items():
            states = calibration.per_recording(truth, n)
            if not calibration.is_rejected(states):
                labels[mite_id] = states
        _datasets[name] = dataset, loader, mites, labels
    return _datasets[name]


def score_recordings(job):
    """Rows for the labelled mites of recordings `indices` of a dataset, every
    shake and method, and the seconds each way of measuring took."""
    name, indices, seed = job
    dataset, loader, mites, labels = _dataset(name)
    params = get_default_config().mite.params_for(METRIC)
    pad = Analyzer.roi_padding(METRIC, params)
    rows, seconds = [], {"ecc": 0.0, "centre": 0.0, "score": 0.0}
    for index in indices:
        recording = dataset["recordings"][index]["name"]
        crops = {mite_id: loader.read_mite(recording, number) for mite_id, _zone, number, _box in mites}
        scored = [m for m in mites if labels.get(m[0], [None] * (index + 1))[index] in (calibration.MOVING, calibration.STILL)]
        if not scored:
            continue
        for shake_number, (shake, kind, px) in enumerate(SHAKES):
            rng = np.random.default_rng([seed, zlib.crc32(name.encode()), index, shake_number])
            n_frames = len(next(iter(crops.values())))
            if kind == "rigid":
                plate = shake_offsets(rng, n_frames, px)
                offset_of = {mite_id: plate for mite_id, *_ in mites}
            else:
                zones = sorted({zone for _id, zone, *_ in mites})
                offsets = dict(zip(zones, (shake_offsets(rng, n_frames, px) for _ in zones)))
                offset_of = {mite_id: offsets[zone] for mite_id, zone, *_ in mites}
            frames = {mite_id: shaken(crops[mite_id], offset_of[mite_id]) if px else crops[mite_id]
                      for mite_id, *_ in mites}

            t = time.perf_counter()
            ecc = {mite_id: np.array(ecc_shifts(frames[mite_id], box), dtype=float)
                   for mite_id, _zone, _number, box in mites}
            seconds["ecc"] += time.perf_counter() - t
            t = time.perf_counter()
            centre = {mite_id: centre_shifts(frames[mite_id], box) for mite_id, _zone, _number, box in mites}
            seconds["centre"] += time.perf_counter() - t
            plate_ecc = np.median(np.array(list(ecc.values())), axis=0)
            plate_centre = np.median(np.array(list(centre.values())), axis=0)

            t = time.perf_counter()
            for mite_id, zone, _number, box in scored:
                shifts = {"none": np.zeros((n_frames, 2)), "plate_ecc": plate_ecc, "plate_centre": plate_centre,
                          "own_centre": centre[mite_id], "own_ecc": ecc[mite_id]}
                made = offset_of[mite_id] - offset_of[mite_id][0]  # the shake since the first frame
                row = {"dataset": name, "mite": mite_id, "zone": zone, "recording": index,
                       "moving": labels[mite_id][index] == calibration.MOVING, "shake": shake,
                       "made": float(np.hypot(*made.T).max())}
                f = frames[mite_id]
                for method, moved in shifts.items():
                    if method == "none":
                        x1, y1, x2, y2 = box
                        roi = f[:, max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
                    else:
                        roi = PlateStabilizer.cut(f, box, pad, moved)
                    row[method] = float(Analyzer._motion_score(roi, METRIC, params))
                    row[f"miss_{method}"] = float(np.hypot(*(moved - made).T).max())
                # how far its own shift strayed from the plate's, as Analyzer._follow_plate() reports it
                row["stray_ecc"] = float(np.hypot(*(ecc[mite_id] - plate_ecc).T).max())
                row["stray_centre"] = float(np.hypot(*(centre[mite_id] - plate_centre).T).max())
                rows.append(row)
            seconds["score"] += time.perf_counter() - t
    return rows, seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datasets", nargs="+", help="recording folders (default: every one with ground truth)")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count()))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    names = args.datasets or [d["id"] for d in pipeline.list_calibration_datasets()]
    jobs = []
    for name in names:
        n = len(pipeline._read_dataset(name)["recordings"])
        jobs += [(name, list(range(start, min(n, start + 2))), args.seed) for start in range(0, n, 2)]
    print(f"{len(names)} datasets, {len(jobs)} jobs on {args.jobs} processes")
    started = time.perf_counter()
    rows, seconds = [], {"ecc": 0.0, "centre": 0.0, "score": 0.0}
    with ProcessPoolExecutor(args.jobs) as pool:
        for done, (job_rows, job_seconds) in enumerate(pool.map(score_recordings, jobs), 1):
            rows += job_rows
            for key, value in job_seconds.items():
                seconds[key] += value
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} jobs, {time.perf_counter() - started:.0f} s")
    table = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    pd.Series(seconds).to_csv(args.out.with_name(args.out.name.replace(".csv.gz", "_seconds.csv")), header=["seconds"])
    print(f"{len(table)} rows -> {args.out}; seconds in all processes: {seconds}")


if __name__ == "__main__":
    main()
