"""The files of a run's results: the workbook, the figures and the annotated
first frame (classes/results/reporting.py). They take longer to write than the results to work
out, so after a correction they are written in the background a moment later
(classes/storage/deferred_files.py); a download waits for them.
"""

import threading
from pathlib import Path

import cv2

from classes.results import reporting
from classes.storage.deferred_files import DeferredFiles
from pipeline import paths, run_settings, scoring


# The files a page need not wait for, written in the background once things are
# quiet (classes/storage/deferred_files.py): the workbook and the figures after a page's
# run and after every call corrected by hand, and a calibration report's workbook.
files_later = DeferredFiles()

# One at a time: matplotlib's figures are not made for two threads at once.
_files_lock = threading.Lock()


def annotated(run):
    """The first frame of a run with its zones and mites drawn on it."""
    return run.zone_manager.draw(cv2.cvtColor(run.masked, cv2.COLOR_GRAY2BGR))  # the frames are grey, the zones drawn in colour


def write_files(annotated, out_dir, mite_data, run, normalizer):
    """Write the workbook, the figures and the annotated first frame of a run to
    `out_dir` (reporting.write_outputs()), with run_settings.json, how the app
    was set for it (`normalizer`: the ScoreNormalizer of `mite_data`), and say
    what was written."""
    with _files_lock:
        settings = run_settings.write(run, out_dir, normalizer, mite_data)
        return reporting.write_outputs(mite_data, annotated, out_dir, settings)


def write_files_later(run, out_dir, corrections, normalizer, delay=None):
    """Write the files of a folder's run in the background (see files_later),
    from the table as the corrections are when they are written."""
    files_later.later(paths.folder_key(out_dir),
                      lambda: write_files(annotated(run), out_dir, scoring.mite_table(run, corrections, normalizer)[0], run,
                                          normalizer),
                      delay)


def finish_files(out_dir=None):
    """Return once the files of the results in `out_dir` (by default of all
    results) are as the last call corrected by hand makes them: before one is
    downloaded, and before the program ends."""
    files_later.finish(None if out_dir is None else paths.folder_key(out_dir))


def results_file(out_dir, name):
    """The path of the file `name` of the results in `out_dir`, written as the
    last correction makes it if it is one of those. A clip's frames wait for
    nothing."""
    if name in (reporting.EXCEL_NAME, reporting.DETECTIONS_NAME, reporting.CALIBRATION_EXCEL_NAME,
                *(figure for figure, _method in reporting.FIGURES)):
        finish_files(out_dir)
    return Path(out_dir) / name
