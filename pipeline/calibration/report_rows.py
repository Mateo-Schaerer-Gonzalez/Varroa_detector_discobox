"""The rows a calibration report is made of: one per labelled (mite, recording)
of each dataset, and what the report shows of each dataset and zone.
"""

import numpy as np

from classes import calibration
from classes.benchmark import Benchmark
from classes.outline_change import OutlineChange
from classes.zones import UNLABELED
from pipeline import ground_truth
from pipeline.calibration import score_cache


def last_recording(dataset, scores, threshold, benchmark=None, circles=None):
    """The last recording of a dataset as its callers see it, for the test
    report: every mite not marked "not a mite" with its box (x1, y1, x2, y2),
    its score there, the detector's call at `threshold` and its label, None
    when it has none there. With `benchmark` (its calls, see
    score_cache.dataset_benchmark()) each mite also has the benchmark's call, and
    `circles` are what the benchmark draws on that recording, each of radius
    "circle_radius" (see score_cache.dataset_circles()). A mite a live run did not follow
    there (counted dead by then, see calibration.followed()) is left out."""
    last = len(dataset["times"]) - 1
    boxes = score_cache.mite_boxes(dataset["mites"])
    mites = []
    for mite, states in ground_truth.mite_states(dataset):
        if not calibration.followed(mite, last):
            continue
        score = scores[mite["id"]][last]
        mites.append(
            {
                "id": mite["id"],
                "zone_id": mite["zone_id"],
                "box": list(boxes[mite["id"]]),
                "score": score,
                "call": calibration.call(score >= threshold),
                "movement": states[last],
                **({} if benchmark is None else {"benchmark_call": calibration.call(benchmark[mite["id"]][last])}),
            }
        )
    return {
        "recording": last,
        "recording_name": dataset["recordings"][last]["name"] if last < len(dataset["recordings"]) else "",
        "time": dataset["times"][last],
        "mites": mites,
        "circles": circles,
        "circle_radius": Benchmark.CIRCLE,
    }


def observations(dataset, dataset_key, scores, benchmark=None, outline=None):
    """One row per (mite, recording) of a dataset labelled moving or still, and
    the number of mites marked not a mite and of unlabelled mite-recordings.
    With `benchmark` (its calls, see score_cache.dataset_benchmark()), each row also says
    what the benchmark called it; with `outline` ({changes, calls}, each mite id
    to one per recording, see between_recordings()), the outline's change from
    the recording before and what it calls it. A mite a live run did not follow
    in a recording (added later, or counted dead, see calibration.followed())
    has no row there: nothing of it was saved."""
    times = dataset["times"]
    n_recordings = len(times)
    groups = {zone["id"]: zone["label"] or UNLABELED for zone in dataset["zones"]}
    recording_names = [recording["name"] for recording in dataset["recordings"]]
    recording_names += [""] * (n_recordings - len(recording_names))
    rows, n_unlabelled = [], 0
    kept = ground_truth.mite_states(dataset)
    n_rejected = len(dataset["mites"]) - len(kept)
    for mite, states in kept:
        start = mite.get("start", 0)
        for recording, movement in enumerate(states):
            if not calibration.followed(mite, recording):
                continue
            if movement is None:
                n_unlabelled += 1
                continue
            rows.append(
                {
                    "dataset": dataset_key,
                    "dataset_name": dataset["name"],
                    "recording_name": recording_names[recording],
                    "mite_id": mite["id"],
                    "zone_id": mite["zone_id"],
                    "group": groups.get(mite["zone_id"], UNLABELED),
                    "x": mite["x"],
                    "y": mite["y"],
                    "recording": recording,
                    "time": times[recording],
                    "start": start,
                    "movement": movement,
                    "score": scores[mite["id"]][recording],
                    **({} if benchmark is None else {"benchmark_call": calibration.call(benchmark[mite["id"]][recording])}),
                    **({} if outline is None else {
                        "outline_change": outline["changes"][mite["id"]][recording],
                        "outline_call": calibration.call(outline["calls"][mite["id"]][recording])}),
                }
            )
    return rows, n_rejected, n_unlabelled


def between_recordings(key, dataset, stabilize=False):
    """The outline change of every mite of a dataset from the recording before
    (score_cache.dataset_outline_changes()) and whether it says the mite moved
    (OutlineChange.calls()): {changes, calls}, each mite id to one per recording.
    A change into or out of a recording a live run did not follow the mite in
    (calibration.followed()) is None: nothing of it was saved there."""
    changes = dict(score_cache.dataset_outline_changes(key, dataset, stabilize))
    for mite in dataset["mites"]:
        if mite.get("start") or mite.get("stop") is not None:
            changes[mite["id"]] = [None if not (calibration.followed(mite, at) and calibration.followed(mite, at - 1)) else change
                                   for at, change in enumerate(changes[mite["id"]])]
    judge = OutlineChange()
    return {"changes": changes, "calls": {mite_id: judge.calls(values) for mite_id, values in changes.items()}}


def outline_rows(dataset, key, outline):
    """Every mite of a dataset not marked not a mite, for the figure of the
    outline change (OutlineChange.raster()): where it is, its labels per
    recording (True moving, False still, None unlabelled) and its changes."""
    rows = []
    for mite, states in ground_truth.mite_states(dataset):
        rows.append({"dataset": key, "dataset_name": dataset["name"], "mite_id": mite["id"], "zone_id": mite["zone_id"],
                     "moving": [None if state is None or not calibration.followed(mite, at) else state == calibration.MOVING
                                for at, state in enumerate(states)],
                     "changes": outline["changes"][mite["id"]], "calls": outline["calls"][mite["id"]]})
    return rows


def pooled_times(datasets):
    """Recordings are pooled by their order; each gets the mean of its times."""
    n_recordings = max(len(dataset["times"]) for dataset in datasets)
    times = []
    for recording in range(n_recordings):
        here = [dataset["times"][recording] for dataset in datasets if recording < len(dataset["times"])]
        times.append(round(float(np.mean(here)), 2))
    return times


def n_mites(rows):
    return len({(row["dataset"], row["mite_id"]) for row in rows})


def calibration_by_zone(rows):
    """Per zone of each dataset, at the threshold in use: the movement labels and
    how many the detector called wrong, each way."""
    zones = []
    for dataset, zone_id in sorted({(row["dataset"], row["zone_id"]) for row in rows}):
        here = [row for row in rows if row["dataset"] == dataset and row["zone_id"] == zone_id]
        zones.append(
            {
                "dataset": dataset,
                "dataset_name": here[0]["dataset_name"],
                "id": zone_id,
                "group": here[0]["group"],
                "n_mites": n_mites(here),
                "n_moving": sum(row["movement"] == calibration.MOVING for row in here),
                "n_still": sum(row["movement"] == calibration.STILL for row in here),
                "moving_called_still": sum(row["outcome"] == "moving_called_still" for row in here),
                "still_called_moving": sum(row["outcome"] == "still_called_moving" for row in here),
            }
        )
    return zones


def rounded(values, digits=4):
    return [None if value is None else round(float(value), digits) for value in values]
