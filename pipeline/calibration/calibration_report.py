"""The calibration report: the saved mites scored with a metric and compared
with the movement the user saw, pooled over datasets.
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from classes.results import reporting
from classes.ground_truth import calibration
from classes.scoring.analyzer import Analyzer
from classes.scoring.benchmark import Benchmark
from classes.app_config import get_default_config
from classes.results.error_map import ErrorMap
from classes.scoring.outline_change import OutlineChange
from classes.scoring.score_normalizer import ScoreNormalizer
from pipeline import output_files, paths
from pipeline.calibration import dataset_library, movement_score, poke_test, report_rows, score_cache


def evaluate_calibration(out_dir, datasets, metric=None, params=None, recordings_root=paths.RECORDINGS_ROOT,
                         stabilize=None, benchmark=False, normalize_brightness=None, normalize_floor=None,
                         between=False):
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
    both moving and still labels, the precision-recall curve with its average
    precision ("precision_recall", "average_precision") and the suggested threshold with
    its confusion counts: the one with the largest F0.5 of the calls moving,
    recording by recording (calibration.best_f05_threshold()). The close calls
    it gets wrong are the ones the result pages ask to check by eye
    (classes/results/review_band.py). Also the fraction of mites moving per
    recording and the Kaplan-Meier survival curves (of the mites seen moving at
    least once) by the labels and by the detector; how far the detector puts
    each mite's death from where the labels put it, in recordings, at each
    threshold ("death_error", see calibration.death_errors()), reported but not
    chosen on; every observation with its outcome; and, where a poke test was entered, the
    survival of the poked mites by the pokes and by the detector at the
    threshold in use ("poke", see poke_test.poke_survival()).
    Everything is also written to calibration.xlsx in `out_dir`, a moment later:
    the workbook takes longer to write than the report to work out, so the page
    has the report first (results_file() waits for the workbook).

    With `benchmark`, the same observations are also called by the Discobox's
    original software (classes/scoring/benchmark.py): its confusion counts, with
    precision, recall and F1 as for the detector, come as "benchmark", and its
    survival curve and its death errors join the others. Slow the first time a dataset meets it.

    With `between`, each mite's outline is also compared from each recording to
    the next (classes/scoring/outline_change.py): a change that opening the box to poke
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
    how = _how_to_score(metric, params, stabilize, normalize_brightness, normalize_floor)
    times = report_rows.pooled_times(loaded)
    pooled = _pooled(ids, loaded, how, benchmark, between)
    if not pooled.rows:
        raise ValueError("Mark at least one mite moving or still first.")

    current = how.in_use["threshold"]
    scores = np.array([row["score"] for row in pooled.rows])
    is_moving = np.array([row["movement"] == calibration.MOVING for row in pooled.rows], dtype=bool)
    suggested = calibration.best_f05_threshold(scores, is_moving) if calibration.has_both_classes(is_moving) else None
    _add_outcomes(pooled.rows, current, suggested)
    result = _report(how, pooled, times, suggested, benchmark, between)
    # each outcome as a fraction of its row, for the confusion matrices
    result["rates"] = {key: None if result[key] is None else calibration.outcome_rates(result[key])
                       for key in ("current", "best")}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    result["excel"] = reporting.CALIBRATION_EXCEL_NAME
    output_files.files_later.later(paths.folder_key(out_dir),
                                   lambda: reporting.write_calibration_excel(result, out_dir))
    return result


def _how_to_score(metric, params, stabilize, normalize_brightness, normalize_floor):
    """How a report scores the mites: the metric and all its parameters
    (movement_score.resolve_metric()), plate stabilization and the
    normalisations (a ScoreNormalizer), each config.yaml's unless given; with
    config.yaml's movement score (`in_use`, movement_score.in_use()) and whether
    its threshold fits these scores (`fits`): only when they are all its own."""
    metric, params = movement_score.resolve_metric(metric, params)
    in_use = movement_score.in_use(get_default_config().mite)
    stabilize = in_use["stabilize_plate"] if stabilize is None else bool(stabilize)
    normalizer = ScoreNormalizer(
        floor=in_use["normalize_floor"] if normalize_floor is None else normalize_floor,
        brightness=in_use["normalize_brightness"] if normalize_brightness is None else normalize_brightness)
    fits = (metric == in_use["metric"] and params == in_use["params"]
            and stabilize == in_use["stabilize_plate"]
            and normalizer.brightness == in_use["normalize_brightness"]
            and normalizer.floor == in_use["normalize_floor"])
    return SimpleNamespace(metric=metric, params=params, stabilize=stabilize, normalizer=normalizer,
                           in_use=in_use, fits=fits)


def _pooled(ids, loaded, how, benchmark, between):
    """The datasets `loaded` (their ids `ids`) scored as `how` says, and what
    the report pools of them: `rows`, one per labelled mite-recording
    (report_rows.observations()); `n_rejected` and `n_unlabelled`; `summaries`,
    one per dataset (_dataset_summary()); `poked`, the poked mites
    (poke_test.poked_mites()); and with `between`, `outline_rows` for the
    figure of the outline changes. With `benchmark`, the benchmark calls each
    mite-recording too."""
    current = how.in_use["threshold"]
    pooled = SimpleNamespace(rows=[], n_rejected=0, n_unlabelled=0, summaries=[], poked=[], outline_rows=[])
    for key, dataset in zip(ids, loaded):
        scores = score_cache.dataset_scores(key, dataset, how.metric, how.params, how.stabilize)
        scores = score_cache.normalised_scores(key, dataset, scores, how.normalizer,
                                               Analyzer.roi_padding(how.metric, how.params), how.stabilize)
        called = score_cache.dataset_benchmark(key, dataset) if benchmark else None
        outline = report_rows.between_recordings(key, dataset, how.stabilize) if between else None
        here, rejected, unlabelled = report_rows.observations(dataset, key, scores, called, outline)
        last = len(dataset["times"]) - 1
        circles = (score_cache.dataset_circles(key, dataset, last)
                   if benchmark and last < len(dataset["recordings"]) else None)
        pooled.rows += here
        pooled.poked += poke_test.poked_mites(dataset, scores, current, outline and outline["calls"])
        if outline:
            pooled.outline_rows += report_rows.outline_rows(dataset, key, outline)
        pooled.n_rejected += rejected
        pooled.n_unlabelled += unlabelled
        pooled.summaries.append(_dataset_summary(key, dataset, here, scores, current, called, circles))
    return pooled


def _dataset_summary(key, dataset, rows, scores, threshold, benchmark, circles):
    """What the report shows of one dataset: its observations `rows`, its plate,
    and its last recording with every mite's call at `threshold` and the
    `benchmark`'s (report_rows.last_recording())."""
    return {
        "id": key,
        "name": dataset["name"],
        "data_dir": dataset["data_dir"],
        "n_observations": len(rows),
        "n_mites": report_rows.n_mites(rows),
        # enough to draw the dataset's plate on its own preview
        "image": dataset["image"],
        "zones": [{k: zone[k] for k in ("id", "x1", "y1", "x2", "y2")} for zone in dataset["zones"]],
        # its last recording, every mite with the call at the threshold in use and the benchmark's
        "last_recording": report_rows.last_recording(dataset, scores, threshold, benchmark, circles),
    }


def _add_outcomes(rows, current, suggested):
    """Each row's outcome (calibration.outcome()) at the `current` threshold and,
    with one, the `suggested` threshold."""
    for row in rows:
        is_moving = row["movement"] == calibration.MOVING
        row["outcome"] = calibration.outcome(is_moving, row["score"], current)
        if suggested is not None:
            row["outcome_suggested"] = calibration.outcome(is_moving, row["score"], suggested)


def _report(how, pooled, times, suggested, benchmark, between):
    """The report of the observations `pooled`, scored as `how` says, against the
    threshold in use and the `suggested` one (None without both labels)."""
    rows = pooled.rows
    current = how.in_use["threshold"]
    scores = np.array([row["score"] for row in rows])
    is_moving = np.array([row["movement"] == calibration.MOVING for row in rows], dtype=bool)
    both = calibration.has_both_classes(is_moving)
    thresholds = {"current": current}
    if suggested is not None:
        thresholds["suggested"] = suggested
    # who else calls the observations: the benchmark, and the outline change between recordings
    calls = {**({"benchmark": "benchmark_call"} if benchmark else {}), **({"outline": "outline_call"} if between else {})}

    def over_time(subset):
        curves = calibration.moving_over_time(subset, len(times), thresholds)
        return {key: values if key == "n" else report_rows.rounded(values) for key, values in curves.items()}

    def survival(subset):
        curves = calibration.survival_curves(subset, times, thresholds, calls)
        return {name: {key: report_rows.rounded(value, 2) if isinstance(value, list) else value
                       for key, value in curve.items()}
                for name, curve in curves.items()}

    return {
        "metric": how.metric,
        "metric_params": how.params,
        "stabilize_plate": how.stabilize,
        "normalize_brightness": how.normalizer.brightness,
        "normalize_floor": how.normalizer.floor,
        "in_use": how.in_use,
        "threshold_fits": how.fits,
        "datasets": pooled.summaries,
        "times": times,
        "threshold": current,
        "suggested_threshold": None if suggested is None else round(suggested, 3),
        "average_precision": calibration.average_precision(scores, is_moving) if both else None,
        "precision_recall": _precision_recall(scores, is_moving) if both else None,
        "n_mites": report_rows.n_mites(rows),
        "n_moving": int(is_moving.sum()),
        "n_still": int((~is_moving).sum()),
        "n_not_a_mite": pooled.n_rejected,
        "n_unlabelled": pooled.n_unlabelled,
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
        # how far the detector, and the benchmark, put each mite's death from the labels', in recordings:
        # reported, not what the suggestion is chosen on
        "death_error": {name: {key: value if value is None or isinstance(value, int) else round(value, 3)
                               for key, value in errors.items()}
                        for name, errors in calibration.death_errors(rows, thresholds, calls).items()},
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
        # the survival of the mites poked by hand, by the pokes and by the detector at the
        # threshold in use; None without a poke test
        "poke": poke_test.poke_survival(pooled.poked, times),
        # every mite's outline change from each recording to the next, by its death; None without `between`
        "between_recordings": OutlineChange().raster(pooled.outline_rows) if between else None,
    }


def _precision_recall(scores, is_moving):
    """The precision-recall curve of `scores` against the labels, for the report,
    with the precision of calling everything moving ("chance": the share of
    moving labels)."""
    recall, precision, f05, thresholds = calibration.precision_recall_curve(scores, is_moving)
    return {
        "recall": report_rows.rounded(recall),
        "precision": report_rows.rounded(precision),
        "f05": report_rows.rounded(f05),
        # the F-score's beta, for the figure's curve of equal F0.5
        "beta": calibration.F_BETA,
        "thresholds": report_rows.rounded(thresholds, 3),
        "chance": round(float(is_moving.mean()), 4),
    }


