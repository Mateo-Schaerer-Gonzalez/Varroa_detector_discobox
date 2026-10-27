"""This app against the Discobox's original analysis software (Abilium's
varroa-discobox, src/processing.py; classes/scoring/benchmark.py), on every
mite-recording labelled moving or still by eye: README.md's "How well it works".

The app's calls are those of its own analysis of each session
(scoring.detect_and_score()) at the default threshold, which was set on the
poke run (poke_test_oct), so the poke run is not among the datasets compared.
The original is asked what the app is asked, did this mite move in this
recording: it says moving when a spot of its mask lies on the mite's box. It
runs on the mite's box and Benchmark.MARGIN px round it, which gives the calls
of the whole frame (see Benchmark).

A recording's plate shake is the median over its mites of how far each one's
patch moved within it, as the app measures it (Mite.activity "shake").

    python scripts/benchmark_original.py
    python scripts/benchmark_original.py --root <folder holding the datasets>

Writes docs/images/benchmark_bars.png and benchmark_shake.png, and
results/scripts/benchmark_original.csv.gz (one row per labelled mite-recording)
and benchmark_original.json (the numbers README.md quotes). Reads only.
"""
import argparse
import json
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# The defaults everyone has, not this machine's config.yaml (only read).
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pipeline  # noqa: E402
from pipeline import clips, ground_truth, scoring  # noqa: E402
from pipeline.calibration import dataset_library, score_cache  # noqa: E402
from classes.app_config import get_default_config  # noqa: E402
from classes.ground_truth import calibration  # noqa: E402
from classes.scoring.analyzer import NoNoiseWarning  # noqa: E402
from classes.scoring.benchmark import Benchmark  # noqa: E402

IMAGES = ROOT / "docs" / "images"
OUT = pipeline.SCRIPTS_OUTPUT / "benchmark_original"
# The groups compared, each one or more datasets of recordings/ pooled.
GROUPS = {
    "2025 sessions\n1 s, 30 fps": ("sample_data", "ground_truth_60min", "ground_truth_90min"),
    "GT_oct_2\n1 s, 10 fps": ("GT_oct_2",),
    "long run\n10 frames": ("test_run_2026-09-08_Mathis_last_dsRNA",),
}
SHAKE_BINS = np.arange(0, 0.30, 0.05)
APP, ORIGINAL = "#1f8a5b", "#5c6bc0"
plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 130, "font.size": 9, "axes.titlesize": 10,
                     "axes.spines.top": False, "axes.spines.right": False})


def observations(name, root, threshold):
    """One row per labelled (mite, recording) of a dataset: the label, the
    app's score and call, the original's call and the recording's plate shake."""
    dataset = dataset_library.read_dataset(name, root)
    data_dir = Path(dataset["data_dir"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NoNoiseWarning)
        run = scoring.detect_and_score(data_dir, None)
    by_id = {mite.text: mite for mite in run.zone_manager.mites}

    def of_mite(mite, states):
        # one mite's rows; each thread opens its own loader (OpenCV lets go of the GIL)
        if mite["id"] not in by_id:   # left out of the app's analysis (a fly-off): no calls to compare
            print(f"  {name}: mite {mite['id']} is not in the app's analysis, left out")
            return []
        loader = score_cache.open_recordings(data_dir)
        app_mite = by_id[mite["id"]]
        fixed_box = score_cache.mite_boxes([mite])[mite["id"]]
        found = []
        for index, recording in enumerate(dataset["recordings"]):
            state = states[index] if index < len(states) else None
            if state not in (calibration.MOVING, calibration.STILL) or app_mite.motion_scores[index] is None:
                continue
            placed = loader.placements(recording["name"])
            box = placed[loader.number_at(mite["x"], mite["y"])] if placed else None
            box = tuple(int(round(v)) for v in (fixed_box if box is None else box))
            x0, y0, x_end, y_end = clips.bounds([box], Benchmark.MARGIN)
            frames = np.asarray(loader.load_recording_region(recording["name"], x0, y0, x_end, y_end))
            local = (box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0)
            original = Benchmark.calls(list(frames), {mite["id"]: local})[mite["id"]]
            score = app_mite.motion_scores[index]
            found.append(dict(dataset=name, mite_id=mite["id"], recording=index, movement=state,
                              score=score, app=calibration.MOVING if score >= threshold else calibration.STILL,
                              original=calibration.MOVING if original else calibration.STILL))
        return found

    with ThreadPoolExecutor(8) as pool:
        rows = [row for found in pool.map(lambda pair: of_mite(*pair), ground_truth.mite_states(dataset)) for row in found]
    shake = {}
    for index in range(len(dataset["recordings"])):
        values = [m.activity[index]["shake"] for m in by_id.values()
                  if index < len(m.activity) and m.activity[index] and m.activity[index].get("shake") is not None]
        shake[index] = float(np.median(values)) if values else np.nan
    for row in rows:
        row["plate_shake"] = shake[row["recording"]]
    print(f"  {name}: {len(rows)} labelled mite-recordings")
    return rows


def summary(rows, threshold):
    moving = np.array([row["movement"] == calibration.MOVING for row in rows])
    out = {}
    for method in ("app", "original"):
        called = np.array([row[method] == calibration.MOVING for row in rows])
        out[method] = calibration.calls_confusion(called, moving)
    deaths = calibration.death_errors(rows, {}, {"app": "app", "original": "original"})
    for method in ("app", "original"):
        out[method]["death"] = deaths[method]
    out["f05_difference"] = bootstrap_f05(rows)
    return out


def bootstrap_f05(rows, n=2000, seed=0):
    """The app's F0.5 minus the original's, the mites resampled with
    replacement: median and 95 % interval."""
    by_mite = {}
    for row in rows:
        counts = by_mite.setdefault((row["dataset"], row["mite_id"]), np.zeros((2, 3)))
        truth = row["movement"] == calibration.MOVING
        for k, method in enumerate(("app", "original")):
            called = row[method] == calibration.MOVING
            counts[k] += (truth and called, called and not truth, truth and not called)   # tp, fp, fn
    counts = np.array(list(by_mite.values()))
    rng = np.random.default_rng(seed)
    differences = []
    for _ in range(n):
        tp, fp, fn = counts[rng.integers(0, len(counts), len(counts))].sum(axis=0).T
        f = [calibration.f_score(tp[k], fp[k], fn[k]) for k in range(2)]
        differences.append(f[0] - f[1])
    return [round(float(v), 3) for v in np.percentile(differences, [50, 2.5, 97.5])]


def bars(table, threshold):
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.2))
    x = np.arange(len(table))
    for ax, (kind, of) in zip(axes, (("still_called_moving", "n_still"), ("moving_called_still", "n_moving"))):
        for offset, method, colour, label in ((-0.2, "app", APP, f"this app (T = {threshold:g}, set on the poke run)"),
                                              (0.2, "original", ORIGINAL, "Discobox original (fixed 25)")):
            counts = [table[group][method][kind] for group in table]
            share = [100 * c / table[group][method][of] for c, group in zip(counts, table)]
            ax.bar_label(ax.bar(x + offset, share, 0.38, color=colour, label=label), [f"{c:,}" for c in counts], padding=2, fontsize=8)
        ax.set_xticks(x, [f"{group}\n{table[group]['app']['n_moving'] + table[group]['app']['n_still']:,} labelled" for group in table])
        what = "still recordings called moving" if of == "n_still" else "moving recordings called still"
        ax.set(ylabel="%", title=f"{'a' if of == 'n_still' else 'b'}. {what} (% of {of[2:]})")
        ax.margins(y=0.12)
    axes[0].legend(frameon=False)
    fig.text(0.01, -0.03, "Bar labels: number of mite-recordings.", fontsize=8, color="#666")
    fig.savefig(IMAGES / "benchmark_bars.png", bbox_inches="tight")
    plt.close(fig)


def shake_chart(rows, threshold):
    """The long run's still recordings by plate shake: the share each method calls moving."""
    still = pd.DataFrame([row for row in rows if row["movement"] == calibration.STILL])
    still["bin"] = pd.cut(still["plate_shake"], np.append(SHAKE_BINS, np.inf), right=False)
    groups = still.groupby("bin", observed=True)
    labels = [f"{b.left:.2f}–{b.right:.2f} px\n{len(g):,} rec." if np.isfinite(b.right) else f"≥ {b.left:.2f} px\n{len(g):,} rec."
              for b, g in groups]
    shares = {m: [100 * (g[m] == calibration.MOVING).mean() for _b, g in groups] for m in ("app", "original")}
    fig, ax = plt.subplots(figsize=(10, 4.2))
    x = np.arange(len(labels))
    for offset, method, colour, label in ((-0.2, "app", APP, f"this app (T = {threshold:g}), per-mite stabilization"),
                                          (0.2, "original", ORIGINAL, "Discobox original (25)")):
        ax.bar_label(ax.bar(x + offset, shares[method], 0.38, color=colour, label=label), [f"{v:.1f}" for v in shares[method]],
                     padding=2, fontsize=8)
    ax.set_xticks(x, labels)
    ax.set(xlabel="plate shake within the recording (median over the mites)", ylabel="% of still recordings called moving",
           title="Long run: still recordings called moving, by how much the plate shook")
    ax.legend(frameon=False)
    fig.savefig(IMAGES / "benchmark_shake.png", bbox_inches="tight")
    plt.close(fig)
    return {label.replace("\n", " "): {m: round(shares[m][i], 2) for m in shares} for i, label in enumerate(labels)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=pipeline.RECORDINGS_ROOT, help="the folder holding the datasets")
    args = parser.parse_args()
    threshold = get_default_config().mite.threshold_for("outline_variability")
    IMAGES.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows, table = {}, {}
    for group, names in GROUPS.items():
        rows[group] = [row for name in names for row in observations(name, args.root, threshold)]
        table[group] = summary(rows[group], threshold)
    pd.DataFrame([dict(row, group=group.split("\n")[0]) for group, group_rows in rows.items() for row in group_rows]) \
        .to_csv(OUT.with_suffix(".csv.gz"), index=False)
    bars(table, threshold)
    numbers = {"threshold": threshold, "groups": {group.split("\n")[0]: value for group, value in table.items()},
               "long_run_shake": shake_chart(rows["long run\n10 frames"], threshold)}
    OUT.with_suffix(".json").write_text(json.dumps(numbers, indent=1), encoding="utf-8")
    print(json.dumps(numbers, indent=1))


if __name__ == "__main__":
    main()
