"""Detector and score figures for report/REPORT.md, from the long run (read only)."""
import os
import sys
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, REPO)
os.chdir(REPO)

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from classes.app_config import get_default_config
from classes.scoring.analyzer import Analyzer
from classes.scoring.plate_stabilizer import PlateStabilizer
from classes.scoring.score_normalizer import ScoreNormalizer
from classes.storage.roi_recordings import RoiRecordings
from pipeline import plate_zones

RUN = "test_run_2026-09-08_Mathis_last_dsRNA"
OUT = os.path.join(REPO, "report", "images")
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "lines.linewidth": 2,
})
PARAMS = {"relative": 0.0, "width": 1.5, "pad": 16}
PAD = 16
THRESHOLD = {"outline_variability": 0.31, "variability": 3.476}  # this machine's config.yaml


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=150, bbox_inches="tight")
    plt.close(fig)


def bare(ax):
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)


m = pd.read_excel(f"results/{RUN}/results.xlsx", sheet_name="measurements")
m["key"] = [f"{x}_{y}" for x, y in zip(m.x, m.y)]
times = sorted(m.time.unique())
rois = RoiRecordings(f"recordings/{RUN}")
names = rois.recording_names
index_mites = rois.index["mites"]
centres = np.array([((b["box"][0] + b["box"][2]) / 2, (b["box"][1] + b["box"][3]) / 2) for b in index_mites])


def number_of(row):
    return int(np.argmin(np.hypot(centres[:, 0] - row.x, centres[:, 1] - row.y)))


def local_box(number):
    box, roi = index_mites[number]["box"], index_mites[number]["roi"]
    return (box[0] - roi[0], box[1] - roi[1], box[2] - roi[0], box[3] - roi[1])


def whole_roi(row):
    """The mite's saved surroundings (box ± 32) in every frame of the row's recording, float32."""
    number = number_of(row)
    return rois.read_mite(names[times.index(row.time)], number).astype(np.float32), local_box(number)


def scored_patch(frames, box, stabilize=True):
    if stabilize:
        shifts = PlateStabilizer().shifts(frames, [box])[0]
        return PlateStabilizer.cut(frames, box, PAD, shifts)[..., 0]
    x1, y1, x2, y2 = box
    return frames[:, y1 - PAD:y2 + PAD, x1 - PAD:x2 + PAD]


# ---------- 1. The detector, step by step on one plate
first = cv2.imread(f"recordings/{RUN}/first_frame.png", cv2.IMREAD_GRAYSCALE)
zones = plate_zones.zones_of(f"recordings/{RUN}")
masked = zones.mask_image_to_valid_rois(first)
analyzer = Analyzer(get_default_config())
keypoints = analyzer.blob_detector.detect(masked)
x0, y0, x1, y1 = 200, 400, 720, 650     # plates 6 and 7 and their labels
fig, axes = plt.subplots(1, 3, figsize=(13, 2.9), gridspec_kw={"wspace": 0.04})
axes[0].imshow(first[y0:y1, x0:x1], cmap="gray", vmin=0, vmax=255)
axes[0].set_title("1. first frame", loc="left", fontsize=10)
axes[1].imshow(masked[y0:y1, x0:x1], cmap="gray", vmin=0, vmax=255)
axes[1].set_title("2. only the plates kept (labels masked)", loc="left", fontsize=10)
axes[2].imshow(first[y0:y1, x0:x1], cmap="gray", vmin=0, vmax=255)
for kp in keypoints:
    x, y = kp.pt
    if x0 <= x < x1 and y0 <= y < y1:
        axes[2].add_patch(plt.Circle((x - x0, y - y0), kp.size / 2 + 3, fill=False, color=AQUA, linewidth=1.6))
axes[2].set_title("3. dark round blobs = mites", loc="left", fontsize=10)
for ax in axes:
    bare(ax)
save(fig, "detector_steps.png")

# ---------- 2. Where the score looks: the outline unrolled
moving_row = m[(m.time < 400) & m.motion_score.between(3, 6) & ~m.disturbed.astype(bool)].sort_values("motion_score", ascending=False).iloc[0]
same = m[m.key == moving_row.key]
still_row = same[same.time > same[same.moving].time.max() + 600].iloc[0]
cases = []
for label, row in (("moving", moving_row), ("still", still_row)):
    frames, box = whole_roi(row)
    patch = scored_patch(frames, box)
    variance, edge, step, centre = Analyzer._outline_rays(patch, PAD)
    profile = Analyzer.outline_variability_profile(patch, PARAMS["width"], PAD)
    cases.append((label, row, patch, variance, edge, step, centre, profile))
mite_name = f"mite {moving_row.mite_ID}"

label, row, patch, variance, edge, step, centre, profile = cases[0]
angle = np.arange(64) * 2 * np.pi / 64
fig, axes = plt.subplots(1, 3, figsize=(13, 3.9), gridspec_kw={"width_ratios": [1, 1, 1.9], "wspace": 0.18})
for ax, image, cmap, title in ((axes[0], patch.mean(axis=0), "gray", "a. mean of the frames"),
                               (axes[1], patch.std(axis=0), "Blues", "b. how much each pixel varies")):
    ax.imshow(image, cmap=cmap)
    for radius, style in ((edge * step - PARAMS["width"], ":"), (edge * step, "-"), (edge * step + PARAMS["width"], ":")):
        r = np.append(radius, radius[0]); a = np.append(angle, angle[0])
        ax.plot(centre[0] + r * np.cos(a), centre[1] + r * np.sin(a), color=ORANGE, linewidth=1.2, linestyle=style)
    for a in angle[::8]:
        ax.plot([centre[0], centre[0] + 13 * np.cos(a)], [centre[1], centre[1] + 13 * np.sin(a)], color=YELLOW, linewidth=0.6, alpha=0.8)
    ax.set_title(title, loc="left", fontsize=10)
    bare(ax)
ax = axes[2]
shown = ax.imshow(variance.T, aspect="auto", origin="lower", cmap="Blues",
                  extent=(0, 360, 0, variance.shape[1] * step))
ax.plot(np.arange(64) * 360 / 64 + 360 / 128, edge * step, color=ORANGE, linewidth=1.5, label="body edge")
ax.fill_between(np.arange(64) * 360 / 64 + 360 / 128, edge * step - 1.5, edge * step + 1.5, color=ORANGE, alpha=0.18, linewidth=0,
                label="outline band (±1.5 px): what is scored")
ax.set_xlabel("direction from the mite's centre (°, clockwise from right)")
ax.set_ylabel("distance from the centre (px)")
ax.set_title("c. the same variance unrolled along 64 rays", loc="left", fontsize=10)
ax.set_xticks([0, 90, 180, 270, 360]); ax.grid(False)
ax.legend(loc="upper right", fontsize=8.5)
fig.colorbar(shown, ax=ax, label="variance (grey levels²)", pad=0.01)
fig.suptitle(f"{mite_name}, moving recording at {row.time:.0f} min", x=0.125, ha="left", fontsize=12, fontweight="bold", y=1.02)
save(fig, "outline_unrolled.png")

# ---------- 3. The 64 values and their vector sum: noise cancels, a leg does not
fig, axes = plt.subplots(1, 3, figsize=(13, 3.9), gridspec_kw={"width_ratios": [1.6, 1, 1], "wspace": 0.3})
ax = axes[0]
degrees = np.arange(64) * 360 / 64
for (label, row, *_rest, profile), colour in zip(cases, (BLUE, MUTED)):
    ax.plot(np.append(degrees, 360), np.append(profile, profile[0]), color=colour, label=f"{label} (score {row.motion_score:.2f})")
    ax.axhline(profile.mean(), color=colour, linewidth=1, linestyle=":")
ax.set_xticks([0, 90, 180, 270, 360]); ax.set_xlim(0, 360)
ax.set_xlabel("direction (°)"); ax.set_ylabel("variance on the outline")
ax.set_title("a. variance per direction (dotted: mean)", loc="left", fontsize=10)
ax.legend(fontsize=8.5)
for ax, (label, row, *_rest, profile) in zip(axes[1:], cases):
    vectors = profile * np.exp(1j * angle) / 64
    path = np.concatenate([[0], np.cumsum(vectors)])
    ax.plot(path.real, -path.imag, color=BLUE if label == "moving" else MUTED, linewidth=1.3, marker="o", markersize=2.5)
    ax.annotate("", xy=(path[-1].real, -path[-1].imag), xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=2.2))
    ax.plot(0, 0, "o", color=INK, markersize=4)
    reach = max(np.abs(path).max(), 0.02) * 1.15
    ax.set_xlim(-reach, reach); ax.set_ylim(-reach, reach); ax.set_aspect("equal")
    ax.set_title(f"b. {label}: 64 arrows tip to tail" if label == "moving" else f"c. {label}: the same", loc="left", fontsize=10)
    ax.text(0.02, 0.02, f"sum = {abs(path[-1]):.2f}\nmean = {profile.mean():.2f}", transform=ax.transAxes, fontsize=9, color=INK2)
save(fig, "outline_vector_sum.png")
