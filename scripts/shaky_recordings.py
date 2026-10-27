"""Why does a threshold calibrated on the poke run call so many still mites moving on the long run?

Every labelled (mite, recording) of two datasets is read from its saved ROI
video and measured:

    the long run   test_run_2026-09-08_Mathis_last_dsRNA (10 frames a recording,
                   plates that shake), the guide for shaky recordings
    the poke run   poke_test_oct (3 s at 30 fps, 90 frames), the run the
                   threshold is calibrated on

Per (mite, recording): outline_variability stabilized four ways (as
scripts/centre_stabilization.py: `none`, `own_centre` the app's, `plate_centre`,
`plate_ecc`), the noise floor (Analyzer.plate_noise()) and the raw score, and
how the plate moved in the recording: `shake` (the most the plate's shift, the
median of every mite's centre shift, moved from the first frame), `jitter`
(the median step of the plate's shift from frame to frame), `own_shake` and
`stray` (the most the mite's own shift strayed from the plate's).

For the poke run also `short_*`: the same with the recording cut down to what the
long run records (10 frames, every second one: 0.6 s at 15 fps), so a difference
between the runs that is only their length shows.

    python scripts/shaky_recordings.py --poke-root %TEMP%/zzrc/gt

Writes results/scripts/shaky_recordings.csv.gz and, beside it, each row's outline
profile in shaky_recordings_profiles.npz (read by notebooks/shaky_recordings.ipynb).
"""
import argparse
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
# The defaults everyone has, not this machine's config.yaml (only read).
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pipeline  # noqa: E402
from pipeline import ground_truth  # noqa: E402
from pipeline.calibration import dataset_library  # noqa: E402
from classes.ground_truth import calibration  # noqa: E402
from classes.scoring.analyzer import Analyzer, NoNoiseWarning  # noqa: E402
from classes.app_config import METRIC, get_default_config  # noqa: E402
from classes.scoring.plate_stabilizer import PlateStabilizer  # noqa: E402
from classes.storage.roi_recordings import RoiRecordings  # noqa: E402
from centre_stabilization import centre_shifts, ecc_shifts  # noqa: E402

LONG_RUN = "test_run_2026-09-08_Mathis_last_dsRNA"
POKE_RUN = "poke_test_oct"
SHORT = slice(0, 20, 2)   # 10 frames, every second one: the long run's length at 15 fps
METHODS = ("none", "own_centre", "plate_centre", "plate_ecc")
OUT = pipeline.SCRIPTS_OUTPUT / "shaky_recordings.csv.gz"
# Per row of OUT, the outline's variance in each of 64 directions in multiples of
# the noise floor (Analyzer.outline_variability_profile() / plate_noise()), of the app's cut
PROFILES = pipeline.SCRIPTS_OUTPUT / "shaky_recordings_profiles.npz"

_datasets = {}


def _dataset(name, root):
    """(dataset, ROI reader, [(mite id, ROI number)], labels by mite id)."""
    if name not in _datasets:
        dataset = dataset_library.read_dataset(name, root)
        loader = RoiRecordings(dataset["data_dir"])
        saved = np.array(loader.boxes, dtype=float)
        mites = [(mite_id, int(np.abs(saved - np.array(box)).sum(axis=1).argmin()))
                 for mite_id, box in pipeline.mite_boxes(dataset["mites"]).items()]
        labels = {mite["id"]: states for mite, states in ground_truth.mite_states(dataset)}
        _datasets[name] = dataset, loader, mites, labels
    return _datasets[name]


def _box_in_roi(loader, recording, number):
    """The mite's box in its ROI of `recording` (where a live run followed it), or
    None where nothing of it was saved."""
    rect = loader.rects_in(recording)[number]
    if rect is None or rect[0] is None:
        return None
    placed = loader.placements(recording)
    box = loader.boxes[number] if placed is None else placed[number]
    if box is None:
        return None
    return tuple(int(round(v)) for v in (box[0] - rect[0], box[1] - rect[1], box[2] - rect[0], box[3] - rect[1]))


def _scores(frames, box, pad, params, shifts):
    """{method: outline_variability}, and the noise floor and raw score of the app's cut."""
    out = {}
    for method, moved in shifts.items():
        if method == "none":
            x1, y1, x2, y2 = box
            roi = frames[:, max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
        else:
            roi = PlateStabilizer.cut(frames, box, pad, moved)
        out[method] = float(Analyzer._motion_score(roi, METRIC, params))
        if method == "own_centre":
            out["noise"] = Analyzer.plate_noise(roi)
            out["profile"] = Analyzer.outline_variability_profile(roi, params["width"], params["pad"])
    out["raw"] = out["own_centre"] * out["noise"] if out["noise"] > 0 else out["own_centre"]
    return out


def _shifts(crops, boxes):
    """Per mite, {method: shifts}, and the plate's centre shift."""
    centre = {m: centre_shifts(crops[m], boxes[m]) for m in crops}
    ecc = {m: np.array(ecc_shifts(crops[m], boxes[m]), dtype=float) for m in crops}
    found = [s for s in centre.values() if s is not None]
    plate_centre = np.median(found, axis=0) if found else np.zeros((len(next(iter(crops.values()))), 2))
    centre = {m: plate_centre if s is None else s for m, s in centre.items()}
    plate_ecc = np.median(list(ecc.values()), axis=0)
    return {m: {"none": np.zeros_like(plate_centre), "own_centre": centre[m], "plate_centre": plate_centre,
                "plate_ecc": plate_ecc} for m in crops}, plate_centre


def score_recording(job):
    """Rows for the labelled mites of one recording."""
    name, root, index = job
    warnings.simplefilter("ignore", NoNoiseWarning)
    dataset, loader, mites, labels = _dataset(name, root)
    params = get_default_config().mite.params_for(METRIC)
    pad = Analyzer.roi_padding(METRIC, params)
    recording = dataset["recordings"][index]["name"]
    crops, boxes = {}, {}
    for mite_id, number in mites:
        box = _box_in_roi(loader, recording, number)
        if box is None:
            continue
        frames = loader.read_mite(recording, number).astype(np.float32)
        if not len(frames) or frames.max() <= 0:
            continue
        crops[mite_id], boxes[mite_id] = frames, box
    if not crops:
        return []
    lengths = {"": slice(None)} if name != POKE_RUN else {"": slice(None), "short_": SHORT}
    measured = {}
    for prefix, frames_kept in lengths.items():
        cut = {m: f[frames_kept] for m, f in crops.items()}
        shifts, plate = _shifts(cut, boxes)
        steps = np.hypot(*np.diff(plate, axis=0).T)
        moves = {"shake": float(np.hypot(*plate.T).max()), "jitter": float(np.median(steps)) if len(steps) else 0.0}
        for mite_id in cut:
            own = shifts[mite_id]["own_centre"]
            row = {f"{prefix}{k}": v for k, v in _scores(cut[mite_id], boxes[mite_id], pad, params, shifts[mite_id]).items()}
            # the outline's variance in each of the 64 directions, in multiples of the noise floor
            noise = row[f"{prefix}noise"]
            row[f"{prefix}profile"] = row[f"{prefix}profile"] / noise if noise > 0 else row[f"{prefix}profile"]
            row.update({f"{prefix}{k}": v for k, v in moves.items()})
            row[f"{prefix}own_shake"] = float(np.hypot(*own.T).max())
            row[f"{prefix}stray"] = float(np.hypot(*(own - plate).T).max())
            measured.setdefault(mite_id, {}).update(row)
    rows = []
    for mite_id, row in measured.items():
        state = labels.get(mite_id, [None] * (index + 1))[index]
        zone = next(m["zone_id"] for m in dataset["mites"] if m["id"] == mite_id)
        rows.append({"dataset": name, "mite": mite_id, "zone": zone, "recording": index,
                     "minutes": dataset["times"][index], "frames": len(crops[mite_id]),
                     "labelled": state in (calibration.MOVING, calibration.STILL),
                     "moving": state == calibration.MOVING, **row})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--poke-root", type=Path, default=pipeline.RECORDINGS_ROOT,
                        help="the folder poke_test_oct is in (it sits one folder too deep in recordings/)")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count()))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    jobs = []
    for name, root in ((LONG_RUN, pipeline.RECORDINGS_ROOT), (POKE_RUN, args.poke_root)):
        dataset = dataset_library.read_dataset(name, root)
        jobs += [(name, root, index) for index in range(len(dataset["recordings"]))]
    rows, started = [], time.perf_counter()
    with ProcessPoolExecutor(args.jobs) as pool:
        for done, part in enumerate(pool.map(score_recording, jobs, chunksize=4), 1):
            rows += part
            if done % 50 == 0:
                print(f"  {done}/{len(jobs)} recordings, {time.perf_counter() - started:.0f} s", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # the profiles go beside the table, one row each in the table's order (short ones NaN for the long run)
    missing = np.full(64, np.nan)
    profiles = {column: np.array([row.pop(column, missing) for row in rows]) for column in ("profile", "short_profile")}
    pd.DataFrame(rows).to_csv(args.out, index=False)
    np.savez_compressed(PROFILES, **profiles)
    print(f"{len(rows)} rows -> {args.out}, {PROFILES}")


if __name__ == "__main__":
    main()
