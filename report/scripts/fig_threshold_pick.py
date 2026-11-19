"""How the threshold is picked (report/2_how_it_works.md, section 6): five labelled scores, F0.25 of
the calls at a threshold on each of them, the best of those, and the threshold put halfway into the
gap below it. The numbers come from the app's own functions (classes/ground_truth/calibration.py),
so the figure shows what the app does.

    python report/scripts/fig_threshold_pick.py [<out dir>]

Writes threshold_pick.png into report/images (or the folder given). Needs no data.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from classes.ground_truth import calibration  # noqa: E402

GREEN, ORANGE, BLUE, INK = "#1b9e77", "#d95f02", "#2a78d6", "#222222"
SCORES = np.array([0.30, 0.12, 0.09, 0.05, 0.02])          # the report's example
MOVING = np.array([True, True, True, False, False])       # by eye: the first three are moving

_recall, _precision, f_scores, thresholds = calibration.precision_recall_curve(SCORES, MOVING)
best = calibration.best_f05_threshold(SCORES, MOVING)
lowest_moving = thresholds[int(np.argmax(f_scores))]
order = np.argsort(thresholds)
assert abs(best - (lowest_moving + SCORES[SCORES < lowest_moving].max()) / 2) < 1e-9

fig, (top, bottom) = plt.subplots(2, 1, figsize=(9.5, 6.4), sharex=True, gridspec_kw={"height_ratios": [1, 1.5], "hspace": 0.12})

# top: the labelled scores on the score axis, the region called moving by the final threshold
top.axvspan(best, 0.33, color=GREEN, alpha=0.10)
top.axvspan(0, best, color=ORANGE, alpha=0.08)
for x, m in zip(SCORES, MOVING):
    top.plot(x, 0, "o", ms=15, color=GREEN if m else ORANGE, mec="white", mew=1.5, zorder=3)
    top.annotate(f"{x:.2f}", (x, 0), xytext=(0, 14), textcoords="offset points", ha="center", fontsize=10)
for x in SCORES:                                              # the candidate thresholds
    top.axvline(x, color=INK, ls=":", lw=1, ymin=0.1, ymax=0.9)
top.axvline(best, color=BLUE, lw=2.5, ymin=0.05, ymax=0.95)
top.text(best, 0.62, f" threshold {best:.2f}", color=BLUE, fontsize=11, fontweight="bold", va="center")
top.text(0.325, -0.55, "called moving", ha="right", color=GREEN, fontsize=10)
top.text(0.005, -0.55, "called still", ha="left", color=ORANGE, fontsize=10)
top.set_ylim(-0.8, 0.9); top.set_yticks([])
for side in ("left", "right", "top"):
    top.spines[side].set_visible(False)
top.set_title("a. Five labelled recordings, by score (green: moving by eye, orange: still). "
              "Dotted: the thresholds tried", loc="left", fontsize=10.5)

# bottom: F0.25 when the threshold sits exactly on each labelled score
bottom.step(thresholds[order], f_scores[order], where="post", color="#bbbbbb", lw=1, zorder=1)
for t, f in zip(thresholds, f_scores):
    k = int(np.argmin(abs(SCORES - t)))
    bottom.plot(t, f, "o", ms=11, color=INK if t != lowest_moving else BLUE, zorder=3)
    bottom.annotate(f"{f:.2f}", (t, f), xytext=(0, 12), textcoords="offset points", ha="center", fontsize=10)
bottom.plot(lowest_moving, f_scores[int(np.argmax(f_scores))], "*", ms=24, color=BLUE, zorder=4, mec="white")
bottom.annotate("", xy=(best, 0.5), xytext=(lowest_moving, 0.5), arrowprops=dict(arrowstyle="->", color=BLUE, lw=2))
bottom.text(lowest_moving + 0.006, 0.5, "halfway between 0.09 and 0.05", ha="left", va="center", fontsize=9.5, color=BLUE)
bottom.axvline(best, color=BLUE, lw=2.5, ymax=0.95)
bottom.set_ylim(0.4, 1.12); bottom.set_xlim(0, 0.33)
bottom.set_xlabel("threshold (score)"); bottom.set_ylabel("$F_{0.25}$ of the calls")
bottom.set_title("b. $F_{0.25}$ of the calls with the threshold on each score; the best is the star", loc="left", fontsize=10.5)
for side in ("right", "top"):
    bottom.spines[side].set_visible(False)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "report" / "images"
out.mkdir(parents=True, exist_ok=True)
fig.savefig(out / "threshold_pick.png", dpi=150, bbox_inches="tight")
print("wrote", out / "threshold_pick.png", f"(best {lowest_moving}, threshold {best})")
