"""An Optuna search over the constants of the scoring chain: the stabilizer, the
patch's rim, the body mask, the rays and the outline band.

Every constant the chain hard-codes (classes/scoring/plate_stabilizer.py and
Analyzer._outline_rays/_lit/outline_variability_profile/_outline_variability)
is a parameter of score() and stabilized() here; at APP they give the app's
scores exactly (`check`). Nothing in the app is changed. The patch's pad (16 px)
and the stabilizer's largest shift (12 px) stay fixed: a saved live run keeps
only 32 px round each mite (classes/storage/roi_recordings.py).

Data: every labelled (mite, recording) of the poke run (90 frames) and of the
three 30-frame datasets, the frames round the mite read once and cached
(`build`). The long run is left out: its labels are the detector's calls
(CLAUDE.md). The mites of each dataset are split in two at random (SEED): a
trial is judged on the "tune" half, and the "test" half shows how well that
carries over to mites it never saw.

Two objectives, both maximised, each the mean over the four datasets (a
threshold per dataset, as their recordings differ in length):

    f05         the best F0.5 of the calls moving (the threshold the calibration
                report would suggest, calibration.best_f05_threshold())
    separation  d' of log10(score): the distance between the means of the moving
                and the still recordings in units of their pooled standard
                deviation (scores floored at 1e-4)

Each trial also keeps, as user attributes, both on the test half (F0.5 at the
threshold chosen on the tune half) and per dataset.

    python scripts/pipeline_optuna.py build              # cache the frames (once)
    python scripts/pipeline_optuna.py check              # the copy at APP equals the app
    python scripts/pipeline_optuna.py run --trials 600 --workers 8
    python scripts/pipeline_optuna.py export             # scores of the chosen trials, for the notebook

Run in the base Python (Optuna is not in discobox_env). Writes
results/scripts/pipeline_optuna.journal (the study) and
results/scripts/pipeline_optuna_scores.csv.gz; read by notebooks/pipeline_optuna.ipynb.
"""
import argparse
import math
import os
import pickle
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pipeline  # noqa: E402
from pipeline import clips, scoring  # noqa: E402
from pipeline.calibration import dataset_library, score_cache  # noqa: E402
from classes.ground_truth import calibration  # noqa: E402
from classes.scoring import plate_stabilizer as ps  # noqa: E402
from classes.scoring.analyzer import Analyzer, NoNoiseWarning  # noqa: E402
from classes.scoring.plate_stabilizer import PlateStabilizer  # noqa: E402
import script_data  # noqa: E402

cv2.setNumThreads(1)
CACHE = Path(tempfile.gettempdir()) / "varroa_pipeline_optuna"
JOURNAL = pipeline.SCRIPTS_OUTPUT / "pipeline_optuna.journal"
SCORES = pipeline.SCRIPTS_OUTPUT / "pipeline_optuna_scores.csv.gz"
STUDY = "pipeline"
POKE_ROOT = Path(tempfile.gettempdir()) / "zzrc" / "gt"
DATASETS = {"poke_test_oct": POKE_ROOT, "ground_truth_60min": None, "ground_truth_90min": None, "sample_data": None}
PAD, MARGIN, REACH_CAP = 16, 32, 12.0
SEED = 0
INTER = {"linear": cv2.INTER_LINEAR, "cubic": cv2.INTER_CUBIC, "lanczos": cv2.INTER_LANCZOS4}

# The app's constants: trial 228 of the first search (2026-10-27), rounded, without its relative 0.491 (taken out the same day)
APP = dict(stab_pad=4, stab_rim=8, stab_share=0.241, stab_grow=4, stab_interp="linear",
           rim=3, body_share=0.355, edge_share=0.226, grow=0, darkest_n=8,
           angles=128, ray_step=0.5, reach=11.4, width=1.04, ray_interp="linear", relative=0.0)
# The app on the morning of 2026-10-27 (body mask and ray edge both at 0.3 of the
# darkest): trial 0 of the first search, "app now" in its notebook
EDGE_03 = dict(stab_pad=8, stab_rim=6, stab_share=0.3, stab_grow=2, stab_interp="lanczos",
               rim=6, body_share=0.3, edge_share=0.3, grow=2, darkest_n=30,
               angles=64, ray_step=0.5, reach=13.0, width=1.5, ray_interp="linear", relative=0.0)
# The committed code before 2026-10-27: the ray edge at half the darkest (trial 1)
BEFORE = {**EDGE_03, "edge_share": 0.5}


# ---------------------------------------------------------------- the chain, parametrised
def centres(patches, p):
    """plate_stabilizer._centres() with its rim, share and growth as parameters."""
    height, width = patches.shape[1:]
    rim_px = p["stab_rim"]
    rim = np.ones((height, width), dtype=bool)
    rim[rim_px:-rim_px, rim_px:-rim_px] = False
    if rim.all():
        return None
    plate = np.median(patches[:, rim], axis=1)
    if plate.min() <= 0:
        return None
    dark = np.clip(1 - patches / plate[:, None, None], 0, None)
    still = dark.mean(axis=0)
    if still[~rim].max() <= 0:
        return None
    darkest = np.sort(still[~rim])[-p["darkest_n"]:].mean()
    dark_enough = (still > p["stab_share"] * darkest) & ~rim
    pieces = cv2.connectedComponents(dark_enough.astype(np.uint8))[1]
    yy, xx = np.ogrid[:height, :width]
    from_middle = np.hypot(yy - (height - 1) / 2, xx - (width - 1) / 2)
    body = (pieces == pieces.ravel()[np.where(dark_enough, from_middle, np.inf).argmin()]).astype(np.uint8)
    if p["stab_grow"]:
        body = cv2.dilate(body, np.ones((3, 3), np.uint8), iterations=p["stab_grow"])
    body = body.astype(np.float32)
    middle = ps._weighted_centres((still * body)[None])
    found = ps._weighted_centres(dark * body)
    if middle is None or found is None:
        return None
    steps = np.round(found - middle).astype(int)
    if not steps.any():
        return found
    reach = int(np.abs(steps).max())
    around = np.pad(body, reach)
    moved = np.stack([around[reach - dy:reach - dy + height, reach - dx:reach - dx + width] for dx, dy in steps])
    return ps._weighted_centres(dark * moved)


def shifts_of(frames, box, p):
    """PlateStabilizer.shifts() of one mite: its own centre's shift, zeros where it is lost."""
    pad = p["stab_pad"]
    patches = ps._gray(ps._patches(frames, box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))
    found = centres(patches, p)
    if found is None or not np.isfinite(found).all():
        return np.zeros((len(frames), 2))
    return np.clip(found - found[0], -REACH_CAP, REACH_CAP)


def cut(frames, box, shifts, p):
    """PlateStabilizer.cut() with its interpolation as a parameter, grey (N, h, w) float32."""
    height, width = frames[0].shape[:2]
    x1, y1 = max(0, box[0] - PAD), max(0, box[1] - PAD)
    x2, y2 = min(width, box[2] + PAD), min(height, box[3] + PAD)
    out = np.empty((len(frames), y2 - y1, x2 - x1), dtype=np.float32)
    for index, (frame, (dx, dy)) in enumerate(zip(frames, np.asarray(shifts, dtype=float).tolist())):
        m = math.ceil(max(abs(dx), abs(dy))) + ps._LANCZOS_REACH
        patch = ps._patch(frame, x1 - m, y1 - m, x2 + m, y2 + m).astype(np.float32)
        patch = cv2.warpAffine(patch, ps._move(-dx, -dy), patch.shape[1::-1], flags=INTER[p["stab_interp"]],
                               borderMode=cv2.BORDER_REFLECT101)
        out[index] = patch[m:patch.shape[0] - m, m:patch.shape[1] - m]
    return out


def score(gray, p):
    """Analyzer._outline_variability() of a grey (N, H, W) float32 patch, every constant a parameter."""
    height, width = gray.shape[1:]
    rim_px = p["rim"]
    edge = np.ones((height, width), dtype=bool)
    edge[rim_px:-rim_px, rim_px:-rim_px] = False
    plate = np.median(gray[:, edge], axis=1)
    if plate.min() <= 0:
        return 0.0
    light = float(plate.mean())
    lit = (gray * (light / plate)[:, None, None]).astype(np.float32)
    dark = np.clip(1 - lit / light, 0, None)
    still = dark.mean(axis=0)
    margin = max(PAD - 8, 0)
    near = np.zeros((height, width), dtype=bool)
    near[margin:height - margin, margin:width - margin] = True
    darkest = np.sort(still.ravel())[-p["darkest_n"]:].mean()
    if not near.any() or still[near].max() <= 0:
        return 0.0
    dark_enough = (still > p["body_share"] * darkest) & near
    pieces = cv2.connectedComponents(dark_enough.astype(np.uint8))[1]
    yy, xx = np.mgrid[:height, :width]
    from_middle = np.hypot(yy - (height - 1) / 2, xx - (width - 1) / 2)
    body = (pieces == pieces.ravel()[np.where(dark_enough, from_middle, np.inf).argmin()]).astype(np.uint8)
    if p["grow"]:
        body = cv2.dilate(body, np.ones((3, 3), np.uint8), iterations=p["grow"])
    weight = dark * body
    total = weight.sum(axis=(1, 2))
    if total.min() <= 0:
        return 0.0
    centre_x, centre_y = (weight * xx).sum(axis=(1, 2)) / total, (weight * yy).sum(axis=(1, 2)) / total

    angles, ray_step = p["angles"], p["ray_step"]
    reach = min(p["reach"], centre_x.min(), centre_y.min(), width - 1 - centre_x.max(), height - 1 - centre_y.max())
    if reach < 2:
        return 0.0
    angle = np.arange(angles) * (2 * np.pi / angles)
    along = np.arange(0, reach, ray_step)
    ray_x, ray_y = np.outer(np.cos(angle), along), np.outer(np.sin(angle), along)
    more = {} if p["ray_interp"] == "linear" else {"borderMode": cv2.BORDER_REFLECT101}
    unrolled = np.array([
        cv2.remap(frame, (x + ray_x).astype(np.float32), (y + ray_y).astype(np.float32), INTER[p["ray_interp"]], **more)
        for frame, x, y in zip(lit, centre_x.tolist(), centre_y.tolist())
    ])
    past_body = 1 - unrolled.mean(axis=0) / light < p["edge_share"] * darkest
    body_ends = np.where(past_body.any(axis=1), past_body.argmax(axis=1), len(along) - 1)
    variance = unrolled.var(axis=0)
    away = np.abs(np.arange(variance.shape[1])[None] - body_ends[:, None]) * ray_step
    on_outline = away <= p["width"]
    profile = (variance * on_outline).sum(axis=1) / on_outline.sum(axis=1)
    if float(profile.mean()) < 1e-6:
        return 0.0
    noise = float(np.median(lit[:, edge].var(axis=0)))
    if noise > 0:
        profile = profile / noise
    mean = float(profile.mean())
    direction = np.exp(2j * np.pi * np.arange(len(profile)) / len(profile))
    return float(np.abs((profile * direction).mean())) / mean ** p["relative"]


def scored(pair, p):
    frames, box = pair["frames"], pair["box"]
    return score(cut(frames, box, shifts_of(frames, box, p), p), p)


# ---------------------------------------------------------------- the data
def _region(dataset, data_dir, loader, mite, recording):
    """(frames, box in them) round one mite in one recording, where a live run followed it to."""
    name = dataset["recordings"][recording]["name"]
    placed = loader.placements(name) if hasattr(loader, "placements") else None
    box = placed[loader.number_at(mite["x"], mite["y"])] if placed else None
    if box is None:
        box = score_cache.mite_boxes([mite])[mite["id"]]
    box = tuple(int(round(v)) for v in box)
    x0, y0, x_end, y_end = clips.bounds([(box[0] - PAD, box[1] - PAD, box[2] + PAD, box[3] + PAD)], scoring.STABILIZE_MARGIN)
    frames = np.asarray(loader.load_recording_region(name, x0, y0, x_end, y_end))
    return frames, (box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0)


def build():
    CACHE.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    for name, root in DATASETS.items():
        dataset = dataset_library.read_dataset(name, root or pipeline.RECORDINGS_ROOT)
        data_dir = Path(dataset["data_dir"])
        loader = score_cache.open_recordings(data_dir)
        mites, moving, labelled = script_data.labels_of(dataset)
        ids = [m["id"] for m in mites]
        tune = set(rng.permutation(ids)[: len(ids) // 2].tolist())
        pairs, started = [], time.perf_counter()
        for i, mite in enumerate(mites):
            for recording in np.flatnonzero(labelled[i]):
                frames, box = _region(dataset, data_dir, loader, mite, int(recording))
                if frames.size == 0:
                    continue
                pairs.append({"dataset": name, "mite": mite["id"], "recording": int(recording), "moving": bool(moving[i, recording]),
                              "fold": "tune" if mite["id"] in tune else "test", "frames": frames, "box": box})
        with open(CACHE / f"{name}.pkl", "wb") as f:
            pickle.dump(pairs, f, protocol=pickle.HIGHEST_PROTOCOL)
        size = sum(p["frames"].nbytes for p in pairs) / 1e6
        print(f"{name}: {len(pairs)} pairs, {size:.0f} MB, {time.perf_counter() - started:.0f} s", flush=True)


def load_pairs():
    pairs = []
    for name in DATASETS:
        with open(CACHE / f"{name}.pkl", "rb") as f:
            pairs += pickle.load(f)
    return pairs


def check(pairs):
    """The copy at APP against the app's own stabilizer, cut and score."""
    worst, lost = 0.0, 0
    for pair in pairs:
        frames, box = pair["frames"], pair["box"]
        shifts = PlateStabilizer().shifts(frames, [box])[0]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NoNoiseWarning)
            app = float(Analyzer._motion_score(PlateStabilizer.cut(frames, box, PAD, shifts), "outline_variability"))
        mine = scored(pair, APP)
        lost += not np.array_equal(shifts, shifts_of(frames, box, APP))
        worst = max(worst, abs(app - mine))
    print(f"{len(pairs)} pairs: largest |app - copy| = {worst:.3g}; shifts differ in {lost}")
    return worst


# ---------------------------------------------------------------- the search
def metrics(frame, threshold=None):
    """(best F0.5, its threshold, d' of log10 scores) of one dataset's rows; with `threshold`, F0.5 at it."""
    s, m = frame["score"].to_numpy(), frame["moving"].to_numpy()
    if not calibration.has_both_classes(m):
        return None
    if threshold is None:
        threshold = calibration.best_f05_threshold(s, m)
    f05 = calibration.confusion(s, m, threshold)["f05"] or 0.0
    log = np.log10(np.maximum(s, 1e-4))
    pooled = math.sqrt((log[m].var() + log[~m].var()) / 2) or 1e-9
    return f05, threshold, float((log[m].mean() - log[~m].mean()) / pooled)


def evaluate(pairs, p):
    """Per dataset: tune F0.5 and d', the tune threshold, test F0.5 at it and test d'."""
    rows = pd.DataFrame([{"dataset": q["dataset"], "fold": q["fold"], "moving": q["moving"], "score": scored(q, p)} for q in pairs])
    out = {}
    for name, part in rows.groupby("dataset"):
        tune = metrics(part[part["fold"] == "tune"])
        test_part = part[part["fold"] == "test"]
        if tune is None:
            continue
        test_f05 = metrics(test_part, tune[1])
        test_sep = metrics(test_part)
        out[name] = {"f05": tune[0], "threshold": tune[1], "separation": tune[2],
                     "test_f05": test_f05[0] if test_f05 else None, "test_separation": test_sep[2] if test_sep else None}
    return out


def suggest(trial):
    return dict(
        stab_pad=trial.suggest_int("stab_pad", 4, 12),
        stab_rim=trial.suggest_int("stab_rim", 3, 8),
        stab_share=trial.suggest_float("stab_share", 0.1, 0.6),
        stab_grow=trial.suggest_int("stab_grow", 0, 4),
        stab_interp=trial.suggest_categorical("stab_interp", ["lanczos", "cubic", "linear"]),
        rim=trial.suggest_int("rim", 3, 8),
        body_share=trial.suggest_float("body_share", 0.1, 0.6),
        edge_share=trial.suggest_float("edge_share", 0.15, 0.7),
        grow=trial.suggest_int("grow", 0, 4),
        darkest_n=trial.suggest_int("darkest_n", 5, 80, log=True),
        angles=trial.suggest_categorical("angles", [32, 64, 128]),
        ray_step=trial.suggest_categorical("ray_step", [0.25, 0.5, 1.0]),
        reach=trial.suggest_float("reach", 8.0, 16.0),
        width=trial.suggest_float("width", 0.5, 3.0),
        ray_interp=trial.suggest_categorical("ray_interp", ["linear", "cubic", "lanczos"]),
        relative=trial.suggest_float("relative", 0.0, 1.0),
    )


def storage():
    import optuna
    from optuna.storages.journal import JournalFileBackend, JournalFileOpenLock
    # the default lock is a symlink, which Windows refuses without admin rights
    return optuna.storages.JournalStorage(JournalFileBackend(str(JOURNAL), lock_obj=JournalFileOpenLock(str(JOURNAL))))


def worker(trials, seed):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    pairs = load_pairs()
    study = optuna.load_study(study_name=STUDY, storage=storage(),
                              sampler=optuna.samplers.TPESampler(multivariate=True, seed=seed, n_startup_trials=40))

    def objective(trial):
        result = evaluate(pairs, suggest(trial))
        for name, values in result.items():
            for key, value in values.items():
                trial.set_user_attr(f"{name}|{key}", value)
        mean = lambda key: float(np.mean([v[key] for v in result.values() if v[key] is not None]))
        trial.set_user_attr("test_f05", mean("test_f05"))
        trial.set_user_attr("test_separation", mean("test_separation"))
        return mean("f05"), mean("separation")

    study.optimize(objective, n_trials=trials)


def run(trials, workers):
    import optuna
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(study_name=STUDY, storage=storage(), directions=["maximize", "maximize"], load_if_exists=True)
    if not len(study.trials):
        study.enqueue_trial(APP)
        study.enqueue_trial(BEFORE)
    each = -(-trials // workers)
    started = time.perf_counter()
    jobs = [subprocess.Popen([sys.executable, __file__, "worker", "--trials", str(each), "--seed", str(SEED + k)])
            for k in range(workers)]
    for job in jobs:
        job.wait()
    print(f"{len(optuna.load_study(study_name=STUDY, storage=storage()).trials)} trials, {time.perf_counter() - started:.0f} s")


def export(pairs):
    """Scores of every pair at APP, BEFORE and the Pareto trials, for the notebook."""
    import optuna
    study = optuna.load_study(study_name=STUDY, storage=storage())
    chosen = {"app": APP, "before": BEFORE}
    for trial in study.best_trials:
        chosen[f"trial {trial.number}"] = {**APP, **trial.params}
    rows = []
    for label, p in chosen.items():
        for q in pairs:
            rows.append({"setting": label, "dataset": q["dataset"], "mite": q["mite"], "recording": q["recording"],
                         "fold": q["fold"], "moving": q["moving"], "score": scored(q, p)})
    pd.DataFrame(rows).to_csv(SCORES, index=False)
    print(f"{len(chosen)} settings x {len(pairs)} pairs -> {SCORES}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["build", "check", "time", "run", "worker", "export"])
    parser.add_argument("--trials", type=int, default=600)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    if args.command == "build":
        build()
    elif args.command == "check":
        check(load_pairs())
    elif args.command == "time":
        pairs = load_pairs()
        started = time.perf_counter()
        result = evaluate(pairs, APP)
        print(f"one trial: {time.perf_counter() - started:.1f} s", result)
    elif args.command == "run":
        run(args.trials, args.workers)
    elif args.command == "worker":
        worker(args.trials, args.seed)
    elif args.command == "export":
        export(load_pairs())


if __name__ == "__main__":
    main()
