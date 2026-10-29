"""run_settings.json in a run's results: the settings the recordings were made
and analysed with, so the results can be published with them and made again.
Written with the workbook every time (output_files.write_files()), which shows
the same in its settings sheet.

    code         git commit, files changed but not committed, Python and OpenCV
    recording    how the recordings were made (their .settings.txt): number,
                 interval, frames, frame rate, fan and LEDs, following (live)
    detector     how the mites were found on the first frame (config's detector)
    analysis     how each recording was scored and called: metric, its
                 parameters and constants, stabilizer, threshold, death rule,
                 zones per plate, mites whose calls were corrected by hand

A number inside the code that is not here is fixed by the commit.
"""

import dataclasses
import platform
import subprocess
from datetime import datetime
from pathlib import Path

import cv2

from classes.results.call_corrections import CallCorrections
from classes.scoring import analyzer, plate_stabilizer
from classes.scoring.analyzer import Analyzer
from classes.storage import settings_file
from classes.storage.files import write_json
from pipeline import paths, plate_zones

NAME = "run_settings.json"
# The lines of .settings.txt that say how the recordings were made.
RECORDING_KEYS = ("recording_count", "run_minutes", "recording_timeout", "frame_count", "fps",
                  "vent_time", "vent", "led1_time", "led1", "led2_time", "led2", "follow_px")


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=paths.APP_DIR, capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# Read once: the code this process runs, even if the folder is updated meanwhile.
COMMIT = _git("rev-parse", "HEAD")
# Files in git changed but not committed (config.yaml is not in git): the commit alone does not make the results again.
CHANGED = _git("status", "--porcelain", "--untracked-files=no").splitlines()


def code():
    return {"commit": COMMIT, "uncommitted_changes": CHANGED, "python": platform.python_version(),
            "opencv": cv2.__version__, "system": platform.system()}


def recording(run, data_dir):
    saved = settings_file.of_folder(data_dir) if data_dir is not None else {}
    return {"recordings": run.n_recordings, **{key: saved[key] for key in RECORDING_KEYS if key in saved}}


def analysis(mite, normalizer, data_dir):
    """How each recording was scored and called, as the run did it."""
    return {
        "metric": mite.metric,
        # its defaults (classes/scoring/analyzer.py) with config.default.yaml's over
        # them: for outline_variability metric_width (the band round the outline,
        # px either way) and metric_pad (px of plate round the mite's box)
        **{f"metric_{name}": value
           for name, value in Analyzer.check_metric_params(mite.metric, mite.params_for(mite.metric)).items()},
        "threshold": float(mite.motion_threshold),
        "mite_radius_px": mite.radius,
        "outline_rim_px": analyzer.RIM,
        "body_share": analyzer.BODY_SHARE,
        "body_grow_px": analyzer.BODY_GROW,
        "edge_share": analyzer.EDGE_SHARE,
        "edge_darkest_n": analyzer.EDGE_DARKEST_N,
        "rays": analyzer.ANGLES,
        "ray_step_px": analyzer.RAY_STEP,
        "ray_reach_px": analyzer.REACH,
        "stabilize_plate": bool(mite.stabilize_plate),
        "stabilizer_pad_px": plate_stabilizer.PAD,
        "stabilizer_rim_px": plate_stabilizer._RIM,
        "stabilizer_darkest_n": plate_stabilizer.DARKEST_N,
        "stabilizer_body_share": plate_stabilizer.BODY_SHARE,
        "stabilizer_body_grow_px": plate_stabilizer.BODY_GROW,
        "stabilizer_margin_px": plate_stabilizer.MARGIN,
        "stabilizer_interpolation": {cv2.INTER_LINEAR: "bilinear", cv2.INTER_LANCZOS4: "lanczos"}.get(
            plate_stabilizer.INTERPOLATION, str(plate_stabilizer.INTERPOLATION)),
        "normalize_floor": bool(normalizer is not None and normalizer.floor),
        "normalize_brightness": bool(normalizer is not None and normalizer.brightness),
        # as run_results.death_minutes() reads it (0: dead from the last movement on)
        "death_minutes": None if data_dir is None else settings_file.whole_number(data_dir, "death_minutes", 0),
        "zones_per_plate": None if data_dir is None else plate_zones.zones_per_plate(data_dir),
        "mites_corrected_by_hand": 0 if data_dir is None else len(CallCorrections(data_dir).entries()),
    }


def describe(run, normalizer):
    data_dir = getattr(run, "data_dir", None)
    config = run.analyzer.config
    return {
        "written": datetime.now().isoformat(timespec="seconds"),
        "code": code(),
        "recording": recording(run, data_dir),
        "detector": dataclasses.asdict(config.detector),
        "analysis": analysis(config.mite, normalizer, data_dir),
    }


def write(run, out_dir, normalizer):
    """Write run_settings.json to `out_dir`, and return what it holds (also the
    workbook's settings sheet)."""
    settings = describe(run, normalizer)
    write_json(Path(out_dir) / NAME, settings, indent=2)
    return settings
