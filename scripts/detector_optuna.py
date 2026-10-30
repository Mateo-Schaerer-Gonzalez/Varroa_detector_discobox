"""An Optuna search over the mite detector: the SimpleBlobDetector's settings
(config.default.yaml's `detector`) and, in a second study, a preprocessing step
before it.

Data: the frames labelled in Label Studio (a YOLO export: images/*.bmp and
labels/*.txt, one 4-corner box per mite), 398 frames and 27,505 mites from the
2021 and 2023 runs (an older, overexposed setup) and the 2025 test sessions
(today's Discobox). Detection is judged as the app detects: on the frame masked
to the plates of coords_pixel.txt, a blob kept only when its box lies in a
plate (ZoneManager.assign_mites()); a labelled mite counts when its centre lies
in a plate. A detection finds a labelled mite when their centres are less than
MATCH_PX apart, one to one (Hungarian assignment).

Frames of one session are near copies of each other, so the split is by
session: a 2025 session is a day, an older one a run of days with no day
missing. The test sessions (TEST) are half the 2025 days and one older run, so
the test set is mostly today's frames; a trial is judged on the others ("tune").

Objective, maximised: F2 of the detections on the tune frames, every labelled
mite counting the same (recall weighs four times precision: a missed mite is
lost to the analysis, a false one shows as a mite that never moves). Each trial
keeps recall, precision and F2 per year and fold as user attributes.

Two studies: "settings" (the detector's settings only, nothing in the app's
code changes) and "preprocessing" (the same plus a step before detection, which
would need a change to the detection code).

    python scripts/detector_optuna.py build --data <export folder>   # cache the frames (once)
    python scripts/detector_optuna.py check                         # the copy at APP equals the app
    python scripts/detector_optuna.py run --study settings --trials 400 --workers 8
    python scripts/detector_optuna.py run --study preprocessing --trials 400 --workers 8
    python scripts/detector_optuna.py export                        # chosen settings, evaluated
    python scripts/detector_optuna.py evaluate                      # again, in another OpenCV

Run in the base Python (Optuna is not in discobox_env); `check` and `evaluate`
need no Optuna and also run in discobox_env. Writes
results/scripts/detector_optuna.journal (the studies),
results/scripts/detector_optuna_chosen.json (the settings compared) and
results/scripts/detector_optuna_<setting>_opencv<N>.csv.gz (every labelled mite
and every detection of each); read by notebooks/detector_optuna.ipynb.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import linear_sum_assignment  # noqa: E402

import pipeline  # noqa: E402
from pipeline import plate_zones  # noqa: E402
from classes.app_config import get_default_config  # noqa: E402
from classes.scoring.analyzer import Analyzer  # noqa: E402

cv2.setNumThreads(1)
CACHE = Path(tempfile.gettempdir()) / "varroa_detector_optuna"
FRAMES, META = CACHE / "frames.npy", CACHE / "meta.json"
JOURNAL = pipeline.SCRIPTS_OUTPUT / "detector_optuna.journal"
CHOSEN = pipeline.SCRIPTS_OUTPUT / "detector_optuna_chosen.json"
DATA = ROOT / "project-2-at-2026-10-30-10-27-b73784e5"
COORDS = ROOT / plate_zones.DEFAULT_COORDS_FILE
MATCH_PX = 8.0
BETA = 2.0
# Sessions held out: three of the six 2025 days and one older run (named by its first day).
TEST = {"2025-07-30", "2025-08-04", "2025-08-08", "2023-08-22"}
SEED = 0

_detector = get_default_config().detector
# The app's settings (config.default.yaml): since 2026-10-30 those this search chose (trial 189 of "settings").
APP = dict(min_threshold=_detector.min_threshold, max_threshold=_detector.max_threshold,
           threshold_step=_detector.threshold_step, min_area=_detector.min_area, max_area=_detector.max_area,
           min_circularity=_detector.min_circularity, min_convexity=_detector.min_convexity,
           min_inertia_ratio=_detector.min_inertia_ratio, min_dist_between_blobs=_detector.min_dist_between_blobs,
           min_repeatability=_detector.min_repeatability, pre="none")
# The app's settings before (and SimpleBlobDetector's defaults for the two that were not settings then):
# the search started from them, and the notebook compares with them as "today's settings".
BEFORE = dict(min_threshold=30, max_threshold=200, threshold_step=10, min_area=40, max_area=1200,
              min_circularity=0.55, min_convexity=0.8, min_inertia_ratio=0.45, min_dist_between_blobs=10.0,
              min_repeatability=2, pre="none")


def session_of(name):
    """(year, day) of a frame from its file name: the 2025 ones start with their
    date, the older ones hold it as <recording>_<frame>_<y-m-d>_<time>."""
    if name.startswith("2025-"):
        return "2025", name[:10]
    y, m, d = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})_", name).groups()
    return y, f"{y}-{int(m):02d}-{int(d):02d}"


def runs_of(days):
    """Each older day -> the first day of its run (consecutive days)."""
    first, previous, out = None, None, {}
    for day in sorted(set(days)):
        date = np.datetime64(day)
        if previous is None or date - previous > np.timedelta64(1, "D"):
            first = day
        out[day], previous = first, date
    return out


def plates():
    """The plates of coords_pixel.txt as an (n, 4) array of x1, y1, x2, y2."""
    zones = plate_zones.build_zone_manager(COORDS).valid_zones
    rects = np.array([[z.x1, z.y1, z.x2, z.y2] for z in zones], dtype=float)
    return rects


def build(data):
    """Read every labelled frame once into FRAMES (a memory-mapped stack all
    workers share) and its labels and fold into META."""
    CACHE.mkdir(parents=True, exist_ok=True)
    images = sorted((Path(data) / "images").glob("*.bmp"))
    rects = plates()
    entries = []
    for path in images:
        name = path.stem.split("-", 1)[1]
        year, day = session_of(name)
        entries.append({"file": path.name, "name": name, "year": year, "day": day})
    runs = runs_of([e["day"] for e in entries if e["year"] != "2025"])
    shape = cv2.imread(str(images[0]), cv2.IMREAD_GRAYSCALE).shape
    stack = np.lib.format.open_memmap(FRAMES, mode="w+", dtype=np.uint8, shape=(len(images), *shape))
    for k, (path, entry) in enumerate(zip(images, entries)):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        stack[k] = image
        h, w = image.shape
        text = (Path(data) / "labels" / f"{path.stem}.txt").read_text().split()
        corners = np.array(text, dtype=float).reshape(-1, 9)[:, 1:].reshape(-1, 4, 2) * [w, h]
        centres = corners.mean(axis=1)
        inside = ((centres[:, None, 0] >= rects[:, 0]) & (centres[:, None, 0] <= rects[:, 2])
                  & (centres[:, None, 1] >= rects[:, 1]) & (centres[:, None, 1] <= rects[:, 3])).any(axis=1)
        size = corners.max(axis=1) - corners.min(axis=1)
        session = entry["day"] if entry["year"] == "2025" else runs[entry["day"]]
        entry.update(session=session, fold="test" if session in TEST else "tune",
                     labels=[[*c, *s] for c, s, i in zip(centres.tolist(), size.tolist(), inside) if i],
                     outside=int((~inside).sum()))
    stack.flush()
    META.write_text(json.dumps(entries))
    for fold in ("tune", "test"):
        part = [e for e in entries if e["fold"] == fold]
        print(fold, {y: (sum(e["year"] == y for e in part), sum(len(e["labels"]) for e in part if e["year"] == y))
                     for y in ("2021", "2023", "2025")})


def load():
    return np.load(FRAMES, mmap_mode="r"), json.loads(META.read_text())


def blob_detector(p):
    params = cv2.SimpleBlobDetector_Params()
    params.minThreshold, params.maxThreshold = p["min_threshold"], p["max_threshold"]
    params.thresholdStep = p["threshold_step"]
    params.filterByColor, params.blobColor = True, 0
    params.filterByArea, params.minArea, params.maxArea = True, p["min_area"], p["max_area"]
    params.filterByCircularity, params.minCircularity = True, p["min_circularity"]
    params.filterByConvexity, params.minConvexity = True, p["min_convexity"]
    params.filterByInertia, params.minInertiaRatio = True, p["min_inertia_ratio"]
    params.minDistBetweenBlobs = p["min_dist_between_blobs"]
    params.minRepeatability = p["min_repeatability"]
    return cv2.SimpleBlobDetector_create(params)


def prepared(image, p, inside):
    """The frame as the detector sees it: preprocessed (`pre`), then masked to
    the plates as ZoneManager.mask_image_to_valid_rois() does (white elsewhere).
    The levels a step takes are measured on the plates' pixels."""
    pre = p["pre"]
    if pre == "stretch":
        # the plates' background (a high percentile) to `stretch_level`
        level = np.percentile(image[inside], p["stretch_percentile"])
        image = np.clip(image.astype(np.float32) * (p["stretch_level"] / max(level, 1.0)), 0, 255).astype(np.uint8)
    elif pre == "clahe":
        tile = int(p["clahe_tile"])
        image = cv2.createCLAHE(clipLimit=p["clahe_clip"], tileGridSize=(tile, tile)).apply(image)
    elif pre == "flatfield":
        # divided by the light falling on it (a wide blur), the background then at `flat_level`
        light = cv2.GaussianBlur(image, (0, 0), p["flat_sigma"]).astype(np.float32)
        image = np.clip(image / np.maximum(light, 1.0) * p["flat_level"], 0, 255).astype(np.uint8)
    return np.where(inside, image, np.uint8(255))


def detect(image, p, detector, rects, inside):
    """(centres, sizes) of the blobs whose box lies in a plate."""
    found = detector.detect(prepared(image, p, inside))
    pts = np.array([[k.pt[0], k.pt[1], k.size] for k in found], dtype=float).reshape(-1, 3)
    # the box in whole pixels, cut off as a Mite's (Rect) is
    half = pts[:, 2:3] / 2
    lo, hi = np.trunc(pts[:, :2] - half), np.trunc(pts[:, :2] + half)
    kept = ((lo[:, None, 0] >= rects[:, 0]) & (hi[:, None, 0] <= rects[:, 2])
            & (lo[:, None, 1] >= rects[:, 1]) & (hi[:, None, 1] <= rects[:, 3])).any(axis=1)
    return pts[kept, :2], pts[kept, 2]


def match(labels, centres):
    """Index pairs (label, detection) closer than MATCH_PX, one to one."""
    if not len(labels) or not len(centres):
        return np.empty(0, int), np.empty(0, int)
    distance = np.linalg.norm(labels[:, None, :2] - centres[None], axis=2)
    rows, cols = linear_sum_assignment(distance)
    close = distance[rows, cols] < MATCH_PX
    return rows[close], cols[close]


def mask_of(shape):
    rects = plates()
    inside = np.zeros(shape, bool)
    for x1, y1, x2, y2 in rects:
        inside[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)] = True
    return rects, inside


def counts(p, frames, meta, which):
    """{(year, fold): [found, labelled, detected]} over the frames `which` selects."""
    detector = blob_detector(p)
    rects, inside = mask_of(frames.shape[1:])
    out = {}
    for k, entry in enumerate(meta):
        if not which(entry):
            continue
        labels = np.array(entry["labels"], dtype=float).reshape(-1, 4)
        centres, _sizes = detect(frames[k], p, detector, rects, inside)
        rows, _cols = match(labels, centres)
        total = out.setdefault((entry["year"], entry["fold"]), [0, 0, 0])
        total[0] += len(rows)
        total[1] += len(labels)
        total[2] += len(centres)
    return out


def scores(found, labelled, detected):
    recall = found / labelled if labelled else 0.0
    precision = found / detected if detected else 0.0
    b2 = BETA ** 2
    f = (1 + b2) * precision * recall / (b2 * precision + recall) if precision + recall else 0.0
    return recall, precision, f


def check(frames, meta):
    """The copy at APP finds the very blobs the app finds (Analyzer.detect on the
    masked frame, the mites ZoneManager.assign_mites() keeps)."""
    analyzer = Analyzer()
    detector = blob_detector(APP)
    rects, inside = mask_of(frames.shape[1:])
    for k in range(0, len(meta), 25):
        zone_manager = plate_zones.build_zone_manager(COORDS)
        mites = zone_manager.assign_mites(analyzer.detect(zone_manager.mask_image_to_valid_rois(np.array(frames[k]))))
        # the same blobs; a Mite's box is in whole pixels, so its centre is up to 1 px off
        app = np.array([m.home for m in mites], dtype=float).reshape(-1, 2)
        centres, _ = detect(frames[k], APP, detector, rects, inside)
        rows, cols = linear_sum_assignment(np.linalg.norm(app[:, None] - centres[None], axis=2))
        assert len(app) == len(centres) and np.abs(app[rows] - centres[cols]).max() <= 1, meta[k]["file"]
    print(f"the copy finds the app's mites on {len(range(0, len(meta), 25))} frames")


def suggest(trial, study):
    p = dict(
        min_threshold=trial.suggest_int("min_threshold", 0, 120),
        max_threshold=trial.suggest_int("max_threshold", 130, 255),
        threshold_step=trial.suggest_int("threshold_step", 4, 25),
        min_area=trial.suggest_float("min_area", 5, 120, log=True),
        max_area=trial.suggest_float("max_area", 300, 3000, log=True),
        min_circularity=trial.suggest_float("min_circularity", 0.0, 0.9),
        min_convexity=trial.suggest_float("min_convexity", 0.3, 0.99),
        min_inertia_ratio=trial.suggest_float("min_inertia_ratio", 0.0, 0.8),
        min_dist_between_blobs=trial.suggest_float("min_dist_between_blobs", 2.0, 20.0),
        min_repeatability=trial.suggest_int("min_repeatability", 1, 5),
        pre="none",
    )
    if study == "preprocessing":
        p["pre"] = trial.suggest_categorical("pre", ["none", "stretch", "clahe", "flatfield"])
        if p["pre"] == "stretch":
            p["stretch_percentile"] = trial.suggest_float("stretch_percentile", 50, 99)
            p["stretch_level"] = trial.suggest_float("stretch_level", 150, 255)
        elif p["pre"] == "clahe":
            p["clahe_clip"] = trial.suggest_float("clahe_clip", 1.0, 6.0)
            p["clahe_tile"] = trial.suggest_int("clahe_tile", 4, 32)
        elif p["pre"] == "flatfield":
            p["flat_sigma"] = trial.suggest_float("flat_sigma", 10.0, 80.0)
            p["flat_level"] = trial.suggest_float("flat_level", 150.0, 250.0)
    return p


def storage():
    import optuna
    from optuna.storages.journal import JournalFileBackend, JournalFileOpenLock
    # the default lock is a symlink, which Windows refuses without admin rights
    return optuna.storages.JournalStorage(JournalFileBackend(str(JOURNAL), lock_obj=JournalFileOpenLock(str(JOURNAL))))


def worker(study_name, trials, seed):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    frames, meta = load()
    study = optuna.load_study(study_name=study_name, storage=storage(),
                              sampler=optuna.samplers.TPESampler(multivariate=True, group=True, seed=seed,
                                                                 n_startup_trials=40))

    def objective(trial):
        result = counts(suggest(trial, study_name), frames, meta, lambda e: True)
        for (year, fold), total in result.items():
            for key, value in zip(("recall", "precision", "f2"), scores(*total)):
                trial.set_user_attr(f"{year}|{fold}|{key}", value)
        for fold in ("tune", "test"):
            total = np.sum([v for (y, f), v in result.items() if f == fold], axis=0)
            for key, value in zip(("recall", "precision", "f2"), scores(*total)):
                trial.set_user_attr(f"all|{fold}|{key}", value)
        return trial.user_attrs["all|tune|f2"]

    study.optimize(objective, n_trials=trials)


def run(study_name, trials, workers):
    import optuna
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(study_name=study_name, storage=storage(), direction="maximize", load_if_exists=True)
    if not len(study.trials):
        study.enqueue_trial({k: v for k, v in BEFORE.items() if k != "pre"} | ({"pre": "none"} if study_name == "preprocessing" else {}))
    each = -(-trials // workers)
    started = time.perf_counter()
    jobs = [subprocess.Popen([sys.executable, __file__, "worker", "--study", study_name, "--trials", str(each),
                              "--seed", str(SEED + k)]) for k in range(workers)]
    for job in jobs:
        job.wait()
    study = optuna.load_study(study_name=study_name, storage=storage())
    print(f"{study_name}: {len(study.trials)} trials, {time.perf_counter() - started:.0f} s, best {study.best_value:.4f}")


def rounded(p):
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in p.items()}


def export():
    """The settings compared (the app's before, the best trial of the settings
    study and the best one with a preprocessing step) into CHOSEN, then evaluated."""
    import optuna
    chosen = {"app": BEFORE}
    for name in ("settings", "preprocessing"):
        study = optuna.load_study(study_name=name, storage=storage())
        done = [t for t in study.trials if t.value is not None and (name == "settings" or t.params.get("pre") != "none")]
        best = max(done, key=lambda t: t.value)
        chosen[name] = rounded({**BEFORE, **best.params}) | {"trial": best.number}
    # the best trial's 9.345 px between blobs finds the very same mites as SimpleBlobDetector's 10
    # on every frame; and its settings with min_repeatability at its default too: all config.yaml can set
    chosen["settings"]["min_dist_between_blobs"] = BEFORE["min_dist_between_blobs"]
    chosen["config_only"] = chosen["settings"] | {"min_repeatability": BEFORE["min_repeatability"]}
    CHOSEN.write_text(json.dumps(chosen, indent=1))
    evaluate()


def evaluate():
    """Every labelled mite (found or not) and every detection (a mite or not) of
    each setting in CHOSEN, in this Python's OpenCV."""
    frames, meta = load()
    rects, inside = mask_of(frames.shape[1:])
    for name, p in json.loads(CHOSEN.read_text()).items():
        detector = blob_detector(p)
        rows = []
        for k, entry in enumerate(meta):
            labels = np.array(entry["labels"], dtype=float).reshape(-1, 4)
            centres, sizes = detect(frames[k], p, detector, rects, inside)
            rows_, cols = match(labels, centres)
            found = dict(zip(rows_.tolist(), cols.tolist()))
            common = {"file": entry["file"], "year": entry["year"], "session": entry["session"], "fold": entry["fold"]}
            for i, (x, y, w, h) in enumerate(labels):
                j = found.get(i)
                rows.append(common | {"kind": "label", "x": x, "y": y, "label_w": w, "label_h": h, "found": j is not None,
                                     "size": sizes[j] if j is not None else np.nan})
            matched = set(found.values())
            for j, ((x, y), size) in enumerate(zip(centres, sizes)):
                if j not in matched:
                    rows.append(common | {"kind": "false", "x": x, "y": y, "size": size})
        path = pipeline.SCRIPTS_OUTPUT / f"detector_optuna_{name}_opencv{cv2.__version__.split('.')[0]}.csv.gz"
        pd.DataFrame(rows).to_csv(path, index=False)
        print(name, path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["build", "check", "time", "run", "worker", "export", "evaluate"])
    parser.add_argument("--data", default=str(DATA))
    parser.add_argument("--study", choices=["settings", "preprocessing"], default="settings")
    parser.add_argument("--trials", type=int, default=400)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    if args.command == "build":
        build(args.data)
    elif args.command == "check":
        check(*load())
    elif args.command == "time":
        frames, meta = load()
        started = time.perf_counter()
        result = counts(APP, frames, meta, lambda e: True)
        print(f"one trial: {time.perf_counter() - started:.1f} s")
        for key, total in sorted(result.items()):
            print(key, total, "recall %.3f precision %.3f F2 %.3f" % scores(*total))
    elif args.command == "run":
        run(args.study, args.trials, args.workers)
    elif args.command == "worker":
        worker(args.study, args.trials, args.seed)
    elif args.command == "export":
        export()
    elif args.command == "evaluate":
        evaluate()


if __name__ == "__main__":
    main()
