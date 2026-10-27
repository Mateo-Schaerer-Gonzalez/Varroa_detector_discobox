"""The figures of README.md (docs/images/), from the 2025 sessions only:
sample_data, ground_truth_60min and ground_truth_90min (4 September 2025, 6
recordings of 1 s at 30 fps each, labelled by eye). The other recordings are
real experiments and stay out of the README.

The steps of the score are those of scripts/visual_walkthrough.py, run on a
moving and a still mite of sample_data. Shake is added to a still mite (the
2025 sessions hardly shake), as tune_optical_flow.shaken() shakes a plate.
The benchmark against the Discobox's original software (classes/scoring/
benchmark.py) uses the differential images notebooks/abilium_benchmark.ipynb
kept in results/scripts/abilium_benchmark_diffs.npz, and the same method on
each mite's surroundings for the shaken plates.

    python scripts/readme_figures.py                     # reads recordings/
    python scripts/readme_figures.py --root <folder holding the 2025 sessions>

Writes docs/images/*.png and results/scripts/readme_figures.json. Reads only.
"""
import argparse
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import visual_walkthrough as vw  # noqa: E402  (sets DISCOBOX_CONFIG to the defaults)

import cv2  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import pipeline  # noqa: E402
from pipeline import scoring  # noqa: E402
from pipeline.calibration import dataset_library, score_cache  # noqa: E402
from classes.app_config import get_default_config  # noqa: E402
from classes.ground_truth import calibration  # noqa: E402
from classes.scoring.analyzer import Analyzer, NoNoiseWarning  # noqa: E402
from classes.scoring.benchmark import Benchmark  # noqa: E402
from classes.scoring.plate_stabilizer import PlateStabilizer  # noqa: E402
import script_data  # noqa: E402
from tune_optical_flow import shaken  # noqa: E402

IMAGES = vw.ROOT / "docs" / "images"
NUMBERS = pipeline.SCRIPTS_OUTPUT / "readme_figures.json"
DATASETS = ("sample_data", "ground_truth_60min", "ground_truth_90min")
EXAMPLE = "sample_data"
SHAKES = (0, 0.05, 0.1, 0.15, 0.2, 0.3)   # px, standard deviation of the plate's offset per frame
APP, ORIGINAL = "#1f8a5b", "#5c6bc0"
GREEN, ORANGE, BLUE, INK = vw.GREEN, vw.ORANGE, vw.BLUE, vw.INK
# Measured on 26 October 2026 on sample_data's whole frames (2064 x 1544, 30 mites), each
# method in its own process on the dev laptop (Intel Core Ultra 7 155H); 90 frames are
# three of its 30-frame recordings joined. Seconds and MB per 90-frame recording.
SPEED = {"all cores\n(as shipped)": (0.53, 69.8), "one core": (0.74, 263)}
MEMORY = {"frames of the recording\n(both hold them)": (287, 287), "extra while analysing": (103, 380)}
BMP_BYTES = 2064 * 1544 + 1078   # one 8-bit grey frame as the Discobox app saves it
numbers = {}


def params():
    return get_default_config().mite.params_for("outline_variability")


def score_of(roi):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NoNoiseWarning)
        return float(Analyzer._motion_score(roi, "outline_variability", params()))


def app_score(frames, box, pad):
    """The app's score of a region: stabilized as an analysis run cuts it."""
    shifts = PlateStabilizer().shifts(frames, [box])[0]
    return score_of(Analyzer.grey(PlateStabilizer.cut(frames, box, pad, shifts)))


def original_calls(frames, box):
    """The original's call on the region: a spot of its mask on the mite's box."""
    mask = Benchmark.mask(Benchmark.differential(list(frames)))
    x1, y1, x2, y2 = box
    return bool(mask[max(0, y1):y2, max(0, x1):x2].any())


# ---------------------------------------------------------------- the labelled 2025 data
def labelled_scores(root):
    """Per dataset: the dataset, its mites' ids, labels and the app's scores of
    every mite in every recording (the app's own analysis of the session)."""
    out = {}
    for name in DATASETS:
        dataset = dataset_library.read_dataset(name, root)
        data_dir = Path(dataset["data_dir"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NoNoiseWarning)
            run = scoring.detect_and_score(data_dir, None)
        by_id = {mite.text: mite for mite in run.zone_manager.mites}
        mites, moving, labelled = script_data.labels_of(dataset)
        ids = [mite["id"] for mite in mites]
        score = np.array([[np.nan if v is None else v for v in by_id[i].motion_scores] for i in ids], float)
        out[name] = dict(dataset=dataset, data_dir=data_dir, mites=mites, ids=ids, moving=moving.astype(bool),
                         labelled=labelled.astype(bool), score=score)
    return out


def pick_examples(data):
    """The moving and the still example of sample_data: the labelled moving
    mite-recording with the highest score, and a labelled still one of the same
    plate with the median score of that plate's still ones."""
    d = data[EXAMPLE]
    use = d["labelled"] & d["moving"]
    i, r = np.unravel_index(np.nanargmax(np.where(use, d["score"], -np.inf)), use.shape)
    moving = (d["ids"][i], int(r))
    plate = moving[0].split(".")[0]
    candidates = [(d["score"][j, s], d["ids"][j], s) for j in range(len(d["ids"])) for s in range(d["score"].shape[1])
                  if d["labelled"][j, s] and not d["moving"][j, s] and d["ids"][j].split(".")[0] == plate]
    candidates.sort()
    _score, mite, recording = candidates[len(candidates) // 2]
    return moving, (mite, int(recording))


# ---------------------------------------------------------------- 3. shake and the stabilizer
def step_shake(data, still, moving):
    d = data[EXAMPLE]
    rows = []
    for key, (mite_id, recording), shake in (("still mite, shaken 0.2 px", still, 0.2), ("moving mite, as recorded", moving, 0)):
        frames, box, pad = vw.frames_of(d["dataset"], d["data_dir"], mite_id, recording)
        if shake:
            frames = shaken(frames, shake, np.random.default_rng(1))
        shifts = PlateStabilizer().shifts(frames, [box])[0]
        fixed = Analyzer.grey(PlateStabilizer.cut(frames, box, pad, np.zeros_like(shifts)))
        roi = Analyzer.grey(PlateStabilizer.cut(frames, box, pad, shifts))
        rows.append((key, mite_id, recording, fixed, roi, shifts))
        numbers[f"shake_example {key}"] = dict(mite=mite_id, recording=recording,
                                              score_not_stabilized=round(score_of(fixed), 4),
                                              score_stabilized=round(score_of(roi), 4))
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.6), layout="constrained")
    for row, (key, mite_id, recording, fixed, roi, shifts) in zip(axes, rows):
        v_fixed, v_stab = fixed.var(axis=0), roi.var(axis=0)
        top = np.percentile(np.concatenate([v_fixed.ravel(), v_stab.ravel()]), 99.5)
        for ax, v, title, s in ((row[0], v_fixed, "not stabilized", score_of(fixed)),
                                (row[1], v_stab, "stabilized (each frame moved back)", score_of(roi))):
            im = ax.imshow(v, cmap="magma", vmin=0, vmax=top)
            ax.set_title(f"{key}: mite {mite_id}, rec. {recording + 1}\n{title}, score {s:.3f}")
            ax.set_xticks([]), ax.set_yticks([])
        fig.colorbar(im, ax=row[1], fraction=0.046, label="variance over the frames (grey levels²)")
        ax = row[2]
        ax.plot(np.hypot(*shifts.T), color=INK)
        ax.set(xlabel="frame", ylabel="shift measured (px)", title=f"the mite's shift, largest {np.hypot(*shifts.T).max():.2f} px")
    fig.savefig(IMAGES / "shake_effect.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- calibration on the 2025 labels
def step_calibration(data, threshold):
    score = np.concatenate([d["score"][d["labelled"]] for d in data.values()])
    moving = np.concatenate([d["moving"][d["labelled"]] for d in data.values()])
    best = calibration.best_f05_threshold(score, moving)
    ap = calibration.average_precision(score, moving)
    recall, precision, f05, thresholds = calibration.precision_recall_curve(score, moving)
    numbers.update(calibration=dict(n=int(len(score)), n_moving=int(moving.sum()), average_precision=round(ap, 4),
                                    best_f05_threshold=round(best, 4), app_threshold=threshold,
                                    at_app=calibration.confusion(score, moving, threshold),
                                    at_best=calibration.confusion(score, moving, best)))
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.6))
    bins = np.logspace(np.log10(max(score.min(), 1e-3)), np.log10(score.max()), 30)
    axes[0].hist(score[~moving], bins=bins, color=ORANGE, alpha=0.8, label=f"labelled still ({(~moving).sum()})")
    axes[0].hist(score[moving], bins=bins, color=GREEN, alpha=0.8, label=f"labelled moving ({moving.sum()})")
    axes[0].axvline(threshold, color=INK, ls="--")
    axes[0].set(xscale="log", xlabel="motion score", ylabel="mite-recordings", title="a. scores of the mite-recordings labelled by eye")
    axes[0].legend(frameon=False)
    axes[1].plot(recall, precision, color=BLUE)
    axes[1].set(xlabel="recall", ylabel="precision", ylim=(0, 1.02), title=f"b. precision-recall, average precision {ap:.3f}")
    axes[2].plot(thresholds, f05, color=BLUE)
    axes[2].axvline(best, color=INK, ls="--")
    axes[2].set(xscale="log", xlabel="threshold T", ylabel="F0.5", title=f"c. F0.5 at every threshold: best at {best:.3f}")
    fig.savefig(IMAGES / "calibration.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- calls by group
def step_calls(data, threshold):
    d = data[EXAMPLE]
    groups = json.loads((d["data_dir"] / "labels.json").read_text(encoding="utf-8"))
    times = np.asarray(d["dataset"]["times"], float)
    order = sorted(range(len(d["ids"])), key=lambda i: (groups.get(d["ids"][i].split(".")[0], ""), d["ids"][i]))
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2), gridspec_kw={"width_ratios": [1.1, 1]})
    ax = axes[0]
    for row, i in enumerate(order):
        for r, value in enumerate(d["score"][i]):
            if not np.isnan(value):
                ax.add_patch(plt.Rectangle((r - 0.45, row - 0.4), 0.9, 0.8, color=GREEN if value >= threshold else ORANGE))
    ax.set(xlim=(-0.6, len(times) - 0.4), ylim=(len(order) - 0.5, -0.5), xlabel="recording (5 min apart)",
           title="a. the app's call for each mite in each recording\n(green moving, orange still)")
    ax.set_xticks(range(len(times)), [str(r + 1) for r in range(len(times))])
    ax.set_yticks(range(len(order)), [f"{d['ids'][i]}  ({groups.get(d['ids'][i].split('.')[0], '?')})" for i in order], fontsize=7)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax = axes[1]
    colours = {"alive": GREEN, "control": BLUE, "dead": INK}
    for group in sorted(set(groups.values())):
        rows = [i for i in range(len(d["ids"])) if groups.get(d["ids"][i].split(".")[0]) == group]
        share = 100 * np.nanmean(d["score"][rows] >= threshold, axis=0)
        ax.plot(times, share, "o-", color=colours.get(group, ORANGE), label=f"{group} ({len(rows)} mites)")
    ax.set(ylim=(-3, 103), xlabel="minutes since the first recording", ylabel="mites moving (%)",
           title="b. share of each group's mites moving per recording")
    ax.legend(frameon=False)
    fig.savefig(IMAGES / "calls_by_group.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- the benchmark
def step_benchmark(data, threshold):
    """Wrong calls of both methods on every labelled mite-recording, per dataset,
    from the original's whole-frame differentials kept by the notebook."""
    with np.load(pipeline.SCRIPTS_OUTPUT / "abilium_benchmark_diffs.npz") as kept:
        diffs = {key: kept[key] for key in kept.files}
    table = {}
    for name, d in data.items():
        boxes = pipeline.mite_boxes(d["mites"])
        recordings = [rec["name"] for rec in d["dataset"]["recordings"]]
        masks = {}
        for key, diff in diffs.items():
            if key.split("|")[0].rsplit("-", 1)[0] == name:
                masks[key.split("|")[1]] = Benchmark.mask(diff)
        counts = {"app": dict(still_called_moving=0, moving_called_still=0), "original": dict(still_called_moving=0, moving_called_still=0)}
        n = dict(still=0, moving=0)
        for i, mite_id in enumerate(d["ids"]):
            x1, y1, x2, y2 = boxes[mite_id]
            for r, recording in enumerate(recordings):
                if not d["labelled"][i, r]:
                    continue
                truth = bool(d["moving"][i, r])
                n["moving" if truth else "still"] += 1
                calls = {"app": bool(d["score"][i, r] >= threshold),
                         "original": bool(masks[recording][max(0, y1):y2, max(0, x1):x2].any())}
                for method, call in calls.items():
                    if call != truth:
                        counts[method]["moving_called_still" if truth else "still_called_moving"] += 1
        table[name] = dict(n=n, **counts)
    numbers["benchmark"] = table

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.0))
    x = np.arange(len(table))
    for ax, (kind, of) in zip(axes, (("still_called_moving", "still"), ("moving_called_still", "moving"))):
        for offset, method, colour, label in ((-0.2, "app", APP, f"this app (T = {threshold:g})"), (0.2, "original", ORIGINAL, "Discobox original (25)")):
            counts = [table[name][method][kind] for name in table]
            share = [100 * c / table[name]["n"][of] for c, name in zip(counts, table)]
            bars = ax.bar(x + offset, share, 0.38, color=colour, label=label)
            ax.bar_label(bars, [str(c) for c in counts], padding=2, fontsize=8)
        ax.set_xticks(x, [f"{name}\n{table[name]['n']['still'] + table[name]['n']['moving']} labelled" for name in table])
        ax.set(ylabel="%", title=f"{'a' if of == 'still' else 'b'}. {of} recordings called {'moving' if of == 'still' else 'still'} (% of {of})")
    axes[0].legend(frameon=False)
    fig.text(0.01, -0.02, "Bar labels: number of mite-recordings. The 2025 sessions: 1 s at 30 fps, 6 recordings each.", fontsize=8, color="#666")
    fig.savefig(IMAGES / "benchmark_bars.png", bbox_inches="tight")
    plt.close(fig)


def step_shake_robustness(data, threshold):
    """Every still-labelled mite-recording, its plate shaken by more and more:
    the share each method calls moving."""
    rng = np.random.default_rng(0)
    observations = []
    for d in data.values():
        for i, mite_id in enumerate(d["ids"]):
            for r in range(d["score"].shape[1]):
                if d["labelled"][i, r] and not d["moving"][i, r]:
                    observations.append(vw.frames_of(d["dataset"], d["data_dir"], mite_id, r))
    called = {"app": [], "original": []}
    for shake in SHAKES:
        app = original = 0
        for frames, box, pad in observations:
            moved = shaken(frames, shake, rng) if shake else frames
            app += app_score(moved, box, pad) >= threshold
            original += original_calls(moved, box)
        called["app"].append(100 * app / len(observations))
        called["original"].append(100 * original / len(observations))
        print(f"  shake {shake} px: app {called['app'][-1]:.1f} %, original {called['original'][-1]:.1f} %")
    numbers["shake"] = dict(n_still=len(observations), shakes=SHAKES, **called)
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(SHAKES, called["original"], "o-", color=ORIGINAL, label="Discobox original (25)")
    ax.plot(SHAKES, called["app"], "o-", color=APP, label=f"this app (T = {threshold:g}), per-mite stabilization")
    for xs, ys in ((SHAKES, called["original"]), (SHAKES, called["app"])):
        for xv, yv in zip(xs, ys):
            ax.annotate(f"{yv:.0f}", (xv, yv), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=8)
    ax.set(xlabel="plate shake added (px, standard deviation per frame)", ylabel="still recordings called moving (%)",
           title=f"Still mite-recordings of the 2025 sessions ({len(observations)}), the plate shaken")
    ax.legend(frameon=False)
    fig.savefig(IMAGES / "benchmark_shake.png", bbox_inches="tight")
    plt.close(fig)


def step_resources(data):
    storage = {}
    for name, d in data.items():
        saved = sum(f.stat().st_size for f in d["data_dir"].rglob("*") if f.is_file() and "scores" not in f.parts)
        frames = sum(rec["frames"] for rec in d["dataset"]["recordings"])
        storage[name] = (saved / 1e6, frames * BMP_BYTES / 1e6)
    numbers["storage_MB"] = {name: [round(a, 1), round(b, 1)] for name, (a, b) in storage.items()}
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.0))
    for ax, values, unit, title, log in ((axes[0], SPEED, "seconds (log scale)", "a. time to analyse one 90-frame recording", True),
                                         (axes[1], MEMORY, "MB", "b. memory for one 90-frame recording", False),
                                         (axes[2], storage, "MB (log scale)", "c. storage of a session", True)):
        x = np.arange(len(values))
        for offset, k, colour, label in ((-0.2, 0, APP, "this app"), (0.2, 1, ORIGINAL, "Discobox original")):
            bars = ax.bar(x + offset, [v[k] for v in values.values()], 0.38, color=colour, label=label)
            ax.bar_label(bars, [f"{v[k]:.3g}" for v in values.values()], padding=2, fontsize=8)
        ax.set_xticks(x, list(values))
        ax.set(ylabel=unit, title=title, yscale="log" if log else "linear")
        ax.margins(y=0.15)
    axes[0].legend(frameon=False)
    fig.savefig(IMAGES / "speed_memory_storage.png", bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=pipeline.RECORDINGS_ROOT, help="the folder holding the 2025 sessions")
    args = parser.parse_args()
    IMAGES.mkdir(parents=True, exist_ok=True)
    vw.IMAGES = IMAGES
    threshold = get_default_config().mite.threshold_for("outline_variability")
    print("scoring the 2025 sessions"); data = labelled_scores(args.root)
    moving, still = pick_examples(data)
    numbers.update(moving=moving, still=still, threshold=threshold)
    vw.MOVING, vw.STILL = moving, still
    d = data[EXAMPLE]
    print("1. detection"); vw.step_detection(d["data_dir"], moving[0])
    print("2-7. one mite")
    out = {}
    for key, (mite_id, recording) in (("moving", moving), ("still", still)):
        frames, box, pad = vw.frames_of(d["dataset"], d["data_dir"], mite_id, recording)
        shifts = PlateStabilizer().shifts(frames, [box])[0]
        out[key] = dict(mite=mite_id, recording=recording, frames=frames, box=box, pad=pad, shifts=shifts,
                        fixed=Analyzer.grey(PlateStabilizer.cut(frames, box, pad, np.zeros_like(shifts))),
                        roi=Analyzer.grey(PlateStabilizer.cut(frames, box, pad, shifts)))
    _frames_figure(out["moving"])   # (not vw.step_frames_and_stabilizer(): its shake example is the long run)
    vw.step_score(out)
    step_shake(data, still, moving)
    print("calibration, calls"); step_calibration(data, threshold); step_calls(data, threshold)
    print("benchmark"); step_benchmark(data, threshold)
    print("shake robustness"); step_shake_robustness(data, threshold)
    step_resources(data)
    numbers["walkthrough"] = vw.numbers
    NUMBERS.parent.mkdir(parents=True, exist_ok=True)
    NUMBERS.write_text(json.dumps(numbers, indent=1, default=str), encoding="utf-8")
    print(json.dumps(numbers, indent=1, default=str))


def _frames_figure(m):
    """walk_2_frames: a few frames of the moving mite, their mean and variance."""
    n = len(m["fixed"])
    fig, axes = plt.subplots(1, 6, figsize=(15, 2.9))
    for ax, at in zip(axes, [0, n // 3, 2 * n // 3, n - 1]):
        vw.grey_image(ax, m["fixed"][at], f"frame {at + 1} of {n}")
    vw.grey_image(axes[4], m["fixed"].mean(axis=0), "mean of the frames")
    im = axes[5].imshow(m["fixed"].var(axis=0), cmap="magma")
    axes[5].set_title("variance over the frames\n(grey levels²)"), axes[5].set_xticks([]), axes[5].set_yticks([])
    fig.colorbar(im, ax=axes[5], fraction=0.046)
    fig.suptitle(f"Mite {m['mite']}, recording {m['recording'] + 1}: its patch (box + {m['pad']} px) cut from every frame", y=1.04)
    vw.save(fig, "2_frames")


if __name__ == "__main__":
    main()
