"""Tune the threshold against the saved ground truth by the time each mite died,
with and without plate stabilization.

A survival curve is made of the mites' death times, so a threshold is judged by
how far the death times its calls give are from those the labels give: the mean
distance over the mites, in minutes (classes/mite_threshold.py). Three kinds of
threshold are compared:

    single   one threshold for every mite
    own      the moving median of the mite's own scores plus an offset
    scaled   the same, plus a number of median absolute deviations (MADs) of
             those scores, so a noisier mite gets a higher threshold

Every saved dataset in calibration_data/ is scored with config.yaml's metric, as
a calibration report scores it, once with the plate stabilized and once without
(the first time, the recordings are decoded; after that the scores are cached).
For each, the best window, scale and offset are chosen on all the labels, and,
to see what that is worth on mites the choice never saw, on half of the mites
and judged on the other half, over --repeats random halves.

    python scripts/tune_mite_threshold.py
    python scripts/tune_mite_threshold.py --repeats 100
    python scripts/tune_mite_threshold.py --stabilize 0      # only without stabilization

A threshold that rises with the mite's own noise may make stabilization
unnecessary: compare the held-out errors of the two tables.

Every window and scale tried is written to
calibration_data/reports/mite_threshold_<time>.csv.
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline
from classes.app_config import get_default_config
from classes.mite_threshold import MiteThreshold

KINDS = {
    "single": "one threshold for every mite",
    "own": "the mite's median + offset",
    "scaled": "median + MADs + offset",
}


def name(threshold):
    if not threshold.window:
        return f"threshold {threshold.offset:.4g}"
    scale = f" + {threshold.scale:g} MAD" if threshold.scale else ""
    return (f"median of {threshold.window} {'centred' if threshold.centred else 'trailing'}"
            f"{scale} + {threshold.offset:.4g}")


def line(label, search, threshold):
    error = search.death_error(search.calls(threshold))
    confusion = search.confusion(threshold)
    return (f"  {label:<30}{error['mae']:>8.2f}{error['bias']:>+8.2f}{error['n_exact']:>5}/{error['n_mites']:<5}"
            f"{confusion['accuracy']:>7.3f}{confusion['still_called_moving']:>5}{confusion['moving_called_still']:>5}   "
            f"{name(threshold)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stabilize", type=int, choices=[0, 1], default=None,
                        help="only with (1) or without (0) plate stabilization (default: both)")
    parser.add_argument("--repeats", type=int, default=50, help="random halves to choose and judge on")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    config = get_default_config().mite
    in_use = MiteThreshold.from_config(config)
    print(f"{config.metric} {config.params_for(config.metric)}; in config.yaml: {name(in_use)}, "
          f"plate {'stabilized' if config.stabilize_plate else 'not stabilized'}")

    rows, held_out = [], {}
    for stabilize in ([True, False] if args.stabilize is None else [bool(args.stabilize)]):
        print(f"\nScoring {'with' if stabilize else 'without'} plate stabilization...")
        search = pipeline.threshold_search(stabilize=stabilize)
        print(f"{len(search.is_moving)} observations ({search.is_moving.sum()} moving, {(~search.is_moving).sum()} still) "
              f"of {len(search.by_mite)} mites over {len(search.times)} recordings")

        print("Chosen and judged on all the labels:")
        print(f"  {'':<30}{'MAE min':>8}{'bias':>8}{'exact':>11}{'acc.':>7}{'FP':>5}{'FN':>5}")
        if stabilize == config.stabilize_plate:
            print(line("in config.yaml", search, in_use))
        print(line(KINDS["single"], search, search.fit(0, True)))
        print(line(KINDS["own"], search, search.best(scaled=False)))
        print(line("the best of own and scaled", search, search.best()))

        held = search.held_out(args.repeats, args.seed)
        held_out[stabilize] = held
        if held:
            print(f"Chosen on half of the mites, judged on the other half (MAE in minutes, mean of {held['repeats']} halves):")
            for kind, label in KINDS.items():
                print(f"  {label:<30}{held[kind]:>8.2f}")
        rows += [{"stabilize_plate": int(stabilize), **row} for row in search.table()]

    if len(held_out) == 2 and all(held_out.values()):
        print("\nHeld-out MAE in minutes, with and without plate stabilization:")
        print(f"  {'':<30}{'with':>8}{'without':>9}")
        for kind, label in KINDS.items():
            print(f"  {label:<30}{held_out[True][kind]:>8.2f}{held_out[False][kind]:>9.2f}")

    out = pipeline.CALIBRATION_REPORTS / f"mite_threshold_{datetime.now():%Y-%m-%d_%H-%M-%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nEvery window and scale: {out}")


if __name__ == "__main__":
    main()
