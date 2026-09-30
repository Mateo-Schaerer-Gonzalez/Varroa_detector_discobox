"""How well each movement score holds up when the plate shakes, with and without
plate stabilization (mite.stabilize_plate in config.yaml).

The ground truth in calibration_data/ was recorded on a still plate. Every
labelled (mite, recording) is scored as recorded, and the threshold is chosen
there (Youden's J), as a calibration would. The plate is then shaken by
--shakes pixels (see tune_optical_flow.shaken()) and scored again at that same
threshold: that is what happens when a threshold calibrated on a still plate
meets a shaking one. A score that is robust keeps its accuracy; one that isn't
calls still mites moving.

    python scripts/shake_robustness.py
    python scripts/shake_robustness.py --shakes 0.25 0.5 1 --metrics topN_variability optical_flow

The table is also written to calibration_data/reports/shake_robustness_<time>.csv.
"""
import argparse
import csv
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import pipeline
from classes import calibration
from classes.analyzer import Analyzer
from classes.app_config import get_default_config
from tune_optical_flow import load_observations

_ROIS = None


def _init_worker(rois):
    global _ROIS
    _ROIS = rois


def _score(job):
    metric, params = job
    cuts = _ROIS[Analyzer.roi_padding(metric, params)]
    return np.array([Analyzer._motion_score(roi, metric, params) for roi in cuts])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shakes", type=float, nargs="+", default=[0.5, 1.0, 2.0],
                        help="plate shake, pixels (std) per frame")
    parser.add_argument("--metrics", nargs="+", default=Analyzer.metric_names(), choices=Analyzer.metric_names())
    parser.add_argument("--jobs", type=int, default=os.cpu_count())
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    config = get_default_config().mite
    params = {m: config.params_for(m) for m in args.metrics}
    pads = sorted({Analyzer.roi_padding(m, params[m]) for m in args.metrics})
    shakes = [0.0, *args.shakes]

    scores, moving = {}, None
    for stabilize in (0, 1):
        for shake in shakes:
            print(f"Scoring: shake {shake} px, stabilize_plate {stabilize}")
            rois, moving, _mites, _recordings = load_observations(pads, shake, args.seed, bool(stabilize))
            with ProcessPoolExecutor(args.jobs, initializer=_init_worker, initargs=(rois,)) as pool:
                jobs = [(m, params[m]) for m in args.metrics]
                for metric, result in zip(args.metrics, pool.map(_score, jobs)):
                    scores[metric, stabilize, shake] = result
    if not calibration.has_both_classes(moving):
        sys.exit("Need both moving and still labels in calibration_data/.")

    rows = []
    for metric in args.metrics:
        for stabilize in (0, 1):
            threshold = calibration.best_threshold(scores[metric, stabilize, 0.0], moving)
            for shake in shakes:
                s = scores[metric, stabilize, shake]
                counts = calibration.confusion(s, moving, threshold)
                rows.append({"metric": metric, "stabilize_plate": stabilize, "shake": shake,
                             "threshold": threshold, "auc": calibration.auc(s, moving),
                             "accuracy": counts["accuracy"],
                             "still_called_moving": counts["still_called_moving"],
                             "moving_called_still": counts["moving_called_still"]})

    print(f"\n{len(moving)} observations ({moving.sum()} moving). Accuracy at the threshold chosen "
          "without shake (AUC in brackets):")
    print(f"{'metric':<28}{'stabilized':<11}" + "".join(f"{f'{s:g} px':>17}" for s in shakes))
    for metric in args.metrics:
        for stabilize in (0, 1):
            cells = [r for r in rows if r["metric"] == metric and r["stabilize_plate"] == stabilize]
            print(f"{metric:<28}{'yes' if stabilize else 'no':<11}"
                  + "".join(f"{r['accuracy']:>8.3f} ({r['auc']:.3f})" for r in cells))

    out = pipeline.CALIBRATION_REPORTS / f"shake_robustness_{datetime.now():%Y-%m-%d_%H-%M-%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nTable: {out}")


if __name__ == "__main__":
    main()
