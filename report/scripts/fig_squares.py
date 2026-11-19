"""The four squares round a mite (report/2_how_it_works.md, section 2): its ROI, the
stabiliser's crop, the score's patch and the surroundings a live run saves, drawn
on the first frame round the moving example mite (7.1 of the poke run).

    python report/scripts/fig_squares.py                     # the poke run in %TEMP%/zzrc/gt2
    python report/scripts/fig_squares.py <folder holding poke_test_oct> [<out dir>]

Writes squares.png into report/images (or the folder given). Reads only. The
sizes come from the app's constants, so the figure follows them if they change.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import cv2  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from pipeline.calibration import dataset_library, score_cache  # noqa: E402
from classes.app_config import get_default_config  # noqa: E402
from classes.scoring import plate_stabilizer  # noqa: E402
from classes.scoring.analyzer import Analyzer  # noqa: E402
from classes.storage import roi_recordings  # noqa: E402

DATASET, MITE = "poke_test_oct", "7.1"
CONTEXT = 12  # px of slide shown beyond the largest square

metric_pad = Analyzer.roi_padding("outline_variability", get_default_config().mite.params_for("outline_variability"))
# name, grown by (px on every side), colour, what it is for: smallest first
SQUARES = [
    ("ROI", 0, "#1b9e77", "just holds the mite, as found by the detector\nused for: the mite's position, its zone"),
    ("crop", plate_stabilizer.PAD, "#d95f02", f"ROI + {plate_stabilizer.PAD} px on every side\nused for: the stabiliser (section 2.3)"),
    ("patch", metric_pad, "#2a78d6", f"ROI + {metric_pad} px on every side\nused for: the score (section 3)"),
    ("saved surroundings", roi_recordings.ROI_MARGIN, "#7b3294",
     f"ROI + {roi_recordings.ROI_MARGIN} px on every side\nused for: what a live run saves (section 7)"),
]


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "zzrc" / "gt2"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "report" / "images"
    dataset = dataset_library.read_dataset(DATASET, root)
    first = cv2.imread(str(Path(dataset["data_dir"]) / "first_frame.png"), cv2.IMREAD_GRAYSCALE)
    mite = next(m for m in dataset["mites"] if m["id"] == MITE)
    x1, y1, x2, y2 = score_cache.mite_boxes([mite])[MITE]
    reach = SQUARES[-1][1] + CONTEXT
    cx0, cy0 = x1 - reach, y1 - reach
    view = first[cy0:y2 + reach, cx0:x2 + reach]

    fig, (ax, key) = plt.subplots(1, 2, figsize=(10, 5), gridspec_kw={"width_ratios": [1, 1.15]})
    ax.imshow(view, cmap="gray", vmin=0, vmax=255, interpolation="nearest")
    for name, grow, colour, _ in SQUARES:
        # pixel edges lie half a pixel off the pixel centres imshow puts on whole numbers
        ax.add_patch(Rectangle((x1 - grow - cx0 - 0.5, y1 - grow - cy0 - 0.5), x2 - x1 + 2 * grow, y2 - y1 + 2 * grow,
                               fill=False, ec=colour, lw=3))
        ax.text(x1 - grow - cx0 + 0.5, y1 - grow - cy0 - 1.2, name, color=colour, fontsize=9, fontweight="bold",
                va="bottom", bbox=dict(fc="white", ec="none", pad=0.6, alpha=0.85))
    ax.set_xticks([]), ax.set_yticks([])
    ax.set_title(f"Mite {MITE} on the first frame of the poke run", fontsize=10)

    key.axis("off")
    for row, (name, _, colour, text) in enumerate(SQUARES):
        y = 0.88 - row * 0.25
        key.add_patch(Rectangle((0.0, y - 0.04), 0.07, 0.08, fill=False, ec=colour, lw=3, transform=key.transAxes))
        key.text(0.11, y + 0.02, name, color=colour, fontsize=11, fontweight="bold", transform=key.transAxes, va="center")
        key.text(0.11, y - 0.07, text, fontsize=9, transform=key.transAxes, va="center", linespacing=1.4)
    fig.tight_layout()
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "squares.png", dpi=130, bbox_inches="tight")
    print("wrote", out / "squares.png")


if __name__ == "__main__":
    main()
