"""How far the rays reach (report/2_how_it_works.md, section 3.3): the reach rho is the smaller of
`ray_reach_px` and the distance from the centre to the patch's edge, and a patch whose rho is
under 2 px gets no score. Two schematic cases, drawn to scale with the app's constants:
a valid mite (centre in the middle of its patch) and an invalid one (the body found is at the
patch's edge).

    python report/scripts/fig_ray_reach.py [<out dir>]

Writes ray_reach.png into report/images (or the folder given). Needs no data.
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
from matplotlib.patches import Circle, Rectangle  # noqa: E402

from classes.app_config import get_default_config  # noqa: E402
from classes.scoring.analyzer import Analyzer  # noqa: E402

PARAMS = get_default_config().mite.params_for("outline_variability")
PAD = Analyzer.roi_padding("outline_variability", PARAMS)   # metric_pad: 16 px
REACH = 13.0                                                # ray_reach_px
K = 64                                                      # rays
MIN_REACH = 2.0
ROI = 13                                                    # a typical mite's ROI, px
SIDE = ROI + 2 * PAD                                        # the patch, px
GREEN, ORANGE, BLUE, INK, GREY = "#1b9e77", "#d95f02", "#2a78d6", "#222222", "#e8e8e8"


def draw(ax, centre, title, verdict, colour, body=3.2):
    cx, cy = centre
    rho = min(REACH, cx, cy, SIDE - cx, SIDE - cy)          # distance to the nearest patch edge
    ax.add_patch(Rectangle((0, 0), SIDE, SIDE, facecolor=GREY, edgecolor=BLUE, lw=2, zorder=1))
    ax.add_patch(Rectangle((PAD, PAD), ROI, ROI, fill=False, edgecolor=GREEN, lw=1.4, ls="--", zorder=2))
    ax.add_patch(Circle((cx, cy), body, facecolor="#555555", edgecolor="none", zorder=3))      # the body
    ax.add_patch(Circle((cx, cy), REACH, fill=False, edgecolor=INK, lw=1, ls=":", zorder=3))  # the full reach
    for k in range(K):
        t = 2 * np.pi * k / K
        ax.plot([cx, cx + rho * np.cos(t)], [cy, cy + rho * np.sin(t)], color="#e6a800", lw=1.1, zorder=4)
    ax.plot(cx, cy, "+", color="white", ms=7, mew=1.2, zorder=5)
    if rho < REACH:                                          # show what stops the rays
        nearest = min((cx, "left"), (cy, "top"), (SIDE - cx, "right"), (SIDE - cy, "bottom"))
        side = nearest[1]
        ex, ey = {"left": (0, cy), "right": (SIDE, cy), "top": (cx, 0), "bottom": (cx, SIDE)}[side]
        ax.annotate("", xy=(ex, ey), xytext=(cx, cy), arrowprops=dict(arrowstyle="<->", color=colour, lw=1.4), zorder=6)
    ax.set_ylim(SIDE + 3, -3)                                # y grows downwards, as in the image
    ax.set_xlim(-REACH - 3, SIDE + 3)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, loc="left", fontsize=11)
    ax.text(SIDE / 2, SIDE + 5.5, verdict.format(rho=rho), ha="center", va="top", fontsize=10.5, color=colour, fontweight="bold")
    return rho


fig, ax = plt.subplots(1, 2, figsize=(11, 5.6))
r1 = draw(ax[0], (SIDE / 2, SIDE / 2), "a. valid: the centre is in the middle of the patch",
          "ρ = {rho:.0f} px (the full reach): scored", GREEN)
r2 = draw(ax[1], (1.5, SIDE / 2 - 4), "b. invalid: the body found is on the patch's edge",
          "ρ = {rho:.1f} px < 2 px: no score", ORANGE, body=1.0)
ax[1].text(-REACH / 2 - 1, SIDE / 2 - 4, "no pixels\nbeyond the\npatch", ha="center", va="center", fontsize=8.5, color="#777777")
ax[1].text(SIDE / 2 + 2, SIDE / 2 - 12, "the mite in the middle\nis not the body found", ha="center", fontsize=9, color="#555555")
handles = [
    Rectangle((0, 0), 1, 1, facecolor=GREY, edgecolor=BLUE, lw=2),
    Rectangle((0, 0), 1, 1, fill=False, edgecolor=GREEN, ls="--", lw=1.4),
    plt.Line2D([], [], color="#e6a800", lw=1.2),
    plt.Line2D([], [], color=INK, ls=":", lw=1),
]
fig.legend(handles, [f"the patch (ROI + {PAD} px)", "the ROI", f"the {K} rays, up to the reach ρ",
                     f"ray_reach_px = {REACH:.0f} px"], loc="lower center", ncol=4, frameon=False, fontsize=9.5)
fig.subplots_adjust(bottom=0.12, wspace=0.05)
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "report" / "images"
out.mkdir(parents=True, exist_ok=True)
fig.savefig(out / "ray_reach.png", dpi=150, bbox_inches="tight")
print("wrote", out / "ray_reach.png", f"(rho {r1:.1f} and {r2:.1f})")
