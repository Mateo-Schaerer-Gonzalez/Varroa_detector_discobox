"""The measures a calibration report takes of a dataset's mites -- the scores,
the brightness, the benchmark's calls, the outline changes -- worked out from
the frames and cached in the dataset's scores/.

Each cache file's name changes with whatever its values depend on, the scoring
code's source included (_metric_version() and the _*_name() functions), so a
cache is only read back for exactly the code and settings that made it. A cache
is only a shortcut: deleting it just means decoding the recordings again.
"""

import hashlib
import inspect
import json
from functools import partial
from pathlib import Path

import numpy as np

from classes.scoring.analyzer import Analyzer
from classes.scoring import benchmark as benchmark_module
from classes.scoring.benchmark import Benchmark
from classes.scoring import plate_stabilizer
from classes.scoring.plate_stabilizer import PlateStabilizer
from classes.storage.data_loader import DataLoader
from classes.storage.files import read_json, write_json
from classes.scoring import outline_change as outline_change_module
from classes.scoring.outline_change import OutlineChange
from classes.storage.roi_recordings import is_roi_session, open_recordings
from classes.scoring.workers import one_ahead, side_by_side
from pipeline import clips, ground_truth, paths, refusals, scoring


def _scores_dir(dataset):
    """Where a dataset's scores are cached: scores/ in its recording folder."""
    return Path(dataset["data_dir"]) / paths.SCORES_DIRNAME


def _cached_per_recording(cache, field, dataset):
    """What `cache` holds under `field` (mite id to one value per recording), or
    None when there is no cache or it was written when the dataset had another
    number of recordings: a run recorded on after it was scored."""
    cached = read_json(cache)
    if cached is None:
        return None
    by_mite = cached[field]
    n_recordings = len(dataset["recordings"])
    return by_mite if all(len(values) == n_recordings for values in by_mite.values()) else None


def _digest(*parts, sort_keys=False):
    """Twelve hex digits that change with `parts` (as JSON): the version in a
    cached file's name."""
    return hashlib.sha1(json.dumps(list(parts), sort_keys=sort_keys).encode("utf-8")).hexdigest()[:12]


def _mites_key(mites):
    """What of the mites ({id, x, y, r}) a cached measure of them depends on."""
    return [[m["id"], m["x"], m["y"], m["r"]] for m in mites]


def _metric_version(metric, params, mites, stabilize=False):
    """Changes whenever the scores of these mites could: another metric, other
    parameters, plate stabilization switched, an edit to the scoring code, or
    other mites."""
    source = inspect.getsource(Analyzer) + inspect.getsource(plate_stabilizer)
    return _digest(metric, params, source, _mites_key(mites), *([True] if stabilize else []), sort_keys=True)


def _brightness_name(mites, pad, stabilize):
    return f"brightness-{_digest(inspect.getsource(plate_stabilizer), pad, bool(stabilize), _mites_key(mites))}.json"


def _benchmark_name(mites):
    return f"benchmark-{_digest(inspect.getsource(benchmark_module), _mites_key(mites))}.json"


def _outline_name(mites, stabilize):
    source = inspect.getsource(outline_change_module) + inspect.getsource(plate_stabilizer)
    return f"outline-{_digest(source, bool(stabilize), _mites_key(mites))}.json"


def _cached_by_mite(dataset, filename, field, measure, **more):
    """`measure()` of a dataset's mites (mite id to one value per recording),
    kept in its scores/ as `filename` under `field` (with `more` beside it) and
    read back from there while the dataset has as many recordings
    (_cached_per_recording()). The cache is only a shortcut: deleting it just
    means decoding the recordings again."""
    cache = _scores_dir(dataset) / filename
    cached = _cached_per_recording(cache, field, dataset)
    if cached is not None:
        return cached
    values = measure()
    cache.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache, {**more, field: values})
    return values


def mite_boxes(mites, pad=0):
    """Mite id to (x1, y1, x2, y2): the same box around each saved mite as
    Mite.get_ROI() cuts in an analysis run, grown by `pad` pixels on each side.
    x1 and y1 can be negative; the caller cuts them off at the image's edge."""
    return {
        m["id"]: (int(round(m["x"] - m["r"])) - pad, int(round(m["y"] - m["r"])) - pad,
                  int(round(m["x"] + m["r"])) + pad, int(round(m["y"] + m["r"])) + pad)
        for m in mites
    }


def _measure_mites(dataset, recordings_dir, measure, pad=0, stabilize=False):
    """Per recording of a dataset, in order: {mite id: measure(its patch)}, the
    patch being the mite's box grown by `pad` in every frame, as an analysis run
    cuts it. Slow: every frame is decoded, a recording at a time (the next one
    while this one is measured), and only the part of the image holding mites
    is kept; the mites of a recording are measured side by side. With
    `stabilize`, the cuts follow a shaking plate, as mite.stabilize_plate makes
    an analysis run cut them."""
    loader = open_recordings(recordings_dir)
    boxes = mite_boxes(dataset["mites"], pad)
    # Stabilizing reads a little around each cut; keep real pixels there.
    x0, y0, x_end, y_end = clips.bounds(boxes.values(), scoring.STABILIZE_MARGIN if stabilize else 0)
    local = clips.local(mite_boxes(dataset["mites"]), x0, y0)

    def measured(frames):
        shifts = dict(zip(local, PlateStabilizer().shifts(frames, list(local.values())))) if stabilize else None

        def one(mite_id):
            x1, y1, x2, y2 = boxes[mite_id]
            if shifts is None:
                return measure(frames[:, max(0, y1) - y0:y2 - y0, max(0, x1) - x0:x2 - x0])
            return measure(PlateStabilizer.cut(frames, local[mite_id], pad, shifts[mite_id]))

        return dict(zip(boxes, side_by_side(one, boxes)))

    loads = (partial(loader.load_recording_region, recording["name"], x0, y0, x_end, y_end)
             for recording in dataset["recordings"])
    for frames in one_ahead(loads):
        yield measured(frames)


def _check_there(dataset, recordings_dir, what):
    """refusals.recordings_dir() of `dataset`, its recordings read from `recordings_dir`."""
    refusals.recordings_dir({**dataset, "data_dir": str(recordings_dir)}, what)


def _score_mites(dataset, metric, recordings_dir, params=None, stabilize=False):
    """Score every mite of a dataset in every recording with `metric` and its
    `params`: mite id to one score per recording (see _measure_mites())."""
    _check_there(dataset, recordings_dir, f"its mites cannot be scored with {metric}")
    scores = {mite["id"]: [] for mite in dataset["mites"]}

    def score(roi):
        return round(float(Analyzer._motion_score(roi, metric, params)), 3)

    for recording in _measure_mites(dataset, recordings_dir, score, Analyzer.roi_padding(metric, params), stabilize):
        for mite_id, value in recording.items():
            scores[mite_id].append(value)
    return scores


def _brightness_mites(dataset, recordings_dir, pad=0, stabilize=False):
    """The brightness of every mite's patch in every recording, as an analysis
    run records it with the score (Analyzer.score_pool()): mite id to one mean
    pixel value per recording."""
    _check_there(dataset, recordings_dir, "the brightness of its mites cannot be measured")
    brightness = {mite["id"]: [] for mite in dataset["mites"]}

    def mean(roi):
        return round(Analyzer.brightness(np.asarray(roi, dtype=np.float32)), 3)

    for recording in _measure_mites(dataset, recordings_dir, mean, pad, stabilize):
        for mite_id, value in recording.items():
            brightness[mite_id].append(value)
    return brightness


def _dataset_brightness(key, dataset, pad, stabilize=False):
    """The brightness of the dataset's mites, from the cache when exactly these
    patches were measured before."""
    return _cached_by_mite(dataset, _brightness_name(dataset["mites"], pad, stabilize), "brightness",
                           lambda: _brightness_mites(dataset, Path(dataset["data_dir"]), pad, stabilize))


def normalised_scores(key, dataset, scores, normalizer, pad, stabilize):
    """A dataset's scores as the analysis of a folder would have them with
    `normalizer`: over the dataset's recordings, the mites marked not a mite
    left out of it, as an analysis leaves them out."""
    if not normalizer.active:
        return scores
    brightness = _dataset_brightness(key, dataset, pad, stabilize) if normalizer.brightness else None
    mites = [mite["id"] for mite, _states in ground_truth.mite_states(dataset)]
    normalised = normalizer.by_mite({mite_id: scores[mite_id] for mite_id in mites},
                                    brightness and {mite_id: brightness[mite_id] for mite_id in mites})
    return {**scores, **{mite_id: [round(value, 3) for value in values] for mite_id, values in normalised.items()}}


def dataset_scores(key, dataset, metric, params, stabilize=False):
    """The dataset's mites scored with `metric` and `params`, from the cache when
    exactly this metric, with these parameters, this plate stabilization and
    this scoring code, has scored them before. The cache is only a shortcut:
    deleting it just means decoding the recordings again."""
    return _cached_by_mite(dataset, f"{_metric_version(metric, params, dataset['mites'], stabilize)}.json", "scores",
                           lambda: _score_mites(dataset, metric, Path(dataset["data_dir"]), params, stabilize),
                           metric=metric, params=params)


def _benchmark_mites(dataset, recordings_dir):
    """Whether the benchmark (classes/scoring/benchmark.py) calls each mite of a dataset
    moving in each recording: mite id to one True or False per recording. Slow:
    every frame is decoded and denoised, in the part of the image holding mites."""
    _check_there(dataset, recordings_dir, "the benchmark cannot be run on them")
    loader = open_recordings(recordings_dir)
    boxes = mite_boxes(dataset["mites"])
    x0, y0, x_end, y_end = clips.bounds(boxes.values(), Benchmark.MARGIN)
    local = clips.local(boxes, x0, y0)

    calls = {mite_id: [] for mite_id in boxes}
    for recording in dataset["recordings"]:
        frames = loader.load_recording_region(recording["name"], x0, y0, x_end, y_end)
        for mite_id, moving in Benchmark.calls(frames, local).items():
            calls[mite_id].append(moving)
    return calls


def dataset_benchmark(key, dataset):
    """The benchmark's calls for the dataset's mites, from the cache when this
    benchmark code has called exactly these mites before."""
    return _cached_by_mite(dataset, _benchmark_name(dataset["mites"]), "calls",
                           lambda: _benchmark_mites(dataset, Path(dataset["data_dir"])), benchmark=Benchmark.NAME)


def _outline_mites(dataset, recordings_dir, stabilize=False):
    """How much each mite's outline changed from the recording before
    (OutlineChange.changes()): mite id to one change per recording, in px, None
    for the first. Slow: every frame is decoded, as scoring decodes them
    (_measure_mites()), each mite cut with outline_change.PAD pixels around it."""
    _check_there(dataset, recordings_dir, "their outlines cannot be compared")
    outlines = {mite["id"]: [] for mite in dataset["mites"]}
    for recording in _measure_mites(dataset, recordings_dir, OutlineChange.outline_of, outline_change_module.PAD,
                                    stabilize):
        for mite_id, outline in recording.items():
            outlines[mite_id].append(outline)
    return {mite_id: [None if change is None else round(change, 4) for change in OutlineChange.changes(found)]
            for mite_id, found in outlines.items()}


def dataset_outline_changes(key, dataset, stabilize=False):
    """_outline_mites() of the dataset, from the cache when this outline code,
    with this plate stabilization, has measured exactly these mites before."""
    return _cached_by_mite(dataset, _outline_name(dataset["mites"], stabilize), "changes",
                           lambda: _outline_mites(dataset, Path(dataset["data_dir"]), stabilize))


def _benchmark_circles(recordings_dir, recording_name):
    """The circles the benchmark draws on one recording (Benchmark.circles()).
    Slow: every whole frame is decoded and denoised. None for a session saved
    as the mites' ROIs: there are no whole frames to draw them on."""
    if is_roi_session(recordings_dir):
        return None
    return Benchmark.circles(DataLoader(recordings_dir, grayscale=True).load_recording(recording_name))


def dataset_circles(key, dataset, recording):
    """The benchmark's circles on one recording of the dataset, from the cache
    when this benchmark code has drawn them before; None when the recording's
    frames are gone, so there is nothing to draw them from."""
    name = dataset["recordings"][recording]["name"]
    cache = _scores_dir(dataset) / f"benchmark-circles-{_digest(inspect.getsource(benchmark_module), name)}.json"
    cached = read_json(cache)
    if cached is not None:
        return cached["circles"]
    try:
        circles = _benchmark_circles(Path(dataset["data_dir"]), name)
    except FileNotFoundError:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache, {"benchmark": Benchmark.NAME, "recording": name, "circles": circles})
    return circles
