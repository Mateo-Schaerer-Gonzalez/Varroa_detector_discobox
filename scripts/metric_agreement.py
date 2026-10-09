"""Do the movement scores agree with each other? The measurements behind
notebooks/metric_agreement.ipynb.

Every mite of the longest labelled run in calibration_data/ gets, per recording,
the score of every metric of classes/analyzer.py, with config.yaml's parameters,
and the leg movement of classes/leg_tracker.py (scores()). The notebook then
asks whether they call the same recordings moving (calls(), kappa(), votes())
and whether they put the mites in the same order (rank_correlation(),
concordance(), per_mite()).

The patches are those scripts/optuna_death_time.py cuts and keeps; the scores
are kept beside them, so only the first run is slow (about a minute).

    python scripts/metric_agreement.py     # scores, prints how far they agree
"""
import hashlib
import inspect
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import yaml
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata

import alive_dead_features as adf
import leg_tracks
import pipeline
from classes import death_calibration
from classes.analyzer import Analyzer
from classes.app_config import TEMPLATE_CONFIG_PATH, get_default_config
from classes.death_calibration import LabelledRun
from classes.leg_tracker import LegTracker
from optuna_death_time import MAX_PAD, load_dataset

LEGS = "leg_tracker"  # not a metric of the app: the largest swing of a followed leg, in pixels


# ---- the scores ----

def other_runs(run, cache=adf.CACHE, jobs=None):
    """The other labelled runs saved in calibration_data/, the short ones, as
    adf.load_run() gives the longest."""
    runs = []
    for summary in pipeline.list_calibration_datasets():
        saved = pipeline._read_dataset(summary["id"], pipeline.CALIBRATION_LIBRARY)
        if saved["name"] == run.name:
            continue
        dataset = load_dataset({"id": summary["id"]}, cache, get_default_config().mite.stabilize_plate, jobs or os.cpu_count())
        if dataset:
            runs.append(adf.Run(dataset["name"], dataset["mites"], np.array(saved["times"], dtype=float),
                                dataset["moving"], dataset["labelled"], dataset["sizes"], dataset["path"]))
    return runs


def metric_params():
    """Every metric of the app with the parameters it would be scored with:
    config.yaml's, the defaults in classes/analyzer.py for those left out."""
    mite = get_default_config().mite
    return {metric: Analyzer.check_metric_params(metric, mite.params_for(metric)) for metric in Analyzer.metric_names()}


def config_thresholds():
    """The movement threshold saved for each metric: config.yaml's, and
    config.default.yaml's for a metric this machine's file does not have yet."""
    with open(TEMPLATE_CONFIG_PATH, encoding="utf-8") as file:
        saved = dict(yaml.safe_load(file)["mite"].get("metric_thresholds") or {})
    saved.update(get_default_config().mite.metric_thresholds or {})
    return {metric: float(saved[metric]) for metric in Analyzer.metric_names() if metric in saved}


def _score_mite(job):
    """One mite's score in every recording by every metric, as
    Analyzer.score_pool() records it: {metric: (recordings,)}."""
    path, mite, height, width, params = job
    patches = np.load(path, mmap_mode="r")
    mine = np.asarray(patches[mite, :, :, :height + 2 * MAX_PAD, :width + 2 * MAX_PAD])
    out = {}
    for metric, values in params.items():
        edge = MAX_PAD - Analyzer.roi_padding(metric, values)
        box = mine[:, :, edge:mine.shape[2] - edge, edge:mine.shape[3] - edge]
        out[metric] = [float(Analyzer._motion_score(roi, metric, values)) for roi in box]
    return out


def scores(run, cache=adf.CACHE, jobs=None, legs=True):
    """{name: (mites, recordings)}: the score of every metric of the app, and
    with `legs`, under LEGS, the leg tracker's movement. Kept in `cache`."""
    params = metric_params()
    source = inspect.getsource(Analyzer) + inspect.getsource(_score_mite) + json.dumps(params, sort_keys=True) + run.path
    path = Path(cache) / f"metric_agreement-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}.npz"
    if path.is_file():
        kept = np.load(path)
        table = {name: kept[name] for name in kept.files}
    else:
        work = [(run.path, mite, *run.sizes[mite], params) for mite in range(len(run.mites))]
        with ProcessPoolExecutor(jobs or os.cpu_count()) as pool:
            rows = list(pool.map(_score_mite, work))
        table = {metric: np.array([row[metric] for row in rows]) for metric in params}
        np.savez(path, **table)
    if legs:
        per = leg_tracks.frames_per_recording(run)
        table[LEGS] = np.array([LegTracker.movement(found, per) for found in leg_tracks.follow_run(run, cache)])
    return table


def same(table):
    """The pairs of scores that are the same numbers, as two metrics are when
    the parameters of one make it the other: [(name, name), ...]."""
    names = list(table)
    return [(first, second) for index, first in enumerate(names) for second in names[index + 1:]
            if np.allclose(table[first], table[second], rtol=1e-5, atol=1e-5)]


# ---- still or moving ----

def best_thresholds(table, run):
    """Per score, the threshold that puts this run's deaths closest to where
    the labels put them (death_calibration.best_threshold()), and that error
    in recordings: {name: (threshold, error)}."""
    return {name: death_calibration.best_threshold([LabelledRun(values, run.moving, run.labelled)])
            for name, values in table.items()}


def matched_thresholds(table, run):
    """Per score, the threshold at which it calls as many of the labelled
    recordings moving as the labels do. Every score then makes the same
    number of calls, and they can only differ in which ones."""
    wanted = int(run.moving.sum())
    return {name: float(np.sort(values[run.labelled])[-wanted]) for name, values in table.items()}


def calls(table, thresholds):
    """{name: (mites, recordings) bool}: moving where the score reaches its threshold."""
    return {name: table[name] >= thresholds[name] for name in thresholds}


def kappa(first, second):
    """Cohen's kappa of two sets of calls: how much more often they agree
    than two that call as many moving, each at random, would. 1: always,
    0: no more than by chance. When few are moving it is about the share of
    their moving calls the two have in common (their F1)."""
    first, second = np.asarray(first, dtype=bool).ravel(), np.asarray(second, dtype=bool).ravel()
    agree = (first == second).mean()
    by_chance = first.mean() * second.mean() + (1 - first.mean()) * (1 - second.mean())
    return float((agree - by_chance) / (1 - by_chance)) if by_chance < 1 else np.nan


def pairwise(values, measure, where=None):
    """`measure(a, b)` for every pair of {name: array}, over the cells of
    `where` when given: (names, names)."""
    names = list(values)
    cut = [values[name] if where is None else values[name][where] for name in names]
    out = np.ones((len(names), len(names)))
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            out[i, j] = out[j, i] = measure(cut[i], cut[j])
    return out


def votes(called):
    """How many of the scores call each mite-recording moving: (mites, recordings)."""
    return np.sum(list(called.values()), axis=0)


def agreeing(agreement, names, level=0.85):
    """The scores in groups that make about the same calls, the largest group
    first: `agreement` is their pairwise() kappa, and two groups are one when
    their scores' kappas are `level` or more in the mean (average linkage)."""
    joined = linkage(squareform(1 - agreement, checks=False), "average")
    group = fcluster(joined, 1 - level, "distance")
    groups = [[name for name, of in zip(names, group) if of == which] for which in np.unique(group)]
    return sorted(groups, key=len, reverse=True)


# ---- the order of the mites ----

def rank_correlation(first, second):
    """Spearman's: 1 when two sets of values put their items in the same
    order, 0 when the orders have nothing to do with each other. nan when
    one of them is the same for every item."""
    first, second = np.ravel(first), np.ravel(second)
    if np.ptp(first) == 0 or np.ptp(second) == 0:
        return np.nan
    return float(np.corrcoef(rankdata(first), rankdata(second))[0, 1])


def by_recording(first, second, where, at_least=5):
    """rank_correlation() among the mites of one recording that are in `where`
    (mites, recordings), for every recording that has `at_least` of them:
    (recordings,), nan for the others."""
    out = np.full(first.shape[1], np.nan)
    for at in range(first.shape[1]):
        here = where[:, at]
        if here.sum() >= at_least:
            out[at] = rank_correlation(first[here, at], second[here, at])
    return out


def concordance(values):
    """Kendall's W of {name: (items,)}: how far all of them put the items in
    one order. 1: the same order, 0: none in common. It is the mean
    rank_correlation() of all pairs, brought to 0..1 (items of equal value
    share a rank, and W is corrected for them)."""
    ranks = np.array([rankdata(column) for column in values.values()])
    judges, items = ranks.shape
    spread = ((ranks.sum(axis=0) - judges * (items + 1) / 2) ** 2).sum()
    tied = sum(float((count ** 3 - count).sum()) for count in (np.unique(row, return_counts=True)[1] for row in ranks))
    return float(12 * spread / (judges ** 2 * (items ** 3 - items) - judges * tied))


def deaths(run, called):
    """Per mite, the recording it dies at by `called` (mites, recordings): the
    one after its last movement, 0 for a mite that never moves, counted in
    its labelled recordings as classes/death_calibration.py counts."""
    return LabelledRun(np.zeros(called.shape), run.moving, run.labelled).deaths(called)


def above_floor(values, labelled):
    """Per mite, how far its score is above its own floor in the mean: the
    floor is the median of its scores over the run (a mite is still in most
    recordings), and a score below it counts as none. (mites,)"""
    values = np.where(labelled, values, np.nan)
    return np.nanmean(np.clip(values - np.nanmedian(values, axis=1, keepdims=True), 0, None), axis=1)


def per_mite(run, table, called=None):
    """Ways to say how much each mite moved over the run, each {name:
    (mites,)}: "mean_score", its mean score, and "above_floor", see
    above_floor(); with `called` ({name: calls}) also "moving", the recordings
    called moving, and "death", the recording it dies at."""
    out = {"mean_score": {name: np.nanmean(np.where(run.labelled, values, np.nan), axis=1) for name, values in table.items()},
           "above_floor": {name: above_floor(values, run.labelled) for name, values in table.items()}}
    if called is not None:
        out["moving"] = {name: (moving & run.labelled).sum(axis=1) for name, moving in called.items()}
        out["death"] = {name: deaths(run, moving) for name, moving in called.items()}
    return out


def main():
    run = adf.load_run()
    table = scores(run)
    in_use = get_default_config().mite.metric
    for pair in same(table):
        dropped = pair[0] if pair[1] == in_use else pair[1]
        print(f"{pair[0]} and {pair[1]} are the same numbers with these parameters: {dropped} is left out")
        table.pop(dropped, None)
    names = list(table)
    is_still = run.labelled & ~run.moving
    best = best_thresholds(table, run)
    called = calls(table, matched_thresholds(table, run))
    agreement = pairwise(called, kappa, run.labelled)
    total = per_mite(run, table, called)
    truth = run.moving.sum(axis=1)
    print(f"{run.name}: {len(run.mites)} mites, {run.moving.shape[1]} recordings, {len(table)} scores; "
          f"each calls as many recordings moving as the labels ({int(run.moving.sum())})")
    print(f"  {'score':<28}{'AUC':>7}{'best death error':>18}{'kappa, labels':>15}{'kappa, others':>15}{'order of the mites':>20}")
    for index, name in enumerate(names):
        print(f"  {name:<28}{adf.auc(table[name][run.moving], table[name][is_still]):>7.3f}{best[name][1]:>18.2f}"
              f"{kappa(called[name][run.labelled], run.moving[run.labelled]):>15.2f}{np.delete(agreement[index], index).mean():>15.2f}"
              f"{rank_correlation(total['above_floor'][name], truth):>20.2f}")
    n_votes = votes(called)[run.labelled]
    print(f"  recordings some score calls moving: {(n_votes > 0).sum()}; all of them do: {(n_votes == len(table)).sum()}")
    print("  making about the same calls: " + "; ".join(", ".join(group) for group in agreeing(agreement, names)))
    print(f"  the mites in one order by all the scores (Kendall's W): by the mean score {concordance(total['mean_score']):.2f}, "
          f"by the mean score above each mite's floor {concordance(total['above_floor']):.2f}")


if __name__ == "__main__":
    main()
