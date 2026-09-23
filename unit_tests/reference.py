"""Snapshots of a folder-mode run, to compare a run with one made before a change.

make_reference.py writes them to unit_tests/reference/ from the code as it was
before live input was added; folder_regression_test.py makes them again from the
code as it is now and compares. Everything a run hands over is covered: the dict
run_analysis() returns, every sheet of results.xlsx, what each figure draws, the
pixels of every image written, and what the command line prints.
"""

import hashlib
import json
import math
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA = ROOT / "sample_data"
REFERENCE_DIR = Path(__file__).resolve().parent / "reference"

# Plate labels for the labelled run: three groups, so grouping is exercised.
LABELS = {str(zone): ["control", "venom 1x", "venom 2x"][zone // 5] for zone in range(15)}
# The mite the labelled run marks "not a mite", by its id in the unlabelled run.
REJECTED_MITE = "3"

# The small session the command line is run on: the first frames of the first
# recordings of sample_data.
SMALL_RECORDINGS = 3
SMALL_FRAMES = 6


def versions():
    return {
        "matplotlib": matplotlib.__version__,
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }


def _plain(value):
    """A JSON-able version of a numpy or pandas value."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Not JSON-able: {value!r}")


def plain(data):
    return json.loads(json.dumps(data, default=_plain))


def _color(value):
    return mcolors.to_hex(value, keep_alpha=True)


def figure_data(fig):
    """What a figure draws: per axes its texts, limits, lines, point sets and bars."""
    axes = []
    for ax in fig.axes:
        legend = ax.get_legend()
        axes.append(
            {
                "title": ax.get_title(),
                "xlabel": ax.get_xlabel(),
                "ylabel": ax.get_ylabel(),
                "xlim": [float(v) for v in ax.get_xlim()],
                "ylim": [float(v) for v in ax.get_ylim()],
                "xticklabels": [t.get_text() for t in ax.get_xticklabels()],
                "legend": None if legend is None else [t.get_text() for t in legend.get_texts()],
                "lines": [
                    {
                        "x": np.asarray(line.get_xdata(), dtype=float).tolist(),
                        "y": np.asarray(line.get_ydata(), dtype=float).tolist(),
                        "color": _color(line.get_color()),
                        "width": float(line.get_linewidth()),
                        "style": str(line.get_linestyle()),
                        "marker": str(line.get_marker()),
                        "markersize": float(line.get_markersize()),
                        "alpha": line.get_alpha(),
                        "label": line.get_label(),
                    }
                    for line in ax.get_lines()
                ],
                "collections": [
                    {
                        "offsets": np.asarray(c.get_offsets(), dtype=float).tolist(),
                        "facecolors": [_color(color) for color in c.get_facecolors()],
                        "sizes": np.asarray(c.get_sizes(), dtype=float).tolist(),
                        "alpha": c.get_alpha(),
                    }
                    for c in ax.collections
                ],
                "patches": [
                    {
                        "x": float(p.get_x()),
                        "y": float(p.get_y()),
                        "width": float(p.get_width()),
                        "height": float(p.get_height()),
                        "facecolor": _color(p.get_facecolor()),
                        "edgecolor": _color(p.get_edgecolor()),
                    }
                    for p in ax.patches
                    if hasattr(p, "get_width")
                ],
            }
        )
    return {"size": [float(v) for v in fig.get_size_inches()], "dpi": float(fig.dpi), "axes": axes}


@contextmanager
def capture_figures():
    """Record figure_data() of every figure saved to a file while this is open,
    by file name."""
    captured = {}
    original = Figure.savefig

    def savefig(self, fname, *args, **kwargs):
        result = original(self, fname, *args, **kwargs)
        captured[Path(str(fname)).name] = plain(figure_data(self))
        return result

    Figure.savefig = savefig
    try:
        yield captured
    finally:
        Figure.savefig = original


def pixel_hash(path):
    """A hash of an image's decoded pixels, so a file re-encoded the same way
    with other metadata still matches."""
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    digest = hashlib.sha256(f"{image.shape}{image.dtype}".encode())
    digest.update(np.ascontiguousarray(image).tobytes())
    return digest.hexdigest()


def excel_sheets(path):
    return {
        name: plain(frame.astype(object).where(pd.notna(frame), None).to_dict(orient="split"))
        for name, frame in pd.read_excel(path, sheet_name=None).items()
    }


def outputs(out_dir):
    """Every file a run wrote: the workbook's sheets and each image's pixels."""
    out_dir = Path(out_dir)
    files = sorted(path.name for path in out_dir.iterdir() if path.is_file())
    return {
        "files": files,
        "excel": {name: excel_sheets(out_dir / name) for name in files if name.endswith(".xlsx")},
        "pixels": {name: pixel_hash(out_dir / name) for name in files if name.endswith((".png", ".jpg"))},
    }


def write_library(library_dir, data_dir, mite):
    """A calibration library in which `mite` (an entry of run_analysis()'s
    "mites") of the folder `data_dir` is marked not a mite."""
    import pipeline

    folder = Path(library_dir) / pipeline.dataset_id(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    dataset = {
        "data_dir": str(Path(data_dir).resolve()),
        "name": Path(data_dir).name,
        "saved_at": "2026-01-01T00:00:00",
        "times": [0.0],
        "recordings": [],
        "image": {},
        "zones": [],
        "mites": [{"id": mite["id"], "zone_id": mite["zone_id"], "x": mite["x"], "y": mite["y"], "r": 8}],
        "truth": {mite["id"]: ["not_a_mite"]},
    }
    (folder / "dataset.json").write_text(json.dumps(dataset), encoding="utf-8")
    return Path(library_dir)


def run_folder(data_dir, out_dir, library_dir, labels=None, **kwargs):
    """run_analysis() on a folder, and a snapshot of everything it produced."""
    import pipeline

    with capture_figures() as figures:
        results = pipeline.run_analysis(data_dir, out_dir, labels, library_dir=library_dir, **kwargs)
    return {"results": plain(results), "figures": figures, **outputs(out_dir)}


def make_small_session(target):
    """Copy the first frames of the first recordings of sample_data to `target`."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAMPLE_DATA / ".settings.txt", target / ".settings.txt")
    recordings = sorted(d for d in SAMPLE_DATA.iterdir() if d.is_dir())[:SMALL_RECORDINGS]
    for recording in recordings:
        (target / recording.name).mkdir()
        for frame in sorted(recording.glob("*.bmp"))[:SMALL_FRAMES]:
            shutil.copy2(frame, target / recording.name / frame.name)
    return target


def run_cli(args, replacements):
    """Run main.py with `args`; what it printed, with each key of `replacements`
    (a path that changes from run to run) replaced by its value."""
    completed = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    text = completed.stdout
    for path, name in replacements.items():
        text = text.replace(str(path), name)
    return text


def load(name):
    return json.loads((REFERENCE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def save(name, data):
    REFERENCE_DIR.mkdir(exist_ok=True)
    (REFERENCE_DIR / f"{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


def differences(expected, actual, path="", limit=10):
    """Where two snapshots differ, as readable lines (at most `limit`). Numbers
    must be exactly equal; NaN equals NaN."""
    found = []

    def walk(a, b, where):
        if len(found) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b), key=str):
                if key not in a or key not in b:
                    found.append(f"{where}/{key}: only in {'actual' if key in b else 'expected'}")
                else:
                    walk(a[key], b[key], f"{where}/{key}")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                found.append(f"{where}: length {len(a)} expected, {len(b)} now")
            for index, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f"{where}[{index}]")
        elif isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return
        elif a != b:
            found.append(f"{where}: {a!r} expected, {b!r} now")
        elif type(a) is not type(b) and (
            isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float))
        ):
            found.append(f"{where}: {type(a).__name__} expected, {type(b).__name__} now")

    walk(expected, actual, path)
    return found
