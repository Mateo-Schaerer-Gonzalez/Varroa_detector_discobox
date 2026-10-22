"""The calibration report: the saved mites scored with a metric and compared
with the movement the user saw, pooled over datasets.
"""

from pathlib import Path

import numpy as np

import reporting
from classes import calibration
from classes import death_calibration
from classes.analyzer import Analyzer
from classes.benchmark import Benchmark
from classes import app_config
from classes.app_config import get_default_config
from classes.error_map import ErrorMap
from classes.outline_change import OutlineChange
from classes.score_normalizer import ScoreNormalizer
from pipeline import output_files, paths
from pipeline.calibration import dataset_library, movement_score, poke_test, report_rows, score_cache


# Checks by eye per mite the band suggested with a threshold may ask for, unless the report is asked for another number.
REVIEW_CHECKS = 0.5
# Edges tried on each side of the threshold for that band.
REVIEW_BAND_STEPS = 24


def _suggested_band(runs, threshold, checks_per_mite):
    """The band to check by eye that goes with a suggested threshold, for a
    calibration report: the one with the smallest death error among those asking
    for at most `checks_per_mite` checks per mite, the labels standing in for
    the eye (death_calibration.best_band()), with what it leaves:

        {checks_allowed, low, high, mae, checks_per_mite, exact,
         frontier: what the checks buy (death_calibration.checks_frontier()), up
                   to four times the checks allowed}

    low == high when no band does better than the threshold alone."""
    threshold = round(threshold, 3)
    grid = death_calibration.band_grid(runs, threshold, REVIEW_BAND_STEPS)
    low, high = death_calibration.best_band(runs, threshold, checks_per_mite, grid=grid)
    low, high = min(round(low, 3), threshold), max(round(high, 3), threshold)
    shown = max(4 * checks_per_mite, 2.0)

    def rounded(band):
        return {"low": round(band["low"], 3), "high": round(band["high"], 3), "mae": round(band["mae"], 3),
                "checks_per_mite": round(band["checks_per_mite"], 3), "exact": round(band["exact"], 4)}

    return {"checks_allowed": checks_per_mite,
            **rounded({"low": low, "high": high, **death_calibration.band_outcome(runs, low, high)}),
            "frontier": [rounded(band) for band in death_calibration.checks_frontier(grid)
                         if band["checks_per_mite"] <= shown]}


def evaluate_calibration(out_dir, datasets, metric=None, params=None, recordings_root=paths.RECORDINGS_ROOT,
                         stabilize=None, benchmark=False, normalize_brightness=None, normalize_floor=None,
                         checks_per_mite=None, between=False):
    """Score the saved mites with a metric and compare the scores with the
    movement the user saw, pooled over the saved datasets whose ids are in
    `datasets`.

    The metric is the one in config.yaml unless `metric` is given, with its
    parameters overridden by `params` (e.g. {"n": 20} for topN_variability), so
    other movement scores can be tried without editing the file; likewise
    `stabilize` (following a shaking plate, see PlateStabilizer) is config.yaml's
    mite.stabilize_plate unless given, and `normalize_brightness` and
    `normalize_floor` (the scores of each dataset put on one scale for every
    mite, as the analysis of a folder does, see ScoreNormalizer) config.yaml's
    too. The threshold "in use" is always config.yaml's; it only fits these
    scores when the metric, parameters, stabilization and normalisations are
    config.yaml's too, which `threshold_fits` says.

    Each (mite, recording) labelled moving or still is one observation; the
    detector calls it moving when that recording's score reaches the threshold.
    Mites marked "not a mite" are left out entirely. Scoring decodes a dataset's
    recordings the first time it meets a version of the metric; later evaluations
    reuse those scores. Recordings are pooled by their order (first, second, ...)
    for the fraction moving over time.

    Returns the confusion counts at the threshold in use and, when there are
    both moving and still labels, the ROC curve and the suggested threshold with
    its confusion counts: the one that puts the mites' deaths closest to where
    the labels put them (death_calibration.best_threshold()), as in a long run
    the one that best tells moving from still recording by recording puts many
    deaths late. Also the fraction of mites moving per recording and the
    Kaplan-Meier survival curves (of the mites seen moving at least once) by the
    labels and by the detector; how far the detector puts each mite's death from
    where the labels put it, in recordings ("death_error", see
    calibration.death_errors()) and, with a suggested threshold, that error by
    threshold around the two ("death_curve", see death_calibration.death_curve())
    and the band around it to check by eye, for `checks_per_mite` checks per
    mite at most (REVIEW_CHECKS unless given; "review_band", see
    _suggested_band(); its shape is kept in config.yaml at once when the report
    scores as the analyses do, see _keep_band_shape()); every observation with
    its outcome; and, where a poke
    test was entered, the survival of the poked mites by the pokes and by the
    detector at the threshold in use ("poke", see poke_test.poke_survival()).
    Everything is also written to calibration.xlsx in `out_dir`, a moment later:
    the workbook takes longer to write than the report to work out, so the page
    has the report first (results_file() waits for the workbook).

    With `benchmark`, the same observations are also called by the Discobox's
    original software (classes/benchmark.py): its confusion counts, with
    precision, recall and F1 as for the detector, come as "benchmark", and its
    survival curve and its death errors join the others. Slow the first time a dataset meets it.

    With `between`, each mite's outline is also compared from each recording to
    the next (classes/outline_change.py): a change that opening the box to poke
    the mites does not fake. Each observation then has its "outline_change" and
    "outline_call", the outline's calls join the others' survival curves and
    death errors (as "outline"), and the poked mites' ("others" of "poke"); and
    "between_recordings" holds every mite's changes for the figure of them all
    (OutlineChange.raster()). Slow the first time a dataset meets it, as every
    frame is decoded.
    """
    ids = list(dict.fromkeys(datasets))
    if not ids:
        raise ValueError("Choose at least one dataset.")
    loaded = [dataset_library.read_dataset(key, recordings_root) for key in ids]
    metric, params = movement_score.resolve_metric(metric, params)
    in_use = movement_score.in_use(get_default_config().mite)
    checks_per_mite = REVIEW_CHECKS if checks_per_mite is None else float(checks_per_mite)
    if not 0 <= checks_per_mite <= 100:
        raise ValueError("The checks allowed per mite must be between 0 and 100.")
    stabilize = in_use["stabilize_plate"] if stabilize is None else bool(stabilize)
    normalizer = ScoreNormalizer(
        floor=in_use["normalize_floor"] if normalize_floor is None else normalize_floor,
        brightness=in_use["normalize_brightness"] if normalize_brightness is None else normalize_brightness)
    current = in_use["threshold"]
    times = report_rows.pooled_times(loaded)
    n_recordings = len(times)

    rows, n_rejected, n_unlabelled, summaries, poked, outline_rows = [], 0, 0, [], [], []
    for key, dataset in zip(ids, loaded):
        scores = score_cache.dataset_scores(key, dataset, metric, params, stabilize)
        scores = score_cache.normalised_scores(key, dataset, scores, normalizer, Analyzer.roi_padding(metric, params),
                                               stabilize)
        called = score_cache.dataset_benchmark(key, dataset) if benchmark else None
        outline = report_rows.between_recordings(key, dataset, stabilize) if between else None
        here, rejected, unlabelled = report_rows.observations(dataset, key, scores, called, outline)
        last = len(dataset["times"]) - 1
        circles = score_cache.dataset_circles(key, dataset, last) if benchmark and last < len(dataset["recordings"]) else None
        rows += here
        poked += poke_test.poked_mites(dataset, scores, current, outline and outline["calls"])
        if outline:
            outline_rows += report_rows.outline_rows(dataset, key, outline)
        n_rejected += rejected
        n_unlabelled += unlabelled
        summaries.append(
            {
                "id": key,
                "name": dataset["name"],
                "data_dir": dataset["data_dir"],
                "n_observations": len(here),
                "n_mites": report_rows.n_mites(here),
                # enough to draw the dataset's plate on its own preview
                "image": dataset["image"],
                "zones": [{k: zone[k] for k in ("id", "x1", "y1", "x2", "y2")} for zone in dataset["zones"]],
                # its last recording, every mite with the call at the threshold in use and the benchmark's
                "last_recording": report_rows.last_recording(dataset, scores, current, called, circles),
            }
        )
    if not rows:
        raise ValueError("Mark at least one mite moving or still first.")

    scores = np.array([row["score"] for row in rows])
    is_moving = np.array([row["movement"] == calibration.MOVING for row in rows], dtype=bool)
    both = calibration.has_both_classes(is_moving)
    runs = death_calibration.runs_of_rows(rows)
    suggested = death_calibration.best_threshold(runs)[0] if both else None

    thresholds = {"current": current}
    if suggested is not None:
        thresholds["suggested"] = suggested
    for row in rows:
        is_moving_row = row["movement"] == calibration.MOVING
        row["outcome"] = calibration.outcome(is_moving_row, row["score"], current)
        if suggested is not None:
            row["outcome_suggested"] = calibration.outcome(is_moving_row, row["score"], suggested)

    def over_time(subset):
        curves = calibration.moving_over_time(subset, n_recordings, thresholds)
        return {key: values if key == "n" else report_rows.rounded(values) for key, values in curves.items()}

    # who else calls the observations: the benchmark, and the outline change between recordings
    calls = {**({"benchmark": "benchmark_call"} if benchmark else {}), **({"outline": "outline_call"} if between else {})}

    def survival(subset):
        curves = calibration.survival_curves(subset, times, thresholds, calls)
        return {name: {key: report_rows.rounded(value, 2) if isinstance(value, list) else value for key, value in curve.items()}
                for name, curve in curves.items()}

    roc = None
    if both:
        fpr, tpr, roc_thresholds = calibration.roc_curve(scores, is_moving)
        roc = {
            "fpr": report_rows.rounded(fpr),
            "tpr": report_rows.rounded(tpr),
            # the first point is at an infinite threshold, which JSON cannot hold
            "thresholds": [None if np.isinf(t) else round(float(t), 3) for t in roc_thresholds],
        }

    result = {
        "metric": metric,
        "metric_params": params,
        "stabilize_plate": stabilize,
        "normalize_brightness": normalizer.brightness,
        "normalize_floor": normalizer.floor,
        "in_use": in_use,
        "threshold_fits": (metric == in_use["metric"] and params == in_use["params"]
                           and stabilize == in_use["stabilize_plate"]
                           and normalizer.brightness == in_use["normalize_brightness"]
                           and normalizer.floor == in_use["normalize_floor"]),
        "datasets": summaries,
        "times": times,
        "threshold": current,
        "suggested_threshold": None if suggested is None else round(suggested, 3),
        "auc": calibration.auc(scores, is_moving) if both else None,
        "roc": roc,
        "n_mites": report_rows.n_mites(rows),
        "n_moving": int(is_moving.sum()),
        "n_still": int((~is_moving).sum()),
        "n_not_a_mite": n_rejected,
        "n_unlabelled": n_unlabelled,
        "current": calibration.confusion(scores, is_moving, current),
        "best": calibration.confusion(scores, is_moving, suggested) if suggested is not None else None,
        # the same observations as called by the Discobox's original software
        "benchmark": {
            "name": Benchmark.NAME,
            "threshold": Benchmark.THRESHOLD,
            **calibration.calls_confusion([row["benchmark_call"] == calibration.MOVING for row in rows], is_moving),
        } if benchmark else None,
        "moving_over_time": over_time(rows),
        # the survival curves by the labels and by the detector, see calibration.survival_curves()
        "survival": survival(rows),
        # how far the detector, and the benchmark, put each mite's death from the labels', in recordings
        "death_error": {name: {key: value if value is None or isinstance(value, int) else round(value, 3)
                               for key, value in errors.items()}
                        for name, errors in calibration.death_errors(rows, thresholds, calls).items()},
        # the death error by threshold, around the one in use and the suggested one: what the suggestion is chosen on
        "death_curve": death_calibration.death_curve(runs, [current, suggested]) if suggested is not None else None,
        # the band around the suggested threshold to check by eye, and what the checks buy
        "review_band": _suggested_band(runs, suggested, checks_per_mite) if suggested is not None else None,
        "groups": [
            {
                "group": group,
                "n_mites": report_rows.n_mites([row for row in rows if row["group"] == group]),
                **over_time([row for row in rows if row["group"] == group]),
                "survival": survival([row for row in rows if row["group"] == group]),
            }
            for group in sorted({row["group"] for row in rows})
        ],
        "observations": rows,
        "zones": report_rows.calibration_by_zone(rows),
        # where the calls at the threshold in use go wrong, for the test report's map
        "error_map": ErrorMap(rows).describe(),
        # the survival of the mites poked by hand, by the pokes and by the detector at the threshold in use; None without a poke test
        "poke": poke_test.poke_survival(poked, times),
        # every mite's outline change from each recording to the next, by its death; None without `between`
        "between_recordings": OutlineChange().raster(outline_rows) if between else None,
    }
    if result["threshold_fits"] and result["review_band"] is not None:
        kept = _keep_band_shape(result["review_band"], suggested, current)
        if kept is not None:
            in_use["review_band"] = kept
    # each outcome as a fraction of its row, for the confusion matrices and the ROC curve
    result["rates"] = {key: None if result[key] is None else calibration.outcome_rates(result[key]) for key in ("current", "best")}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    result["excel"] = reporting.CALIBRATION_EXCEL_NAME
    output_files.files_later.later(paths.folder_key(out_dir),
                                   lambda: reporting.write_calibration_excel(result, out_dir))
    return result


def _keep_band_shape(band, suggested, threshold):
    """Keep the shape of the band a calibration report suggests (around the
    `suggested` threshold) in config.yaml, moved to hold the `threshold` in use:
    the result pages widen or narrow it to the mites to check
    (classes/review_band.py), so only how far it reaches below the threshold
    against above counts. Nothing when the report suggests no band. Returns
    [low, high] as saved, or None."""
    if not band["high"] > band["low"]:
        return None
    try:
        return app_config.save_review_band(threshold - (suggested - band["low"]), threshold + (band["high"] - suggested))
    except ValueError:  # too narrow to tell apart from the threshold, once rounded
        return None
