"""Where everything is kept: the app's folders, the names of the files it keeps
in them, and the folder of each recording's results.

    recordings/<name>/         a recording session (live test runs, folders dropped
                               into the page): its frames, labels, ground truth and
                               poke test (scores/ caches the scores calibration
                               reports computed)
    results/<name>/            the last analysis of <name>: workbook, figures (clips/
                               is a cache, kept/ the scores, to save scoring the same
                               recordings again); calibration/ its calibration session
                               and report
    results/pooled/            calibration reports pooled over several recordings
    results/scripts/           what the scripts in scripts/ write
"""

import itertools
import shutil
from datetime import datetime
from pathlib import Path

import reporting
from classes import settings_file
from classes.files import remove_tree


# With two zones per plate these are labels_2.json and controls_2.json: a zone id
# is another plate there.
LABELS_FILENAME = "labels.json"
CONTROLS_FILENAME = "controls.json"  # the zones ticked as negative controls
GROUND_TRUTH_FILENAME = "ground_truth.json"
POKE_FILENAME = "poke_test.json"  # which mites answered a poke, round by round
SETTINGS_FILENAME = settings_file.FILENAME  # the recordings' Discobox settings, with the app's own lines
PREVIEW_NAME = "preview.jpg"
CALIBRATION_SESSION_NAME = "calibration_session.json"
CLIPS_DIRNAME = "clips"  # in a results folder: the frames the pages play, remade when missing
SCORES_DIRNAME = "scores"  # in a recording folder: the scores calibration reports computed
RUN_INFO_NAME = "run.json"  # in a live run's folder: how the run was made, and how far it got
# In a live run's folder: the frame mites were added on, from_<recording>.jpg, the
# recording they were added in (live_add_mites(), preview_images.added_previews()).
ADDED_FRAMES_DIRNAME = "added_frames"

# The app's folders, one for each kind of file it keeps:
APP_DIR = Path(__file__).resolve().parent.parent
# The frames: one folder per recording session, live test runs and folders dropped
# into the page alike.
RECORDINGS_ROOT = APP_DIR / "recordings"
# results/<recording>/: the last analysis of that recording.
RESULTS_ROOT = APP_DIR / "results"
# results/<recording>/calibration/: its calibration session and report.
CALIBRATION_DIRNAME = "calibration"
# results/pooled/<date time>/: a calibration report pooled over several recordings.
POOLED_DIRNAME = "pooled"
# results/scripts/: what the scripts write (classes and tables, optuna studies).
SCRIPTS_OUTPUT_DIRNAME = "scripts"
SCRIPTS_OUTPUT = RESULTS_ROOT / SCRIPTS_OUTPUT_DIRNAME
# The workbook of a calibration report, in the folder of the session that made it.
CALIBRATION_REPORT_NAME = reporting.CALIBRATION_EXCEL_NAME


def folder_name(path):
    return Path(path).resolve().name or "recording"


def results_dir(data_dir, results_root=RESULTS_ROOT):
    """Where the analysis of a recording folder goes: results/<its name>/. Analysing
    it again replaces what is there."""
    return Path(results_root) / folder_name(data_dir)


def calibration_dir(data_dir, results_root=RESULTS_ROOT):
    """Where a calibration session of a recording folder works, and its report
    goes: results/<its name>/calibration/. Two sessions of one recording share
    it, and so what is being entered on its ground-truth page."""
    folder = results_dir(data_dir, results_root) / CALIBRATION_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def new_pooled_report_dir(results_root=RESULTS_ROOT):
    """A new folder for a calibration report pooled over several recordings,
    named by when it began, e.g. results/pooled/2026-09-24 14-05-12/."""
    base = f"{datetime.now():%Y-%m-%d %H-%M-%S}"
    folder, number = Path(results_root) / POOLED_DIRNAME / base, 1
    while True:
        try:
            folder.mkdir(parents=True)
            return folder
        except FileExistsError:
            number += 1
            folder = Path(results_root) / POOLED_DIRNAME / f"{base} ({number})"


def clear_clips(out_dir):
    """Clips are cached by recording index: another folder of the same name, or a
    run of a name used before, must not play the old ones."""
    shutil.rmtree(Path(out_dir) / CLIPS_DIRNAME, ignore_errors=True)


def folder_key(out_dir):
    """A folder as a key of what is kept in memory for it: its full path."""
    return str(Path(out_dir).resolve())


def dataset_id(data_dir):
    """The id of the dataset of a recording folder: its name."""
    return Path(data_dir).name


def free_name(name, recordings_root, separator="-"):
    """`name`, or `name-2`, `name-3`... (`separator` before the number): the
    first not taken in `recordings_root`."""
    candidates = itertools.chain([name], (f"{name}{separator}{number}" for number in itertools.count(2)))
    return next(candidate for candidate in candidates if not (Path(recordings_root) / candidate).exists())


def remove_empty_pooled_reports(results_root=RESULTS_ROOT):
    """Remove the folders of pooled calibration reports that made no report: a
    pooled report's folder is only of use for its report. Run when the app starts."""
    pooled = Path(results_root) / POOLED_DIRNAME
    for folder in sorted(pooled.iterdir()) if pooled.is_dir() else []:
        if folder.is_dir() and not any(folder.glob("*.xlsx")):
            remove_tree(folder, ignore_errors=True)
