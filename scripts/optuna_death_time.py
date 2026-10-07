"""Bayesian search (Optuna, TPE) of the whole movement setup against the saved
ground truth, by where it puts each mite's death: the metric, its parameters,
the normalisations of the scores, the threshold, and a band around it to check
by eye (classes/death_calibration.py).

The mites of every dataset in calibration_data/ are split in two, dataset by
dataset: the train mites choose everything, the test mites only judge it.

    per trial    every mite is scored in every recording with the trial's
                 parameters, as a calibration scores it; the scores go through
                 each of the four normalisations (classes/score_normalizer.py);
                 for each, the threshold with the smallest mean death error on
                 the train mites is taken. The trial's value is the smallest of
                 the four errors, in recordings.
    per metric   the best trial, judged on the test mites at its threshold; and
                 for each number of checks per mite in --checks, the band around
                 the threshold that does best on the train mites, judged on the
                 test mites with their labels standing in for the eye.
                 One split is partly luck, so the threshold is also chosen and
                 judged on --resplits other splits ("other splits").

The patches are cut once (slow: every frame is decoded) and kept in --cache, so
a second run starts at once. The studies are kept in
calibration_data/reports/optuna_death_time.db: the same --study name carries on
where it stopped (Ctrl+C is safe), with the same --seed and --test-share.

    python scripts/optuna_death_time.py                       # every metric
    python scripts/optuna_death_time.py --metrics topN_variability --trials 100

The best of each is written to calibration_data/reports/optuna_death_time_<study>_<time>.csv.
"""
import argparse
import csv
import hashlib
import inspect
import json
import os
import random
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import optuna
import pandas as pd

import pipeline
from classes import calibration, death_calibration, plate_stabilizer
from classes.analyzer import Analyzer
from classes.app_config import get_default_config
from classes.data_loader import DataLoader
from classes.death_calibration import LabelledRun
from classes.plate_stabilizer import PlateStabilizer
from classes.score_normalizer import ScoreNormalizer
from optuna_metrics import DEFAULT_TRIALS, SPACES, TRIALS, _top_n, start_params
from tune_optical_flow import POLY_SIGMA

STORAGE_FILE = pipeline.CALIBRATION_REPORTS / "optuna_death_time.db"
STORAGE = f"sqlite:///{STORAGE_FILE.as_posix()}"
# The patches are kept at the largest padding; a smaller one is cut out of it.
PADS = [0, 4, 8, 12, 16]
MAX_PAD = max(PADS)
NORMALISATIONS = [(False, False), (True, False), (False, True), (True, True)]  # (brightness, floor)


def _optical_flow(trial):
    """optuna_metrics' search, within the padding kept here; `step` is cut to
    the frames of a recording by the metric itself."""
    params = {
        "pad": trial.suggest_categorical("pad", PADS),
        "window": trial.suggest_int("window", 3, 25, step=2),
        "n": trial.suggest_int("n", 5, 300, log=True),
        "step": trial.suggest_int("step", 1, 29),
        "winsize": trial.suggest_int("winsize", 5, 51, step=2),
        "levels": trial.suggest_int("levels", 1, 4),
        "poly_n": trial.suggest_categorical("poly_n", [5, 7]),
        "iterations": trial.suggest_int("iterations", 1, 6),
    }
    params["poly_sigma"] = POLY_SIGMA[params["poly_n"]]
    return params


DEATH_SPACES = {**SPACES, "optical_flow": _optical_flow}


# ---- the patches of every mite in every recording, cut once ----

def _cut_recording(job):
    """One recording's patches, (mites, frames, side, side, channels) float32:
    each mite's box grown by MAX_PAD, in the top left corner of its square."""
    recordings_dir, name, region, local, plate, side, stabilize = job
    frames = DataLoader(recordings_dir, grayscale=False).load_recording_region(name, *region)
    shifts = PlateStabilizer().shifts(frames, plate) if stabilize else None
    out = np.zeros((len(local), len(frames), side, side, frames.shape[-1]), dtype=np.float32)
    for index, (x1, y1, x2, y2) in enumerate(local):
        if shifts is None:
            cut = frames[:, y1 - MAX_PAD:y2 + MAX_PAD, x1 - MAX_PAD:x2 + MAX_PAD]
        else:
            cut = PlateStabilizer.cut(frames, (x1, y1, x2, y2), MAX_PAD, shifts)
        out[index, :, :cut.shape[1], :cut.shape[2]] = cut
    return out


def load_dataset(summary, cache_dir, stabilize, jobs):
    """One saved dataset, its mites marked not a mite left out: {name, mites
    (their ids), path (the patches, see _cut_recording(), as (mites, recordings,
    ...) in a .npy file), sizes (each mite's box, (height, width)), moving and
    labelled as (mites, recordings)}. None when its recordings are gone."""
    dataset = pipeline._read_dataset(summary["id"], pipeline.CALIBRATION_LIBRARY)
    recordings_dir = pipeline._recordings_dir(dataset["data_dir"], pipeline.CALIBRATION_LIBRARY)
    if not recordings_dir.is_dir():
        # a dataset saved on another computer: its id is not this one's for that folder
        recordings_dir = pipeline._dataset_dir(summary["id"], pipeline.CALIBRATION_LIBRARY) / pipeline.RECORDINGS_DIRNAME
    if not recordings_dir.is_dir():
        print(f"  skipping {dataset['name']}: its recordings are gone")
        return None
    n_recordings = len(dataset["times"])
    states = {mite["id"]: calibration.per_recording(dataset["truth"].get(mite["id"]), n_recordings)
              for mite in dataset["mites"]}
    mites = [mite for mite in dataset["mites"] if not calibration.is_rejected(states[mite["id"]])]
    if not mites:
        return None
    states = np.array([states[mite["id"]] for mite in mites], dtype=object)

    boxes = list(pipeline.mite_boxes(mites).values())
    # The plate's shift is measured on every detection, as a calibration measures it.
    every = list(pipeline.mite_boxes(dataset["mites"]).values())
    reach = MAX_PAD + (pipeline.STABILIZE_MARGIN if stabilize else 0)
    x0, y0 = min(b[0] for b in every) - reach, min(b[1] for b in every) - reach
    x_end, y_end = max(b[2] for b in every) + reach, max(b[3] for b in every) + reach
    image = dataset["image"]
    if x0 < 0 or y0 < 0 or x_end > image["width"] or y_end > image["height"]:
        raise ValueError(f"{dataset['name']}: a mite is closer than {reach} px to the image's edge.")
    local = [(x1 - x0, y1 - y0, x2 - x0, y2 - y0) for x1, y1, x2, y2 in boxes]
    plate = [(x1 - x0, y1 - y0, x2 - x0, y2 - y0) for x1, y1, x2, y2 in every]
    sizes = np.array([(y2 - y1, x2 - x1) for x1, y1, x2, y2 in boxes])
    side = int(sizes.max()) + 2 * MAX_PAD

    names = [recording["name"] for recording in dataset["recordings"]]
    version = hashlib.sha1(json.dumps([inspect.getsource(plate_stabilizer), MAX_PAD, bool(stabilize),
                                       boxes, every, names]).encode("utf-8")).hexdigest()[:12]
    path = Path(cache_dir) / f"{summary['id']}-{version}.npy"
    if not path.is_file():
        started = time.time()
        work = [(recordings_dir, name, (x0, y0, x_end, y_end), local, plate, side, stabilize) for name in names]
        patches = None
        part = path.with_suffix(".part.npy")
        with ProcessPoolExecutor(jobs) as pool:
            for index, cut in enumerate(pool.map(_cut_recording, work)):
                if patches is None:
                    patches = np.lib.format.open_memmap(part, mode="w+", dtype=np.float32,
                                                        shape=(len(mites), len(names), *cut.shape[1:]))
                patches[:, index] = cut
        patches.flush()
        del patches
        part.replace(path)
        print(f"  {dataset['name']}: patches cut in {time.time() - started:.0f} s")
    print(f"  {dataset['name']}: {len(mites)} mites, {n_recordings} recordings")
    return {"name": dataset["name"], "mites": [mite["id"] for mite in mites], "path": str(path), "sizes": sizes,
            "moving": states == calibration.MOVING,
            "labelled": (states == calibration.MOVING) | (states == calibration.STILL)}


# ---- scoring, in worker processes that map the patches once ----

_PATCHES = None


def _init_worker(datasets):
    global _PATCHES
    _PATCHES = [(np.load(path, mmap_mode="r"), sizes) for path, sizes in datasets]


def _score_mite(job):
    """One mite's score and brightness in every recording, as
    Analyzer.score_pool() records them."""
    dataset, mite, metric, params = job
    patches, sizes = _PATCHES[dataset]
    height, width = sizes[mite]
    edge = MAX_PAD - Analyzer.roi_padding(metric, params)
    scores, brightness = [], []
    for recording in range(patches.shape[1]):
        roi = np.asarray(patches[mite, recording, :, edge:2 * MAX_PAD + height - edge,
                                 edge:2 * MAX_PAD + width - edge])
        scores.append(round(float(Analyzer._motion_score(roi, metric, params)), 3))
        brightness.append(round(float(roi.mean()), 3))
    return scores, brightness


def score_all(pool, datasets, metric, params):
    """Per dataset, (scores, brightness) as (mites, recordings)."""
    work = [(index, mite, metric, params) for index, dataset in enumerate(datasets)
            for mite in range(len(dataset["mites"]))]
    results = iter(pool.map(_score_mite, work))
    out = []
    for dataset in datasets:
        rows = [next(results) for _mite in dataset["mites"]]
        out.append((np.array([row[0] for row in rows]), np.array([row[1] for row in rows])))
    return out


def normalised(scores, brightness, brightness_on, floor_on):
    """A dataset's scores as the analysis of a folder has them with those
    normalisations switched on: over all its mites and recordings."""
    if not (brightness_on or floor_on):
        return scores
    n_mites, n_recordings = scores.shape
    table = pd.DataFrame({"mite_ID": np.repeat(np.arange(n_mites), n_recordings),
                          "motion_score": scores.ravel(), "brightness": brightness.ravel()})
    return ScoreNormalizer(floor=floor_on, brightness=brightness_on).scores(table).to_numpy().reshape(scores.shape)


# ---- train and test ----

def split_mites(datasets, test_share, seed):
    """Per dataset, True for its train mites: a share of each dataset's mites
    is held out, so both sides have mites of every dataset."""
    masks = []
    for index, dataset in enumerate(datasets):
        order = list(range(len(dataset["mites"])))
        random.Random(f"{seed}/{dataset['name']}").shuffle(order)
        train = np.ones(len(order), dtype=bool)
        train[order[:round(len(order) * test_share)]] = False
        masks.append(train)
    return masks


def runs_of(datasets, scored, masks, brightness_on, floor_on, train):
    """The train or the test mites of every dataset, as LabelledRuns."""
    runs = []
    for dataset, (scores, brightness), mask in zip(datasets, scored, masks):
        run = LabelledRun(normalised(scores, brightness, brightness_on, floor_on), dataset["moving"], dataset["labelled"])
        runs.append(run.of_mites(mask if train else ~mask))
    return runs


def judge(datasets, scored, masks):
    """The normalisations and threshold that do best on the train mites, and
    how they do on the test mites."""
    best = None
    for brightness_on, floor_on in NORMALISATIONS:
        train = runs_of(datasets, scored, masks, brightness_on, floor_on, True)
        threshold, error = death_calibration.best_threshold(train)
        if best is None or error < best["train_mae"]:
            best = {"normalize_brightness": brightness_on, "normalize_floor": floor_on,
                    "threshold": threshold, "train_mae": error}
    test = runs_of(datasets, scored, masks, best["normalize_brightness"], best["normalize_floor"], False)
    best["test_mae"] = float(death_calibration.death_mae(test, [best["threshold"]])[0])
    for dataset, run in zip(datasets, test):
        best[f"test_mae {dataset['name']}"] = float(death_calibration.death_mae([run], [best["threshold"]])[0])
    return best


def search(pool, datasets, masks, metric, study, n_trials, seed):
    """Runs (or carries on) one metric's search; returns the Optuna study."""
    space = DEATH_SPACES.get(metric)
    result = optuna.create_study(
        study_name=f"{study}/{metric}", storage=STORAGE, load_if_exists=True, direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=seed, multivariate=True, n_startup_trials=min(20, n_trials // 3)),
    )
    finished = sum(t.state == optuna.trial.TrialState.COMPLETE for t in result.trials)
    if space is None:
        n_trials = 0 if finished else 1  # nothing to search: score it once
    elif not result.trials:
        start = start_params(metric)
        if "pad" in start and start["pad"] not in PADS:
            start["pad"] = MAX_PAD
        result.enqueue_trial(start)

    def objective(trial):
        params = space(trial) if space else {}
        scored = score_all(pool, datasets, metric, params)
        if not all(np.isfinite(scores).all() for scores, _brightness in scored):
            raise optuna.TrialPruned()
        outcome = judge(datasets, scored, masks)
        for key, value in outcome.items():
            trial.set_user_attr(key, value)
        trial.set_user_attr("params", Analyzer.check_metric_params(metric, params))
        return outcome["train_mae"]

    if n_trials:
        result.optimize(objective, n_trials=n_trials)
    return result


def resplit(datasets, scored, attrs, times, test_share, seed):
    """How much of the test error is the luck of the split: the mites are split
    again `times` times, the threshold chosen on each train side and judged on
    its test side, the parameters and normalisations staying as they are (so
    chosen with some of those test mites: lower than a new mite's error).
    Returns the mean and standard deviation of the test errors and the middle
    threshold."""
    errors, thresholds = [], []
    for again in range(times):
        masks = split_mites(datasets, test_share, f"{seed}/again/{again}")
        train, test = (runs_of(datasets, scored, masks, attrs["normalize_brightness"], attrs["normalize_floor"], side)
                       for side in (True, False))
        threshold = attrs["threshold"] if attrs.get("searched") == "in use" else death_calibration.best_threshold(train)[0]
        thresholds.append(threshold)
        errors.append(death_calibration.death_mae(test, [threshold])[0])
    return {"resplit_test_mae": float(np.mean(errors)), "resplit_test_sd": float(np.std(errors)),
            "resplit_threshold": float(np.median(thresholds))}


def bands(datasets, scored, masks, attrs, checks):
    """For each number of checks per mite, the band chosen on the train mites
    and what it leaves on the test mites."""
    sides = [runs_of(datasets, scored, masks, attrs["normalize_brightness"], attrs["normalize_floor"], train)
             for train in (True, False)]
    rows = []
    for allowed in checks:
        low, high = death_calibration.best_band(sides[0], attrs["threshold"], allowed)
        row = {"checks_allowed": allowed, "low": low, "high": high}
        for side, runs in zip(("train", "test"), sides):
            row.update({f"{side}_{key}": value for key, value in death_calibration.band_outcome(runs, low, high).items()})
        rows.append(row)
    return rows


def in_use(pool, datasets, masks, resplits, test_share, seed):
    """config.yaml's setup, at its own threshold, on the train and test mites."""
    mite = get_default_config().mite
    params = mite.params_for(mite.metric)
    if Analyzer.roi_padding(mite.metric, params) > MAX_PAD:
        return None
    scored = score_all(pool, datasets, mite.metric, params)
    row = {"metric": mite.metric, "searched": "in use", "trials": 0, "params": params,
           "threshold": float(mite.motion_threshold),
           "normalize_brightness": bool(mite.normalize_brightness), "normalize_floor": bool(mite.normalize_floor)}
    for side, train in (("train", True), ("test", False)):
        runs = runs_of(datasets, scored, masks, row["normalize_brightness"], row["normalize_floor"], train)
        row[f"{side}_mae"] = float(death_calibration.death_mae(runs, [row["threshold"]])[0])
        if not train:
            for dataset, run in zip(datasets, runs):
                row[f"test_mae {dataset['name']}"] = float(death_calibration.death_mae([run], [row["threshold"]])[0])
    row.update(resplit(datasets, scored, row, resplits, test_share, seed))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metrics", nargs="+", default=Analyzer.metric_names(), choices=Analyzer.metric_names(),
                        help="the metrics to search (default: all)")
    parser.add_argument("--trials", type=int, default=0,
                        help=f"trials per metric this time (default: {DEFAULT_TRIALS}, "
                             + ", ".join(f"{m} {n}" for m, n in TRIALS.items()) + ")")
    parser.add_argument("--study", default="default", help="study name; the same name carries on")
    parser.add_argument("--jobs", type=int, default=os.cpu_count(), help="worker processes")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--test-share", type=float, default=0.5, help="share of each dataset's mites held out")
    parser.add_argument("--checks", type=float, nargs="+", default=[0.25, 0.5, 1, 2],
                        help="checks by eye allowed per mite, one band for each")
    parser.add_argument("--resplits", type=int, default=50,
                        help="other splits of the mites the best of each metric is judged on too")
    parser.add_argument("--stabilize-plate", type=int, choices=[0, 1], default=None,
                        help="follow a shaking plate (default: config.yaml's mite.stabilize_plate)")
    parser.add_argument("--cache", default=str(Path(tempfile.gettempdir()) / "varroa_death_time_patches"),
                        help="where the cut patches are kept (several GB)")
    args = parser.parse_args()
    stabilize = get_default_config().mite.stabilize_plate if args.stabilize_plate is None else bool(args.stabilize_plate)

    print("Loading the labelled datasets...")
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    datasets = [load_dataset(summary, args.cache, stabilize, args.jobs)
                for summary in pipeline.list_calibration_datasets()]
    datasets = sorted((d for d in datasets if d), key=lambda d: d["name"])
    if not datasets:
        sys.exit("No labelled dataset in calibration_data/ can be read.")
    masks = split_mites(datasets, args.test_share, args.seed)
    for dataset, mask in zip(datasets, masks):
        moving = int(dataset["moving"].sum())
        print(f"  {dataset['name']}: {int(mask.sum())} train and {int((~mask).sum())} test mites, "
              f"{moving} moving and {int(dataset['labelled'].sum()) - moving} still labels")

    STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rows, band_rows = [], []
    patches = [(dataset["path"], dataset["sizes"]) for dataset in datasets]
    with ProcessPoolExecutor(args.jobs, initializer=_init_worker, initargs=(patches,)) as pool:
        current = in_use(pool, datasets, masks, args.resplits, args.test_share, args.seed)
        if current:
            print(f"\nIn use (config.yaml): {current['metric']} {current['params']} at {current['threshold']:.4g}: "
                  f"death error {current['train_mae']:.2f} train, {current['test_mae']:.2f} test (recordings)")
            rows.append(current)
        try:
            for metric in args.metrics:
                started = time.time()
                study = search(pool, datasets, masks, metric, args.study,
                               args.trials or TRIALS.get(metric, DEFAULT_TRIALS), args.seed)
                best = study.best_trial
                scored = score_all(pool, datasets, metric, best.user_attrs["params"])
                rows.append({"metric": metric, "searched": "train mites", "trials": len(study.trials),
                             **best.user_attrs,
                             **resplit(datasets, scored, best.user_attrs, args.resplits, args.test_share, args.seed)})
                print(f"  {metric:<28} {len(study.trials):>4} trials  train {best.value:.2f}  "
                      f"test {best.user_attrs['test_mae']:.2f}  ({time.time() - started:.0f} s)")
                for row in bands(datasets, scored, masks, best.user_attrs, args.checks):
                    band_rows.append({"metric": metric, **row})
        except KeyboardInterrupt:
            print("  stopped; the finished trials are kept")

    searched = sorted((r for r in rows if r["searched"] != "in use"), key=lambda r: r["train_mae"])
    if not searched:
        return
    print("\nBest of each, chosen on the train mites (mean death error, recordings):")
    print(f"  {'metric':<28}{'train':>7}{'test':>7}{'other splits':>15}{'threshold':>11}  normalised by       parameters")
    for row in searched:
        by = " + ".join(name for name, on in (("brightness", row["normalize_brightness"]),
                                              ("floor", row["normalize_floor"])) if on) or "nothing"
        again = f"{row['resplit_test_mae']:.2f} +- {row['resplit_test_sd']:.2f}"
        print(f"  {row['metric']:<28}{row['train_mae']:>7.2f}{row['test_mae']:>7.2f}{again:>15}{row['threshold']:>11.4g}  "
              f"{by:<18}  {row['params']}")
    print(f"\nBand to check by eye, for {searched[0]['metric']} (the labels standing in for the eye):")
    print(f"  {'checks allowed':>14}{'low':>9}{'high':>9}{'test error':>12}{'test checks':>13}{'test exact':>12}")
    for row in band_rows:
        if row["metric"] == searched[0]["metric"]:
            print(f"  {row['checks_allowed']:>14g}{row['low']:>9.4g}{row['high']:>9.4g}{row['test_mae']:>12.2f}"
                  f"{row['test_checks_per_mite']:>13.2f}{row['test_exact']:>12.0%}")

    stamp = f"{args.study}_{datetime.now():%Y-%m-%d_%H-%M-%S}"
    for name, table in (("optuna_death_time", rows), ("optuna_death_time_bands", band_rows)):
        if not table:
            continue
        out = pipeline.CALIBRATION_REPORTS / f"{name}_{stamp}.csv"
        fields = list(dict.fromkeys(key for row in table for key in row))
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(table)
        print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()
