"""Mites pushed during a poke test, scored as they were recorded and as a live
run that follows its mites would score them. What is behind
notebooks/poke_run_followed.ipynb.

Ground_truth_oct_26_final was recorded (12-14 October 2026) before live runs
followed their mites (28afd12): every mite was scored in the box it was found
in on the first frame. The poke test after its 30th recording pushed the
mites of the top plates 10 to 35 px, half or wholly out of those boxes, and
the scores of mites lying still at the edge of their box went up to 100. Its
ROI index keeps the blobs found on every recording's first and last frame, so
following can be replayed: each mite's box moved to the nearest blob in its
zone, at most FOLLOW_PX away, nearest pairs first, as
MotionAnalysis._followed() does.

For every mite of a dataset and every recording this writes:

    scores      outline_variability (the score in use) of the box as found
                ("fixed") and as followed ("follow"), with the stabilizer
                ("stab", as the app scores) and without ("raw")
    outline     classes/outline_change.py's change from the recording before,
                fixed and followed: the between-recordings measure
    light       the plate's light round the mite (median of the patch's rim)
                and how much the frames' mean varies within the recording
    offset      how far the followed box is from where the mite was found, px
                (and the boxes themselves, to draw)

and per dataset the labels, the benchmark's calls (as cached by the
calibration report, boxes fixed) and the poke test's bounds per mite.

The followed boxes are cut from each mite's own ROI video (box + 32 px as
saved). A box followed further than the ROI allows has its patch's far side
mirrored in from the plate (plate_stabilizer._patch()): the plate, not
another mite. A mite whose centre can't be found takes the median of the
others' shifts, as PlateStabilizer.shifts() does.

    python scripts/poke_run_followed.py     # about a minute
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import pipeline
from pipeline.calibration import dataset_library, movement_score, poke_test, score_cache
from classes import calibration
from classes.analyzer import Analyzer
from classes.app_config import METRIC
from classes.motion_analysis import FOLLOW_MIN_SHIFT
from classes.outline_change import PAD as OUTLINE_PAD, OutlineChange
from classes.plate_stabilizer import PlateStabilizer, _RIM
from classes.roi_recordings import open_recordings

DATASETS = ("GT_oct_2", "Ground_truth_oct_26_final")  # calibrate, test
FOLLOW_PX = 50       # classes/live/settings.py's default follow_px
OUT = Path(__file__).resolve().parent.parent / "results" / "scripts" / "poke_run_followed"


def dataset(name):
    """A dataset as the calibration report reads it. Both sit one folder deeper
    than recordings/<name>/, as they were copied from the Discobox laptop."""
    return dataset_library.read_dataset(name, pipeline.RECORDINGS_ROOT / name)


def index_order(data, index):
    """Per mite of the dataset, its number in the ROI index (the index keeps
    the order they were saved in, the dataset its ids)."""
    centres = np.array([[(x1 + x2) / 2, (y1 + y2) / 2] for x1, y1, x2, y2 in (m["box"] for m in index["mites"])])
    order = [int(np.argmin(np.hypot(*(centres - [m["x"], m["y"]]).T))) for m in data["mites"]]
    assert len(set(order)) == len(order), "two mites matched to one ROI"
    return order


def followed_boxes(data, index, order):
    """Per recording, per mite of the dataset, its box (x1, y1, x2, y2) as a
    live run following its mites would have placed it."""
    zones = {zone["id"]: zone for zone in data["zones"]}
    boxes = [tuple(index["mites"][number]["box"]) for number in order]

    def in_zone(mite, x, y):
        zone = zones.get(mite["zone_id"])
        return zone is None or (zone["x1"] <= x <= zone["x2"] and zone["y1"] <= y <= zone["y2"])

    placed = []
    for number, recording in enumerate(index["recordings"]):
        if number > 0 and recording.get("blobs"):
            blobs = np.array(recording["blobs"], dtype=float)
            pairs = []
            for m, (x1, y1, x2, y2) in enumerate(boxes):
                distance = np.hypot(*(blobs - [(x1 + x2) / 2, (y1 + y2) / 2]).T)
                pairs += [(distance[b], m, b) for b in np.flatnonzero(distance <= FOLLOW_PX)
                          if in_zone(data["mites"][m], *blobs[b])]
            moved, taken = {}, set()
            for distance, m, b in sorted(pairs):
                if m in moved or b in taken:
                    continue
                taken.add(b)
                x1, y1, x2, y2 = boxes[m]
                if distance >= FOLLOW_MIN_SHIFT:
                    dx, dy = int(round(blobs[b][0] - (x1 + x2) / 2)), int(round(blobs[b][1] - (y1 + y2) / 2))
                    moved[m] = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                else:
                    moved[m] = boxes[m]
            boxes = [moved.get(m, box) for m, box in enumerate(boxes)]
        placed.append(list(boxes))
    return placed


def measure_recording(job):
    """Everything of one recording, per mite: {scores: {kind: [...]}, outline:
    {kind: [...]}, light, flicker}."""
    data_dir, name, numbers, rois, boxes, params = job
    loader = open_recordings(data_dir)
    frames = [loader.read_mite(name, number).astype(np.float32) for number in numbers]
    frames = [f.reshape(f.shape[:3]) for f in frames]
    out = {"scores": {}, "outline": {}}
    for kind in ("fixed", "follow"):
        local = [(x1 - roi[0], y1 - roi[1], x2 - roi[0], y2 - roi[1]) for (x1, y1, x2, y2), roi in zip(boxes[kind], rois)]
        stabilizer = PlateStabilizer()
        own = [stabilizer._mite_shifts(f, box) for f, box in zip(frames, local)]
        found = [shifts for shifts in own if shifts is not None]
        plate = np.median(found, axis=0) if found else np.zeros((len(frames[0]), 2))
        shifts = [plate if s is None else s for s in own]
        for stab in ("stab", "raw"):
            out["scores"][f"{kind}_{stab}"] = [
                round(float(Analyzer._motion_score(
                    PlateStabilizer.cut(f, box, Analyzer.roi_padding(METRIC, params), s if stab == "stab" else 0 * s),
                    METRIC, params)), 4)
                for f, box, s in zip(frames, local, shifts)]
        out["outline"][kind] = [OutlineChange.outline_of(PlateStabilizer.cut(f, box, OUTLINE_PAD, s)).tolist()
                                for f, box, s in zip(frames, local, shifts)]
    rim = [np.ones(f.shape[1:], bool) for f in frames]
    for r in rim:
        r[_RIM:-_RIM, _RIM:-_RIM] = False
    out["light"] = [round(float(np.median(f[:, r])), 2) for f, r in zip(frames, rim)]
    out["flicker"] = [round(float(np.ptp(f.mean(axis=(1, 2)))), 3) for f in frames]
    return out


def measure(name, params):
    data = dataset(name)
    loader = open_recordings(data["data_dir"])
    index = loader.index
    order = index_order(data, index)
    fixed = [tuple(index["mites"][number]["box"]) for number in order]
    rois = [index["mites"][number]["roi"] for number in order]
    placed = followed_boxes(data, index, order)
    jobs = [(data["data_dir"], recording, order, rois, {"fixed": fixed, "follow": placed[at]}, params)
            for at, recording in enumerate(loader.recording_names)]
    with ProcessPoolExecutor(8) as pool:
        per_recording = list(pool.map(measure_recording, jobs))

    def by_mite(get):
        return [[get(recording)[m] for recording in per_recording] for m in range(len(order))]

    n = len(data["times"])
    ids = [mite["id"] for mite in data["mites"]]
    states = [calibration.per_recording(data["truth"].get(mite_id), n) for mite_id in ids]
    poke = poke_test._poke_of(data)
    benchmark = score_cache.dataset_benchmark(name, data)
    centres = lambda boxes: np.array([[(x1 + x2) / 2, (y1 + y2) / 2] for x1, y1, x2, y2 in boxes])
    return {
        "name": name,
        "ids": ids,
        "zones": [mite["zone_id"] for mite in data["mites"]],
        "xy": [[mite["x"], mite["y"]] for mite in data["mites"]],
        "times": data["times"],
        "states": [[state or "" for state in row] for row in states],
        "app_scores": [score_cache.dataset_scores(name, data, METRIC, params, True)[mite_id] for mite_id in ids],
        "benchmark": [benchmark[mite_id] for mite_id in ids],
        "scores": {kind: by_mite(lambda r, kind=kind: r["scores"][kind]) for kind in per_recording[0]["scores"]},
        "outline": {kind: [OutlineChange.changes([np.array(o) for o in outlines])
                           for outlines in by_mite(lambda r, kind=kind: r["outline"][kind])]
                    for kind in ("fixed", "follow")},
        "light": by_mite(lambda r: r["light"]),
        "flicker": by_mite(lambda r: r["flicker"]),
        "data_dir": str(data["data_dir"]),
        "recordings": loader.recording_names,
        "roi_numbers": order,
        "found_boxes": [list(box) for box in fixed],
        "followed_boxes": [[list(placed[at][m]) for at in range(len(placed))] for m in range(len(order))],
        # per mite, per recording: how far its followed box is from where it was found, px
        "offset": np.round(np.hypot(*(np.array([centres(boxes) for boxes in placed]) - centres(fixed)).transpose(2, 1, 0)), 1).tolist(),
        "poke": {"rounds": [{"after": r["after"], "states": r["states"]} for r in poke.rounds],
                 "bounds": {mite_id: poke.bounds(mite_id) for mite_id in ids if poke.pokes(mite_id)}},
        "outline_limit": OutlineChange().limit,
    }


def main():
    _metric, params = movement_score.resolve_metric(METRIC, None)
    OUT.mkdir(parents=True, exist_ok=True)
    for name in DATASETS:
        result = measure(name, params)
        (OUT / f"{name}.json").write_text(json.dumps(result), encoding="utf-8")
        print(f"{name}: {len(result['ids'])} mites, {len(result['times'])} recordings")


if __name__ == "__main__":
    main()
