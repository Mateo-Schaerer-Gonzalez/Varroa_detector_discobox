"""Bayesian search (Optuna, TPE) of every movement score's parameters against the
saved ground truth.

Every (mite, recording) labelled moving or still in calibration_data/ is scored
as a calibration would score it (see tune_optical_flow.load_observations()), and
each metric's parameters are searched for the best AUC. A metric without
parameters is scored once. Each search starts from the metric's defaults, with
config.yaml's values for the configured metric.

With few labelled mites the best of many trials partly fits noise. The mites are
therefore split into two halves, and each metric is searched twice:

    <study>/<metric>           searched on all mites
    <study>/<metric>/holdout   searched on half A only, then judged on half B,
                               which the search never saw: the honest estimate

The studies are kept in calibration_data/reports/optuna_metrics.db, so running
again with the same --study name carries on where it stopped (Ctrl+C is safe).
notebooks/metric_calibration.ipynb draws the results.

    python scripts/optuna_metrics.py                          # every metric
    python scripts/optuna_metrics.py --metrics optical_flow --trials 500
    python scripts/optuna_metrics.py --study shake --shake 1  # as if the plate shook

The best of each is written to calibration_data/reports/optuna_metrics_<study>_<time>.csv.
"""
import argparse
import csv
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import optuna

import pipeline
from classes import calibration
from classes.analyzer import Analyzer
from classes.app_config import get_default_config
from tune_optical_flow import POLY_SIGMA, evaluate, load_observations

STORAGE_FILE = pipeline.CALIBRATION_REPORTS / "optuna_metrics.db"
STORAGE = f"sqlite:///{STORAGE_FILE.as_posix()}"
PADS = [0, 4, 8, 12, 16, 20, 24]
FRAMES = 30  # per recording; optical_flow's `step` must stay below it


def _top_n(trial):
    # A mite's box holds a few hundred pixels; more than that is the whole box.
    return {"n": trial.suggest_int("n", 1, 1000, log=True)}


def _binary_flux(trial):
    return {"threshold": trial.suggest_int("threshold", 10, 245), **_top_n(trial)}


def _optical_flow(trial):
    """Farneback wants odd window sizes; poly_sigma follows poly_n as the
    OpenCV docs advise."""
    params = {
        "pad": trial.suggest_categorical("pad", PADS),
        "window": trial.suggest_int("window", 3, 25, step=2),
        "n": trial.suggest_int("n", 5, 300, log=True),
        "step": trial.suggest_int("step", 1, FRAMES - 1),
        "winsize": trial.suggest_int("winsize", 5, 51, step=2),
        "levels": trial.suggest_int("levels", 1, 4),
        "poly_n": trial.suggest_categorical("poly_n", [5, 7]),
        "iterations": trial.suggest_int("iterations", 1, 6),
        "stabilize": trial.suggest_categorical("stabilize", [0, 1]),
    }
    params["poly_sigma"] = POLY_SIGMA[params["poly_n"]]
    return params


# How each metric's parameters are searched; a metric missing here has none.
SPACES = {
    "topN_variability": _top_n,
    "topN_temporal_range": _top_n,
    "topN_vector_temporal_range": _top_n,
    "topN_binary_flux": _binary_flux,
    "optical_flow": _optical_flow,
}
# Trials per search: a single parameter is mapped out long before 300.
TRIALS = {"optical_flow": 300, "topN_binary_flux": 150}
DEFAULT_TRIALS = 60


def study_name(study, metric, holdout):
    return f"{study}/{metric}" + ("/holdout" if holdout else "")


def split_halves(mites, seed=0):
    """True for the observations of half A of the mites. Split by mite, so one
    mite's recordings never sit on both sides."""
    keys = sorted(set(mites))
    random.Random(seed).shuffle(keys)
    half_a = set(keys[::2])
    return np.array([m in half_a for m in mites])


def start_params(metric):
    """Where a search starts: the metric's defaults, or config.yaml's values
    for the metric it uses. Only the searched parameters are passed on."""
    params = Analyzer.metric_defaults(metric)
    config = get_default_config().mite
    if metric == config.metric:
        params.update(config.params_for(metric))
    return {k: v for k, v in params.items() if k != "poly_sigma"}


# Worker processes get the observations once, not with every trial.
_ROIS = None


def _init_worker(rois):
    global _ROIS
    _ROIS = rois


def _score_chunk(job):
    metric, params, indices = job
    cuts = _ROIS[Analyzer.roi_padding(metric, params)]
    return [Analyzer._motion_score(cuts[i], metric, params) for i in indices]


def score_all(pool, n_obs, jobs, metric, params):
    """Every observation scored with `params`, spread over the worker pool."""
    chunks = [list(c) for c in np.array_split(np.arange(n_obs), jobs * 2) if len(c)]
    parts = pool.map(_score_chunk, [(metric, params, c) for c in chunks])
    return np.array([s for part in parts for s in part])


def summarize(scores, moving, in_a):
    """AUC, threshold and accuracy on all mites; AUC on each half; and the
    accuracy on half B at the threshold that is best on half A."""
    result = evaluate(scores, moving)
    for half, mask in (("a", in_a), ("b", ~in_a)):
        result[f"auc_{half}"] = calibration.auc(scores[mask], moving[mask]) if calibration.has_both_classes(moving[mask]) else np.nan
    threshold_a = calibration.best_threshold(scores[in_a], moving[in_a])
    result["accuracy_b"] = calibration.confusion(scores[~in_a], moving[~in_a], threshold_a)["accuracy"]
    return result


def search(pool, jobs, metric, study, holdout, n_trials, moving, in_a, seed):
    """Runs (or carries on) one search; returns the Optuna study."""
    tune = in_a if holdout else np.ones_like(in_a)
    space = SPACES.get(metric)
    result = optuna.create_study(
        study_name=study_name(study, metric, holdout), storage=STORAGE, load_if_exists=True,
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed, multivariate=True, n_startup_trials=min(20, n_trials // 3)),
    )
    finished = sum(t.state.is_finished() for t in result.trials)
    if space is None:
        n_trials = 0 if finished else 1  # nothing to search: score it once
    elif not result.trials:
        result.enqueue_trial(start_params(metric))

    def objective(trial):
        params = space(trial) if space else {}
        scores = score_all(pool, len(moving), jobs, metric, params)
        if not np.isfinite(scores).all():
            raise optuna.TrialPruned()
        for key, value in summarize(scores, moving, in_a).items():
            trial.set_user_attr(key, float(value))
        trial.set_user_attr("params", Analyzer.check_metric_params(metric, params))
        return evaluate(scores[tune], moving[tune])["auc"]

    if n_trials:
        result.optimize(objective, n_trials=n_trials)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metrics", nargs="+", default=Analyzer.metric_names(), choices=Analyzer.metric_names(),
                        help="the metrics to search (default: all)")
    parser.add_argument("--trials", type=int, default=0,
                        help=f"trials per search this time (default: {DEFAULT_TRIALS}, "
                             + ", ".join(f"{m} {n}" for m, n in TRIALS.items()) + ")")
    parser.add_argument("--study", default="default", help="study name; the same name carries on")
    parser.add_argument("--jobs", type=int, default=os.cpu_count(), help="worker processes")
    parser.add_argument("--shake", type=float, default=0.0, help="shake the plate by this many pixels (std) per frame")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--stabilize-plate", type=int, choices=[0, 1], default=None,
                        help="follow a shaking plate (default: config.yaml's mite.stabilize_plate)")
    args = parser.parse_args()

    print("Loading labelled observations...")
    rois, moving, mites, _recordings = load_observations(PADS, args.shake, args.seed, args.stabilize_plate)
    if not calibration.has_both_classes(moving):
        sys.exit("Need both moving and still labels in calibration_data/ to tune anything.")
    print(f"{len(moving)} observations ({moving.sum()} moving, {(~moving).sum()} still), {len(set(mites))} mites")
    in_a = split_halves(mites, args.seed)

    STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rows = []
    with ProcessPoolExecutor(args.jobs, initializer=_init_worker, initargs=(rois,)) as pool:
        try:
            for metric in args.metrics:
                n_trials = args.trials or TRIALS.get(metric, DEFAULT_TRIALS)
                for holdout in (False, True):
                    started = time.time()
                    study = search(pool, args.jobs, metric, args.study, holdout, n_trials, moving, in_a, args.seed)
                    best = study.best_trial
                    rows.append({"metric": metric, "searched_on": "half A" if holdout else "all",
                                 "trials": len(study.trials), "auc_searched": best.value,
                                 **{k: best.user_attrs[k] for k in ("auc", "auc_a", "auc_b", "accuracy",
                                                                    "accuracy_b", "threshold")},
                                 "params": best.user_attrs["params"]})
                    print(f"  {study.study_name:<45} {len(study.trials):>4} trials  AUC {best.value:.4f}  "
                          f"half B {best.user_attrs['auc_b']:.4f}  ({time.time() - started:.0f} s)")
        except KeyboardInterrupt:
            print("  stopped; the finished trials are kept")

    if not rows:
        return
    print("\nBest of each, by the honest estimate (searched on half A, judged on half B):")
    print(f"  {'metric':<28}{'AUC B':>8}{'acc. B':>8}   parameters")
    for row in sorted((r for r in rows if r["searched_on"] == "half A"), key=lambda r: -r["auc_b"]):
        print(f"  {row['metric']:<28}{row['auc_b']:>8.4f}{row['accuracy_b']:>8.3f}   {row['params']}")

    out = pipeline.CALIBRATION_REPORTS / f"optuna_metrics_{args.study}_{datetime.now():%Y-%m-%d_%H-%M-%S}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSummary: {out}")


if __name__ == "__main__":
    main()
