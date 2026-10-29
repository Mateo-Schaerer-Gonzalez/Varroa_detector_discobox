"""The detector step by step on plates 6 and 7 of the long run (detector_steps.png), read only.
Its outline figures were replaced by fig_outline.py's."""
import os
import sys

import figure_kit

REPO = str(figure_kit.REPO)
sys.path.insert(0, REPO)
os.chdir(REPO)

import cv2
import matplotlib.pyplot as plt

from classes.app_config import get_default_config
from classes.scoring.analyzer import Analyzer
from pipeline import plate_zones

figure_kit.interactive()
RUN = "test_run_2026-09-08_Mathis_last_dsRNA"
OUT = figure_kit.out_dir()
AQUA = "#1baf7a"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "lines.linewidth": 2,
})


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=150, bbox_inches="tight")


def bare(ax):
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)


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
figure_kit.show()
