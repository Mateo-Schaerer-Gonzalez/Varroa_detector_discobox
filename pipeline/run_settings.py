"""run_settings.json in a run's results: every parameter that made them, so the
results can be published with how the app was set and made again. Written
with the workbook every time (output_files.write_files()).

    software     the code (git commit, files changed but not committed) and
                 Python, OpenCV, numpy, pandas, the operating system, the machine
    in_use       the values that decide the calls, together: metric, its
                 parameters, threshold, review band, normalisations, death rule
    config       the whole configuration as the run used it (config.yaml, with
                 what classes/app_config.py forces or takes from config.default.yaml)
    constants    every named constant (an upper-case name, at the top of a
                 module or a class) of every module of classes/ and pipeline/
                 the process has loaded, with its value: collected, not listed,
                 so a new one is in it without being added here
    recordings   what is kept next to the recordings and changes the results:
                 .settings.txt, run.json of a live run, the negative controls,
                 the calls corrected by hand
    zones        the plates' rectangles in image pixels (coords_pixel.txt or
                 coords_pixel_2.txt) and the group the results give each

A number written inside a function, not named, is fixed by the commit.
"""

import ast
import dataclasses
import platform
import re
import subprocess
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from classes.scoring.analyzer import Analyzer
from classes.results.call_corrections import CallCorrections
from classes.storage import settings_file
from classes.storage.files import try_json, write_json
from pipeline import paths, plate_zones

NAME = "run_settings.json"
_PACKAGES = ("classes", "pipeline")
_CONSTANT = re.compile(r"_?[A-Z][A-Z0-9_]*")


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


def software():
    return {
        "commit": COMMIT,
        "uncommitted_changes": CHANGED,
        "python": sys.version.split()[0],
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "system": platform.platform(),
        "machine": platform.node(),
    }


def in_use(mite, normalizer, data_dir):
    """The values that decide the calls, as the run used them."""
    return {
        "metric": mite.metric,
        # its defaults (classes/scoring/analyzer.py) with config.default.yaml's over them
        "params": Analyzer.check_metric_params(mite.metric, mite.params_for(mite.metric)),
        "threshold": float(mite.motion_threshold),
        "review_band": list(mite.review_band_for(mite.metric) or []) or None,
        "stabilize_plate": bool(mite.stabilize_plate),
        "normalize_floor": bool(normalizer is not None and normalizer.floor),
        "normalize_brightness": bool(normalizer is not None and normalizer.brightness),
        # as run_results.death_minutes() reads it (0: dead from the last movement on)
        "death_minutes": None if data_dir is None else settings_file.whole_number(data_dir, "death_minutes", 0),
        "zones_per_plate": None if data_dir is None else plate_zones.zones_per_plate(data_dir),
    }


def config(app_config):
    """Every section of the configuration, as loaded."""
    return {
        "file": app_config.config_path.name,
        "mite": dataclasses.asdict(app_config.mite),
        "detector": dataclasses.asdict(app_config.detector),
        "label_reader": dataclasses.asdict(app_config.label_reader),
        "drawing": {"rect": dataclasses.asdict(app_config.rect_style),
                    "text_zone": dataclasses.asdict(app_config.text_zone_style),
                    **{name: dataclasses.asdict(style) for name, style in app_config.zone_styles.items()}},
    }


_SKIP = object()


def _plain(value):
    """`value` as JSON, or _SKIP for what is no parameter (a function, a class, a path...)."""
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list, set, frozenset)):
        items = [_plain(item) for item in (sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value)]
        return _SKIP if any(item is _SKIP for item in items) else items
    if isinstance(value, dict):
        items = {str(key): _plain(item) for key, item in value.items()}
        return _SKIP if any(item is _SKIP for item in items.values()) else items
    return _SKIP


def _assigned(body):
    """The upper-case names assigned in `body` (a module's or a class's statements)."""
    for node in body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            for name in ([target] if isinstance(target, ast.Name) else getattr(target, "elts", [])):
                if isinstance(name, ast.Name) and _CONSTANT.fullmatch(name.id):
                    yield name.id


@lru_cache(maxsize=None)
def _names(file):
    """(owner, name) of the constants defined in the source `file`: owner None
    at the top of the module, else the class's name. Imported names are not its own."""
    tree = ast.parse(Path(file).read_text(encoding="utf-8"))
    names = [(None, name) for name in _assigned(tree.body)]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names += [(node.name, name) for name in _assigned(node.body)]
    return tuple(names)


def constants():
    """{module: {name or Class.name: value}} of the modules of classes/ and
    pipeline/ loaded, their values as they are now."""
    found = {}
    for module_name, module in sorted(sys.modules.copy().items()):  # copied at once: another thread may import
        if (module_name.split(".")[0] not in _PACKAGES or module_name == __name__  # its commit is in software()
                or not getattr(module, "__file__", None)):
            continue
        values = {}
        for owner, name in _names(module.__file__):
            holder = module if owner is None else getattr(module, owner, None)
            value = _plain(getattr(holder, name, _SKIP))
            if value is not _SKIP:
                values[name if owner is None else f"{owner}.{name}"] = value
        if values:
            found[module_name] = values
    return found


def recordings(data_dir):
    """What is kept next to the recordings and changes the results."""
    if data_dir is None:
        return {}
    data_dir = Path(data_dir)
    return {
        "folder": data_dir.name,
        "settings": settings_file.of_folder(data_dir),
        "run": try_json(data_dir / paths.RUN_INFO_NAME),
        "controls": try_json(plate_zones.layout_file(data_dir, paths.CONTROLS_FILENAME)),
        "corrections": try_json(data_dir / CallCorrections.FILENAME),
    }


def zones(zone_manager, mite_data):
    """The plates in reading order, each with its rectangle and the group the
    results give its mites ("" for a plate without mites)."""
    groups = {str(zone): "" if pd.isna(group) else str(group)
              for zone, group in mite_data[["zone_id", "group"]].drop_duplicates().itertuples(index=False)}
    return [{**zone, "label": groups.get(str(zone["id"]), "")}
            for zone in plate_zones.describe_zones(zone_manager, None)]


def describe(run, normalizer, mite_data):
    data_dir = getattr(run, "data_dir", None)
    return {
        "written": datetime.now().isoformat(timespec="seconds"),
        "software": software(),
        "in_use": in_use(run.analyzer.config.mite, normalizer, data_dir),
        "n_recordings": run.n_recordings,
        "n_mites": len(run.zone_manager.mites),
        "frames": run.frames,
        "zones": zones(run.zone_manager, mite_data),
        "recordings": recordings(data_dir),
        "config": config(run.analyzer.config),
        "constants": constants(),
    }


def write(run, out_dir, normalizer, mite_data):
    """Write run_settings.json to `out_dir`, and return what it holds (also the
    workbook's settings sheet)."""
    settings = describe(run, normalizer, mite_data)
    write_json(Path(out_dir) / NAME, settings, indent=2)
    return settings
