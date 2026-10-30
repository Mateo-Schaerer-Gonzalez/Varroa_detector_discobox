"""The figures of report/visual_how_it_works.md: every step of the analysis, run
with the app's own functions on one mite of the poke run, drawn.

The moving example is mite 7.1 in recording 8, the still one mite 7.3 in
recording 19, as in report/2_how_it_works.md. Every number a figure shows comes
from the function named in its title; nothing is re-implemented except where a
picture needs an intermediate the function keeps to itself (the unrolled mean
frame, the binarised frames of the blob detector), and those are marked.

    python scripts/visual_walkthrough.py                      # the poke run in %TEMP%/zzrc/gt
    python scripts/visual_walkthrough.py --root <folder holding poke_test_oct>
    python scripts/visual_walkthrough.py --long-run %TEMP%/zzrc/perf/long_run   # a copy of the long run

Writes report/images/walk_*.png and results/scripts/visual_walkthrough.json
(the numbers the text quotes). Reads only.
"""
import argparse
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# The defaults everyone has, not this machine's config.yaml (only read).
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

import pipeline  # noqa: E402
from pipeline import clips, plate_zones, run_results, scoring  # noqa: E402
from pipeline.calibration import dataset_library, score_cache  # noqa: E402
from classes.app_config import get_default_config  # noqa: E402
from classes.ground_truth import calibration  # noqa: E402
from classes.results.result_groups import Calls  # noqa: E402
from classes.results.survival import SurvivalAnalysis  # noqa: E402
from classes.scoring import analyzer, motion_analysis, plate_stabilizer  # noqa: E402
from classes.scoring.analyzer import Analyzer, NoNoiseWarning  # noqa: E402
from classes.scoring.plate_stabilizer import PlateStabilizer  # noqa: E402
import script_data  # noqa: E402

IMAGES = ROOT / "report" / "images"
NUMBERS = pipeline.SCRIPTS_OUTPUT / "visual_walkthrough.json"
DATASET = "poke_test_oct"
LONG_RUN = "test_run_2026-09-08_Mathis_last_dsRNA"
MOVING, STILL = ("7.1", 8), ("7.3", 19)
INTERPOLATION = {cv2.INTER_LINEAR: "bilinear", cv2.INTER_LANCZOS4: "Lanczos"}.get(plate_stabilizer.INTERPOLATION, "?")
F_NAME = f"F{calibration.F_BETA:g}"
GREEN, ORANGE, BLUE, GREY, INK = "#1b9e77", "#d95f02", "#2a78d6", "#c3c2b7", "#52514e"
plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 130, "font.size": 9, "axes.titlesize": 9.5,
                     "axes.spines.top": False, "axes.spines.right": False})
numbers = {}


def save(fig, name):
    fig.savefig(IMAGES / f"walk_{name}.png", bbox_inches="tight")
    plt.close(fig)
    print("  wrote", f"walk_{name}.png")


def grey_image(ax, image, title, **more):
    ax.imshow(image, cmap="gray", vmin=more.pop("vmin", 0), vmax=more.pop("vmax", 255), **more)
    ax.set_title(title)
    ax.set_xticks([]), ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


# ---------------------------------------------------------------- 1. detection
def step_detection(data_dir, mite_id):
    first = cv2.imread(str(data_dir / "first_frame.png"), cv2.IMREAD_GRAYSCALE)
    zones = plate_zones.zones_of(data_dir)
    analyzer = Analyzer()
    masked = motion_analysis.detect_mites(zones, first, analyzer)
    mites = zones.mites
    numbers["detected"] = len(mites)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    grey_image(axes[0], first, "a. first frame (first_frame.png)")
    grey_image(axes[1], masked, "b. zones.mask_image_to_valid_rois(): plates kept, labels blanked")
    grey_image(axes[2], masked, f"c. analyzer.detect(): {len(mites)} mites, boxes and ids")
    for mite in mites:
        axes[2].add_patch(Rectangle((mite.x1, mite.y1), mite.x2 - mite.x1, mite.y2 - mite.y1, fill=False, ec=GREEN, lw=0.8))
    for zone in zones.valid_zones:
        axes[2].add_patch(Rectangle((zone.x1, zone.y1), zone.x2 - zone.x1, zone.y2 - zone.y1, fill=False, ec=BLUE, lw=0.6))
        axes[2].text(zone.x1 + 15, zone.y1 + 60, str(zone.id), color=BLUE, fontsize=7)
    save(fig, "1_detection")

    # zoom on the plate of the example mite: what the blob detector sees at a few grey levels
    zone = next(z for z in zones.valid_zones if str(z.id) == mite_id.split(".")[0])
    crop = masked[zone.y1:zone.y2, zone.x1:zone.x2]
    levels = (40, 80, 110)
    fig, axes = plt.subplots(1, len(levels) + 1, figsize=(15, 3.6))
    for ax, level in zip(axes, levels):
        grey_image(ax, np.where(crop < level, 0, 255), f"dark below grey level {level}\n(one of SimpleBlobDetector's 18 levels)")
    grey_image(axes[-1], crop, f"plate {zone.id}: the mites kept, ids in reading order")
    for mite in zone.mites:
        axes[-1].add_patch(Rectangle((mite.x1 - zone.x1, mite.y1 - zone.y1), mite.x2 - mite.x1, mite.y2 - mite.y1,
                                     fill=False, ec=GREEN, lw=1))
        axes[-1].text(mite.x2 - zone.x1 + 3, mite.y1 - zone.y1, mite.text, color=GREEN, fontsize=8, fontweight="bold")
    save(fig, "1_detection_plate")


# ---------------------------------------------------------------- frames of one mite
def frames_of(dataset, data_dir, mite_id, recording):
    """(frames of a region round the mite, its box in that region, pad): its box
    where the live run followed it to in that recording (RoiRecordings.placements()),
    as an analysis of the saved run cuts it."""
    mite = next(m for m in dataset["mites"] if m["id"] == mite_id)
    pad = Analyzer.roi_padding("outline_variability", get_default_config().mite.params_for("outline_variability"))
    loader = score_cache.open_recordings(data_dir)
    name = dataset["recordings"][recording]["name"]
    placed = loader.placements(name)
    box = placed[loader.number_at(mite["x"], mite["y"])] if placed else None
    if box is None:
        box = score_cache.mite_boxes([mite])[mite_id]
    box = tuple(int(round(v)) for v in box)
    x0, y0, x_end, y_end = clips.bounds([(box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)], scoring.STABILIZE_MARGIN)
    frames = loader.load_recording_region(name, x0, y0, x_end, y_end)
    return np.asarray(frames), (box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0), pad


# ---------------------------------------------------------------- 2. frames, 3. stabilizer
def step_frames_and_stabilizer(dataset, data_dir, long_run_dir):
    out = {}
    for name, (mite_id, recording) in (("moving", MOVING), ("still", STILL)):
        frames, box, pad = frames_of(dataset, data_dir, mite_id, recording)
        shifts = PlateStabilizer().shifts(frames, [box])[0]
        fixed = PlateStabilizer.cut(frames, box, pad, np.zeros_like(shifts))
        stabilized = PlateStabilizer.cut(frames, box, pad, shifts)
        out[name] = dict(mite=mite_id, recording=recording, frames=frames, box=box, pad=pad, shifts=shifts,
                         fixed=Analyzer.grey(fixed), roi=Analyzer.grey(stabilized))
        numbers[f"{name}_frames"] = int(len(frames))
        numbers[f"{name}_largest_shift_px"] = round(float(np.hypot(*shifts.T).max()), 3)

    # 2. the recording: a few frames of the moving mite, its mean, its variance
    m = out["moving"]
    n = len(m["roi"])
    picks = [0, n // 3, 2 * n // 3, n - 1]
    fig, axes = plt.subplots(1, 6, figsize=(15, 2.9))
    for ax, at in zip(axes, picks):
        grey_image(ax, m["fixed"][at], f"frame {at + 1} of {n}")
    grey_image(axes[4], m["fixed"].mean(axis=0), "mean of the frames")
    variance = m["fixed"].var(axis=0)
    im = axes[5].imshow(variance, cmap="magma")
    axes[5].set_title("variance over the frames\n(grey levels²)"), axes[5].set_xticks([]), axes[5].set_yticks([])
    fig.colorbar(im, ax=axes[5], fraction=0.046)
    fig.suptitle(f"Mite {m['mite']}, recording {m['recording']}: its patch (box + {m['pad']} px) cut from every frame", y=1.04)
    save(fig, "2_frames")

    # 3a. how the stabilizer finds the centre: darkness, body mask, centre per frame
    s = out["still"]
    box = s["box"]
    sp = PlateStabilizer().pad
    patches = plate_stabilizer._gray(plate_stabilizer._patches(s["frames"], box[0] - sp, box[1] - sp, box[2] + sp, box[3] + sp))
    centres = plate_stabilizer._centres(patches)
    height, width = patches.shape[1:]
    rim = np.ones((height, width), bool)
    rim[plate_stabilizer._RIM:-plate_stabilizer._RIM, plate_stabilizer._RIM:-plate_stabilizer._RIM] = False
    plate = np.median(patches[:, rim], axis=1)
    dark = np.clip(1 - patches / plate[:, None, None], 0, None)
    still_dark = dark.mean(axis=0)
    body = still_dark > plate_stabilizer.BODY_SHARE * np.sort(still_dark[~rim])[-plate_stabilizer.DARKEST_N:].mean()
    grown = cv2.dilate((body & ~rim).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=plate_stabilizer.BODY_GROW)
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.4))
    grey_image(axes[0], patches[0], f"a. crop: box + {sp} px, frame 1\nblue: the rim (outer {plate_stabilizer._RIM} px), plate only")
    axes[0].imshow(np.ma.masked_where(~rim, rim), cmap="Blues", alpha=0.35, vmin=0, vmax=1)
    im = axes[1].imshow(still_dark, cmap="viridis")
    axes[1].set_title("b. darkness D = max(0, 1 − I / plate light)\nmean of the frames"), axes[1].set_xticks([]), axes[1].set_yticks([])
    fig.colorbar(im, ax=axes[1], fraction=0.046)
    grey_image(axes[2], patches[0], "c. body mask B: D > 0.3 × the darkest, grown 2 px\n+ centre of darkness in every frame")
    axes[2].contour(grown, levels=[0.5], colors=ORANGE, linewidths=1.2)
    axes[2].plot(centres[:, 0], centres[:, 1], ".", ms=2, color=GREEN)
    ax = axes[3]
    ax.plot(s["shifts"][:, 0], label="x (right)", color=BLUE)
    ax.plot(s["shifts"][:, 1], label="y (down)", color=ORANGE)
    ax.set(xlabel="frame", ylabel="shift since frame 1 (px)", title="d. PlateStabilizer().shifts(): s_t = c_t − c_1")
    ax.legend(frameon=False)
    fig.suptitle(f"Still mite {s['mite']}, recording {s['recording']}: what the stabilizer measures", y=1.04)
    save(fig, "3_stabilizer_centre")

    # 3b. what stabilizing changes: variance without and with. The poke run hardly shakes
    # (0.07 px at most in a still recording), so the still example is the long run's
    # shakiest still-labelled recording (the shifts scripts/interpolation.py measured).
    table = pd.read_csv(pipeline.SCRIPTS_OUTPUT / "interpolation.csv.gz", dtype={"mite": str})
    pick = table[(table["dataset"] == LONG_RUN) & table["labelled"] & ~table["moving"]].nlargest(1, "shake").iloc[0]
    long_run = dataset_library.read_dataset(long_run_dir.name, long_run_dir.parent)
    mite_id, recording = pick["mite"], int(pick["recording"])
    frames, box, pad = frames_of(long_run, Path(long_run["data_dir"]), mite_id, recording)
    shifts = PlateStabilizer().shifts(frames, [box])[0]
    shaky = dict(mite=f"{mite_id} (long run)", recording=recording, shifts=shifts,
                 fixed=Analyzer.grey(PlateStabilizer.cut(frames, box, pad, np.zeros_like(shifts))),
                 roi=Analyzer.grey(PlateStabilizer.cut(frames, box, pad, shifts)))
    numbers.update(shaky_mite=mite_id, shaky_recording=recording, shaky_frames=len(frames),
                   shaky_largest_shift_px=round(float(np.hypot(*shifts.T).max()), 3))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NoNoiseWarning)
        for key, roi in (("fixed", shaky["fixed"]), ("stabilized", shaky["roi"])):
            numbers[f"shaky_score_{key}"] = round(float(Analyzer._motion_score(roi, "outline_variability",
                                                                               get_default_config().mite.params_for("outline_variability"))), 4)
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.6), layout="constrained")
    for row, (key, e) in zip(axes, (("shakiest still", shaky), ("moving", out["moving"]))):
        v_fixed, v_stab = e["fixed"].var(axis=0), e["roi"].var(axis=0)
        top = np.percentile(np.concatenate([v_fixed.ravel(), v_stab.ravel()]), 99.5)
        for ax, v, title in ((row[0], v_fixed, "not stabilized: cut at the box"),
                             (row[1], v_stab, f"PlateStabilizer.cut(): each frame moved back by −s_t ({INTERPOLATION})")):
            im = ax.imshow(v, cmap="magma", vmin=0, vmax=top)
            ax.set_title(f"{key} mite {e['mite']}, rec. {e['recording']}\n{title}"), ax.set_xticks([]), ax.set_yticks([])
        fig.colorbar(im, ax=row[1], fraction=0.046, label="variance (grey levels²)")
        ax = row[2]
        ax.plot(np.hypot(*e["shifts"].T), color=INK)
        ax.set(xlabel="frame", ylabel="|s_t| (px)", title=f"shift length, largest {np.hypot(*e['shifts'].T).max():.2f} px")
        numbers[f"{key}_edge_variance_fixed_vs_stabilized"] = [round(float(np.percentile(v, 99)), 2) for v in (v_fixed, v_stab)]
    save(fig, "3_stabilizer_effect")
    return out


# ---------------------------------------------------------------- 4.-7. the score
def step_score(out):
    m, s = out["moving"], out["still"]
    params = get_default_config().mite.params_for("outline_variability")

    # 4. lamp: per-frame plate light and the frames brought to the same light
    roi = m["roi"]
    lit, light, edge = Analyzer._lit(roi)
    plate = np.median(roi[:, edge], axis=1)
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.3), gridspec_kw={"width_ratios": [1, 2, 1]})
    grey_image(axes[0], roi.mean(axis=0), f"a. the rim R (blue): outer {analyzer.RIM} px of the patch")
    axes[0].imshow(np.ma.masked_where(~edge, edge), cmap="Blues", alpha=0.4, vmin=0, vmax=1)
    axes[1].plot(plate, color=INK, label="P_t: median of the rim per frame")
    axes[1].axhline(light, color=BLUE, ls="--", label=f"L = mean light = {light:.1f}")
    axes[1].set(xlabel="frame", ylabel="grey level", title="b. Analyzer._lit(): every frame scaled by L / P_t")
    axes[1].legend(frameon=False)
    rim_var = lit[:, edge].var(axis=0)
    noise = Analyzer.plate_noise(roi)
    axes[2].hist(rim_var, bins=40, color=GREY)
    axes[2].axvline(noise, color=BLUE, lw=2)
    axes[2].set(xlabel="variance over the frames (grey levels²)", ylabel="rim pixels",
                title=f"c. Analyzer.plate_noise(): median σ² = {noise:.2f}")
    save(fig, "4_lamp_noise")
    numbers.update(moving_light=round(light, 2), moving_noise=round(noise, 3), rim_pixels=int(edge.sum()))

    # 5. rays: the rays, the edge, the outline band; the unrolled variance
    variance, body_ends, step, centre = Analyzer._outline_rays(roi)
    K, band = analyzer.ANGLES, params["width"]
    angles = np.arange(K) * 2 * np.pi / K
    along = np.arange(variance.shape[1]) * step
    edge_r = body_ends * step
    mean_lit = lit.mean(axis=0)
    # (for the picture only: the mean frame read along the same rays from the mean centre)
    unrolled = cv2.remap(mean_lit, np.float32(centre[0] + np.outer(np.cos(angles), along)),
                         np.float32(centre[1] + np.outer(np.sin(angles), along)), cv2.INTER_LINEAR)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.0), gridspec_kw={"width_ratios": [1, 1.4, 1.4]})
    ax = axes[0]
    grey_image(ax, mean_lit, f"a. {K} rays from the centre (every 4th drawn), every {analyzer.RAY_STEP} px;\nedge e_k (orange), band ±{band:g} px (dotted)")
    for k in range(0, K, 4):
        ax.plot(centre[0] + np.cos(angles[k]) * along[[0, -1]], centre[1] + np.sin(angles[k]) * along[[0, -1]], color="#e6c200", lw=0.4)
    loop = np.append(np.arange(K), 0)
    for r, style in ((edge_r, "-"), (edge_r - band, ":"), (edge_r + band, ":")):
        ax.plot(centre[0] + np.cos(angles[loop]) * r[loop], centre[1] + np.sin(angles[loop]) * r[loop], style, color=ORANGE, lw=1.2)
    extent = [0, along[-1], K - 0.5, -0.5]
    axes[1].imshow(unrolled, cmap="gray", aspect="auto", extent=extent, vmin=0, vmax=255)
    axes[1].plot(edge_r, np.arange(K), color=ORANGE, lw=1.2)
    axes[1].set(xlabel="distance r along the ray (px)", ylabel="ray k (0 = right, clockwise)",
                title="b. unrolled: the mean frame along each ray (picture only)")
    im = axes[2].imshow(variance, cmap="magma", aspect="auto", extent=extent)
    for r, style in ((edge_r, "-"), (edge_r - band, ":"), (edge_r + band, ":")):
        axes[2].plot(r, np.arange(K), style, color="white" if style == "-" else "#bbbbbb", lw=1)
    axes[2].set(xlabel="distance r along the ray (px)", title="c. Analyzer._outline_rays(): V(k, r) = var_t u_t(k, r)")
    fig.colorbar(im, ax=axes[2], label="grey levels²")
    fig.suptitle(f"Moving mite {m['mite']}, recording {m['recording']}", y=1.03)
    save(fig, "5_rays")

    # 6. profile, divided by the noise floor; 7. the vector sum and its harmonics
    rows = {}
    for key, e in (("moving", m), ("still", s)):
        v = Analyzer.outline_variability_profile(e["roi"])
        sigma2 = Analyzer.plate_noise(e["roi"])
        a = v / sigma2
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NoNoiseWarning)
            score = float(Analyzer._motion_score(e["roi"], "outline_variability", params))
        direction = np.exp(2j * np.pi * np.arange(len(a)) / len(a))
        rows[key] = dict(v=v, sigma2=sigma2, a=a, score=score, walk=np.concatenate([[0], np.cumsum(a * direction / len(a))]),
                         harmonics=np.abs(np.fft.rfft(a)) / len(a))
        numbers[f"{key}_score"] = round(score, 4)
        numbers[f"{key}_noise"] = round(sigma2, 3)
        numbers[f"{key}_mean_a"] = round(float(a.mean()), 3)
        numbers[f"{key}_fft_h1_check"] = round(float(rows[key]["harmonics"][1]), 4)
        numbers[f"{key}_vector_sum_length"] = round(float(rows[key]["harmonics"][1]), 4)

    fig = plt.figure(figsize=(15, 4.0))
    ax = fig.add_subplot(1, 3, 1)
    for key, colour in (("moving", GREEN), ("still", ORANGE)):
        ax.plot(np.degrees(angles), rows[key]["v"], color=colour, label=f"{key}: v_k (grey levels²)")
    ax.set(xlabel="direction θ_k (°)", ylabel="mean variance on the outline", title="a. outline_variability_profile(): v_k")
    ax.legend(frameon=False)
    ax = fig.add_subplot(1, 3, 2)
    for key, colour in (("moving", GREEN), ("still", ORANGE)):
        ax.plot(np.degrees(angles), rows[key]["a"], color=colour, label=f"{key}: a_k = v_k / {rows[key]['sigma2']:.2f}")
    ax.axhline(1, color=INK, ls=":", lw=1)
    ax.set(xlabel="direction θ_k (°)", ylabel="multiples of the noise floor", title="b. divided by plate_noise(): a_k")
    ax.legend(frameon=False)
    ax = fig.add_subplot(1, 3, 3, projection="polar")
    for key, colour in (("moving", GREEN), ("still", ORANGE)):
        ax.plot(np.append(angles, angles[0]), np.append(rows[key]["a"], rows[key]["a"][0]), color=colour)
    ax.set_theta_direction(-1)
    ax.set_title("c. the same round the mite\n(0° right, clockwise as in the image)")
    save(fig, "6_profile")

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    for ax, key, colour in ((axes[0], "moving", GREEN), (axes[1], "still", ORANGE)):
        walk = rows[key]["walk"]
        ax.plot(walk.real, walk.imag, ".-", color=colour, ms=2, lw=0.8)
        ax.annotate("", xy=(walk[-1].real, walk[-1].imag), xytext=(0, 0),
                    arrowprops=dict(arrowstyle="->", color=INK, lw=1.5))
        ax.plot(0, 0, "o", color=INK, ms=4)
        ax.set_aspect("equal")
        ax.invert_yaxis()   # y down, as in the image
        ax.set(xlabel="x", ylabel="y (down)",
               title=f"{'a' if key == 'moving' else 'b'}. {key}: the {K} arrows a_k·e_k / {K} tip to tail, \nblack arrow {abs(rows[key]['walk'][-1]):.3f} = score {rows[key]['score']:.3f}")
    ax = axes[2]
    h = np.arange(11)
    ax.bar(h - 0.2, rows["moving"]["harmonics"][:11], width=0.4, color=GREEN, label="moving")
    ax.bar(h + 0.2, rows["still"]["harmonics"][:11], width=0.4, color=ORANGE, label="still")
    ax.set_yscale("log")
    ax.set(xlabel="harmonic h", ylabel=f"|np.fft.rfft(a)[h]| / {K}",
           title="c. the profile's harmonics: the score is h = 1\n(h = 0 is the mean, which the sum cancels)")
    ax.legend(frameon=False)
    save(fig, "7_vector_sum")
    return rows


# ---------------------------------------------------------------- 8.-10. over the run
def step_run(dataset, data_dir, rows):
    # the app's analysis of the saved run: detect, follow and score every mite in every recording
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NoNoiseWarning)
        run = scoring.detect_and_score(data_dir, None)
    by_id = {mite.text: mite for mite in run.zone_manager.mites}

    mites, moving, labelled = script_data.labels_of(dataset)
    ids = [mite["id"] for mite in mites]
    raw = [by_id[i].motion_scores for i in ids]
    there = np.array([[value is not None for value in scores] for scores in raw])   # not followed: dead, or not yet added
    score = np.array([[np.nan if value is None else value for value in scores] for scores in raw])
    times = np.asarray(dataset["times"], dtype=float)
    for key, (mite_id, recording) in (("moving", MOVING), ("still", STILL)):
        app = score[ids.index(mite_id), recording]
        numbers[f"{key}_score_by_app_run"] = round(float(app), 6)
        numbers[f"{key}_score_steps_minus_app"] = float(rows[key]["score"] - app)
    hours = times / 60

    use = labelled & there
    threshold = calibration.best_f05_threshold(score[use], moving[use])
    counts = calibration.confusion(score[use], moving[use], threshold)
    numbers.update(threshold=round(threshold, 4), n_mites=len(ids), n_recordings=len(times),
                   n_labelled=int(use.sum()), n_moving_labels=int(moving[use].sum()),
                   still_called_moving=counts["still_called_moving"], moving_called_still=counts["moving_called_still"],
                   average_precision=round(calibration.average_precision(score[use], moving[use]), 4))

    # 8. one mite's scores over the run against the threshold
    index = ids.index(MOVING[0])
    fig, ax = plt.subplots(figsize=(12, 3.4))
    ok = there[index]
    ax.plot(hours[ok], score[index, ok], "-", color=GREY, lw=0.8)
    called = score[index] >= threshold
    ax.plot(hours[ok & called], score[index, ok & called], "o", color=GREEN, ms=4, label="called moving (score ≥ T)")
    ax.plot(hours[ok & ~called], score[index, ok & ~called], "o", color=ORANGE, ms=4, label="called still")
    lab = labelled[index] & ok
    ax.plot(hours[lab], score[index, lab], "s", mfc="none", mec=INK, ms=9, label="labelled by eye")
    ax.axhline(threshold, color=INK, ls="--", lw=1)
    ax.text(0.99, threshold, f"T = {threshold:.3f}", va="bottom", ha="right", transform=ax.get_yaxis_transform())
    ax.set(yscale="log", xlabel="hours since the start", ylabel="score", title=f"Mite {MOVING[0]}: one score per recording, one call each")
    ax.legend(frameon=False, ncol=3, loc="lower left")
    save(fig, "8_threshold")

    # 9. calibration: scores of the labels, precision-recall, the F-score
    recall, precision, f05, thresholds = calibration.precision_recall_curve(score[use], moving[use])
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.6))
    bins = np.logspace(np.log10(max(score[use].min(), 1e-3)), np.log10(score[use].max()), 30)
    axes[0].hist(score[use][~moving[use]], bins=bins, color=ORANGE, alpha=0.8, label="labelled still")
    axes[0].hist(score[use][moving[use]], bins=bins, color=GREEN, alpha=0.8, label="labelled moving")
    axes[0].axvline(threshold, color=INK, ls="--")
    axes[0].set(xscale="log", xlabel="score", ylabel="recordings", title="a. the labelled recordings' scores")
    axes[0].legend(frameon=False)
    axes[1].plot(recall, precision, color=BLUE)
    best = int(np.argmax(f05))
    axes[1].plot(recall[best], precision[best], "o", color=INK)
    axes[1].set(xlabel="recall", ylabel="precision", ylim=(0, 1.02),
                title=f"b. calibration.precision_recall_curve(), AP = {numbers['average_precision']:.3f}")
    axes[2].plot(thresholds, f05, color=BLUE)
    axes[2].axvline(threshold, color=INK, ls="--")
    axes[2].set(xscale="log", xlabel="threshold T", ylabel=F_NAME, title=f"c. best_f05_threshold() = {threshold:.3f}")
    save(fig, "9_calibration")

    # 10. calls -> deaths -> Kaplan-Meier
    death = run_results.death_minutes(data_dir) or 300
    numbers["death_minutes"] = death
    analysis = SurvivalAnalysis(times, death)
    # each mite on its own clock from the recording it was first followed in (Mite.start), as the result pages count it
    movings = [Calls([bool(score[i, r] >= threshold) if there[i, r] else None for r in range(len(times))],
                     start=by_id[mite_id].start) for i, mite_id in enumerate(ids)]
    numbers["added_later"] = {mite_id: by_id[mite_id].start for mite_id in ids if by_id[mite_id].start}
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.4), gridspec_kw={"width_ratios": [1.6, 1]})
    ax = axes[0]
    for row, calls in enumerate(movings):
        for r, call in enumerate(calls):
            if call is not None:
                ax.plot(hours[r], row, "s", ms=3.2, color=GREEN if call else ORANGE)
        if analysis.in_study(calls):
            time, dead = analysis.survival(calls)
            at = (time + times[calls.start]) / 60   # back from the mite's own clock to the run's
            ax.plot(at, row, "x" if dead else ">", color=INK, ms=7, mew=1.5)
        else:
            ax.text(hours[-1] + 0.2, row, "never moved: left out", va="center", fontsize=7)
    ax.set_yticks(range(len(ids)), ids)
    ax.invert_yaxis()
    ax.set(xlabel="hours since the start",
           title=f"a. calls per mite (green moving, orange still)\n× death by the rule (still ≥ {death} min), > alive at its end")
    in_study = analysis.study(movings)
    alive = analysis.alive_percent(in_study)
    ci = analysis.alive_ci(in_study)
    axes[1].step(hours, alive, where="post", color=BLUE)
    axes[1].fill_between(hours, [c if c is not None else np.nan for c in ci["low"]],
                         [c if c is not None else np.nan for c in ci["high"]], step="post", color=BLUE, alpha=0.15)
    axes[1].set(xlabel="hours since the start", ylabel="alive (%)", ylim=(0, 105),
                title=f"b. SurvivalAnalysis.alive_percent(): Kaplan–Meier of {len(in_study)} mites, 95 % CI")
    save(fig, "10_survival")
    numbers["n_in_study"] = len(in_study)
    numbers["n_dead"] = analysis.dead_count(in_study)
    numbers["labels_examples"] = {f"{m} rec {r}": ("moving" if moving[ids.index(m), r] else "still") if labelled[ids.index(m), r] else "unlabelled"
                                  for m, r in (MOVING, STILL)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(tempfile.gettempdir()) / "zzrc" / "gt",
                        help="the folder holding poke_test_oct")
    parser.add_argument("--long-run", type=Path, default=pipeline.RECORDINGS_ROOT / LONG_RUN,
                        help="the long run's folder (or a copy of it)")
    args = parser.parse_args()
    IMAGES.mkdir(parents=True, exist_ok=True)
    dataset = dataset_library.read_dataset(DATASET, args.root)
    data_dir = Path(dataset["data_dir"])
    print("1. detection"); step_detection(data_dir, MOVING[0])
    print("2-3. frames, stabilizer"); out = step_frames_and_stabilizer(dataset, data_dir, args.long_run)
    print("4-7. score"); rows = step_score(out)
    print("8-10. over the run"); step_run(dataset, data_dir, rows)
    NUMBERS.parent.mkdir(parents=True, exist_ok=True)
    NUMBERS.write_text(json.dumps(numbers, indent=1), encoding="utf-8")
    print(json.dumps(numbers, indent=1))


if __name__ == "__main__":
    main()
