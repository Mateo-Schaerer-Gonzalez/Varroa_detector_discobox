"""What the figure scripts here share: where the figures go, the data they are drawn
from (made by its data script when it is missing), and showing them.

Every figure script runs on its own from any folder, e.g.
    python report/scripts/fig_mask.py            # into report/images, then shows it
    python report/scripts/fig_mask.py <folder>   # into <folder>
"""
import subprocess
import sys
from pathlib import Path

import cv2  # noqa: F401  in discobox_env (Windows) matplotlib crashes drawing (0xC06D007F, a DLL not found) unless OpenCV's DLLs are loaded first
import matplotlib
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def out_dir():
    """The folder the figures go to: the first argument, else report/images."""
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "images"
    out.mkdir(parents=True, exist_ok=True)
    return out


def needs(path, script, *args):
    """`path`, made first by running the data script `script` with `args` when it is missing."""
    path = Path(path)
    if not path.exists():
        print(f"{path.name} is missing:", end=" ")
        run(script, *args)
    return path


def run(script, *args):
    """Run the data script `script` (in this folder) with `args`, in the same Python."""
    print(f"running {script} {' '.join(args)} (slow)", flush=True)
    subprocess.run([sys.executable, str(HERE / script), *args], check=True, cwd=REPO)


def interactive():
    """The default (window) backend again, for a script that imports classes/:
    classes/results/reporting.py selects Agg. Call it before the first figure."""
    import matplotlib.pyplot as plt
    plt.switch_backend(matplotlib.rcParamsDefault["backend"])


def threshold():
    """The default threshold of the metric in use, from config.default.yaml (not the machine's config.yaml)."""
    mite = yaml.safe_load(open(REPO / "config.default.yaml"))["mite"]
    return float(mite["metric_thresholds"][mite["metric"]])


def width():
    """The outline band's half-width in use (px), from config.default.yaml."""
    mite = yaml.safe_load(open(REPO / "config.default.yaml"))["mite"]
    return float(mite["metric_params"][mite["metric"]]["width"])


def show():
    """Show every figure drawn, each in its own window."""
    import matplotlib.pyplot as plt
    plt.show()
