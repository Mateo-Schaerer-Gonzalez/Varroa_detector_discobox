"""How long, and how fast, a recording must be to tell a moving mite from a still
one. What is behind section 9 of notebooks/poke_run_followed.ipynb.

The labelled sessions of 2025 were recorded at 30 fps for 1 s (30 frames). Each
recording is scored again, with the score in use and the mites followed
(scripts/poke_run_followed.py), cut down to shorter and slower recordings of
itself: the first 1/3, 1/2, 2/3 or all of the second, at 10, 15 or 30 fps
(every third, second or every frame). The same mites, the same labels: only
the recording changes.

    python scripts/recording_length.py      # a minute or two
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import pipeline
from classes import calibration
from classes.analyzer import Analyzer
from classes.app_config import METRIC
from classes.plate_stabilizer import PlateStabilizer
from classes.roi_recordings import open_recordings
from poke_run_followed import followed_boxes, index_order

SESSIONS = ("ground_truth_60min", "ground_truth_90min", "sample_data")
RECORDED_FPS = 30
FPS = (10, 15, 30)
SECONDS = (1 / 3, 1 / 2, 2 / 3, 1.0)
WAYS = {f"{fps} fps, {seconds:.2f} s": (fps, seconds) for fps in FPS for seconds in SECONDS}
OUT = Path(__file__).resolve().parent.parent / "results" / "scripts" / "recording_length.json"


def score_recording(job):
    """{way: [score of each mite]} of one recording."""
    data_dir, name, numbers, rois, boxes, params = job
    loader = open_recordings(data_dir)
    recorded = [loader.read_mite(name, number).astype(np.float32) for number in numbers]
    recorded = [f.reshape(f.shape[:3]) for f in recorded]
    local = [(x1 - roi[0], y1 - roi[1], x2 - roi[0], y2 - roi[1]) for (x1, y1, x2, y2), roi in zip(boxes, rois)]
    out = {}
    for way, (fps, seconds) in WAYS.items():
        frames = [f[:int(round(seconds * RECORDED_FPS)):RECORDED_FPS // fps] for f in recorded]
        own = [PlateStabilizer()._mite_shifts(f, box) for f, box in zip(frames, local)]
        found = [shifts for shifts in own if shifts is not None]
        plate = np.median(found, axis=0) if found else np.zeros((len(frames[0]), 2))
        pad = Analyzer.roi_padding(METRIC, params)
        out[way] = [float(Analyzer._motion_score(PlateStabilizer.cut(f, box, pad, plate if s is None else s), METRIC, params))
                    for f, box, s in zip(frames, local, own)]
    return out


def main():
    params = pipeline._resolve_metric(METRIC, None)[1]
    result = {"ways": {way: {"fps": fps, "seconds": seconds} for way, (fps, seconds) in WAYS.items()}, "sessions": {}}
    for name in SESSIONS:
        data_dir = pipeline.RECORDINGS_ROOT / name
        data = pipeline._read_dataset(name)
        index = open_recordings(data_dir).index
        assert {recording["fps"] for recording in index["recordings"]} == {RECORDED_FPS}
        order = index_order(data, index)
        rois = [index["mites"][number]["roi"] for number in order]
        placed = followed_boxes(data, index, order)
        jobs = [(str(data_dir), recording["name"], order, rois, placed[at], params)
                for at, recording in enumerate(index["recordings"])]
        with ProcessPoolExecutor(8) as pool:
            per_recording = list(pool.map(score_recording, jobs))
        n = len(data["times"])
        states = [calibration.per_recording(data["truth"].get(mite["id"]), n) for mite in data["mites"]]
        result["sessions"][name] = {
            "states": [[state or "" for state in row] for row in states],
            "scores": {way: [[per_recording[at][way][m] for at in range(n)] for m in range(len(order))] for way in WAYS}}
        print(f"{name}: {len(order)} mites, {n} recordings", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
