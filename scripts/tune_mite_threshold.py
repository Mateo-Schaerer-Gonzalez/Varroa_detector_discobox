"""Tune a threshold of each mite's own against the saved ground truth, and compare
it with the single threshold used now.

A mite's own threshold is the moving median of its scores over the recordings
plus an offset (classes/calibration.moving_median()): a mite under a noisier
light scores higher when still, and its median follows that. The window (in
recordings, centred on the recording or ending at it) and the offset are
searched here.

Every (mite, recording) labelled moving or still in calibration_data/ is scored
with config.yaml's metric, as a calibration would score it. The mites are split
into two halves: window and offset are chosen on half A (best sensitivity +
specificity, as the calibration report chooses a threshold) and judged on half
B, which the choice never saw. The single threshold is tuned and judged the same
way. --repeats does this over that many random halves, to see how much is the
luck of one split.

    python scripts/tune_mite_threshold.py
    python scripts/tune_mite_threshold.py --windows 3 5 9 15 --repeats 100
    python scripts/tune_mite_threshold.py --trailing     # only windows a live run can use

A trailing window looks back only, so it can be used while recording; a centred
one needs the recordings that follow.

The median is only the mite's noise while the mite is still in most of the
window, so the last table counts the wrong calls by how often the mite moved.

The table of every window is written to calibration_data/reports/mite_threshold_<time>.csv.
"""
import argparse
import csv
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import pipeline
from classes import calibration
from classes.analyzer import Analyzer
from classes.app_config import get_default_config
from tune_optical_flow import load_observations, score_all


def baselines(scores, series, window, centred):
    """Per observation, the moving median of its mite's scores. `series` holds
    each mite's observations in recording order."""
    base = np.empty_like(scores)
    for indices in series.values():
        base[indices] = calibration.moving_median(scores[indices], window, centred)
    return base


def youden(result):
    return result["sensitivity"] + result["specificity"] - 1


def fit(above, moving, train):
    """The cut on `above` (a score, or a score minus its mite's median) that is
    best on the training observations, and how good it is there."""
    cut = calibration.best_threshold(above[train], moving[train])
    return cut, youden(calibration.confusion(above[train], moving[train], cut))


def fit_own(scores, bases, moving, train):
    """The (window, centred) and offset best on the training observations."""
    best = None
    for key, base in bases.items():
        offset, j = fit(scores - base, moving, train)
        if best is None or j > best[0] + 1e-12:
            best = (j, key, offset)
    return best[1], best[2]


def name(key):
    window, centred = key
    return f"window {window} {'centred' if centred else 'trailing'}"


def line(label, result, tuned):
    return (f"  {label:<26}{result['accuracy']:>7.3f}{result['sensitivity']:>7.3f}{result['specificity']:>7.3f}"
            f"{result['f1']:>7.3f}{result['still_called_moving']:>5}{result['moving_called_still']:>5}   {tuned}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--windows", type=int, nargs="+", default=None,
                        help="window sizes in recordings (default: 2 up to the longest series, at most 12 of them)")
    parser.add_argument("--trailing", action="store_true", help="only windows ending at the recording")
    parser.add_argument("--repeats", type=int, default=50, help="random halves to repeat the comparison on")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    config = get_default_config().mite
    params = config.params_for(config.metric)
    pad = Analyzer.roi_padding(config.metric, params)

    print("Loading labelled observations...")
    rois, moving, mites, recordings = load_observations([pad])
    if not calibration.has_both_classes(moving):
        sys.exit("Need both moving and still labels in calibration_data/ to tune anything.")
    mites, recordings = np.array(mites), np.array(recordings)
    scores = score_all(rois[pad], config.metric, params)
    del rois
    series = {mite: np.flatnonzero(mites == mite)[np.argsort(recordings[mites == mite])] for mite in sorted(set(mites))}
    longest = max(len(indices) for indices in series.values())
    print(f"{len(moving)} observations ({moving.sum()} moving, {(~moving).sum()} still), {len(series)} mites, "
          f"up to {longest} recordings per mite; {config.metric} {params}")

    windows = args.windows or sorted({int(w) for w in np.linspace(2, max(2, longest), 12).round()})
    bases = {(window, centred): baselines(scores, series, window, centred)
             for window in windows for centred in ((False,) if args.trailing else (True, False))}

    def halves(seed):
        """True for the observations of half A. Split by mite, so one mite's
        recordings never sit on both sides."""
        keys = list(series)
        random.Random(seed).shuffle(keys)
        half_a = set(keys[::2])
        return np.array([mite in half_a for mite in mites])

    in_a = halves(args.seed)
    judge = ~in_a
    print(f"\nChosen on half A ({in_a.sum()} observations), judged on half B ({judge.sum()}):")
    print(f"  {'':<26}{'acc.':>7}{'sens.':>7}{'spec.':>7}{'F1':>7}{'FP':>5}{'FN':>5}")
    print(line("single, as configured", calibration.confusion(scores[judge], moving[judge], config.motion_threshold),
               f"threshold {config.motion_threshold:.4g}"))
    threshold, _j = fit(scores, moving, in_a)
    single = calibration.confusion(scores[judge], moving[judge], threshold)
    print(line("single, tuned", single, f"threshold {threshold:.4g}"))
    key, offset = fit_own(scores, bases, moving, in_a)
    own_called = (scores - bases[key]) >= offset
    own = calibration.confusion((scores - bases[key])[judge], moving[judge], offset)
    print(line("mite's own, best window", own, f"{name(key)}, offset {offset:.4g}"))

    rows = []
    for key, base in bases.items():
        offset, _j = fit(scores - base, moving, in_a)
        result = calibration.confusion((scores - base)[judge], moving[judge], offset)
        print(line("  " + name(key), result, f"offset {offset:.4g}"))
        rows.append({"window": key[0], "centred": key[1], "offset": offset,
                     **{k: result[k] for k in ("accuracy", "sensitivity", "specificity", "f1",
                                               "still_called_moving", "moving_called_still")}})

    if args.repeats:
        single_acc, own_acc, chosen = [], [], Counter()
        for seed in range(args.seed + 1, args.seed + 1 + args.repeats):
            train = halves(seed)
            threshold, _j = fit(scores, moving, train)
            single_acc.append(calibration.confusion(scores[~train], moving[~train], threshold)["accuracy"])
            key, offset = fit_own(scores, bases, moving, train)
            own_acc.append(calibration.confusion((scores - bases[key])[~train], moving[~train], offset)["accuracy"])
            chosen[name(key)] += 1
        single_acc, own_acc = np.array(single_acc), np.array(own_acc)
        print(f"\nOver {args.repeats} random halves, accuracy on the half not chosen on:")
        print(f"  single threshold   {single_acc.mean():.3f} (sd {single_acc.std():.3f})")
        print(f"  mite's own         {own_acc.mean():.3f} (sd {own_acc.std():.3f}); "
              f"better in {(own_acc > single_acc).sum()}, equal in {(own_acc == single_acc).sum()}, "
              f"worse in {(own_acc < single_acc).sum()}")
        print("  windows chosen: " + ", ".join(f"{label} ({count})" for label, count in chosen.most_common(4)))

    print("\nWrong calls of the mite's own threshold on half B, by the share of its recordings the mite moved in:")
    edges = [0, 0.25, 0.5, 0.75, 1.0]
    wrong, total = Counter(), Counter()
    for indices in series.values():
        if in_a[indices[0]]:
            continue
        share = moving[indices].mean()
        group = "never" if share == 0 else next(f"up to {int(e * 100)}%" for e in edges[1:] if share <= e)
        total[group] += len(indices)
        wrong[group] += int((own_called[indices] != moving[indices]).sum())
    for group in ["never", *(f"up to {int(e * 100)}%" for e in edges[1:])]:
        if total[group]:
            print(f"  {group:<12}{wrong[group]:>5} of {total[group]}")

    out = pipeline.CALIBRATION_REPORTS / f"mite_threshold_{datetime.now():%Y-%m-%d_%H-%M-%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nEvery window: {out}")


if __name__ == "__main__":
    main()
