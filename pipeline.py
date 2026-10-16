"""The analysis, as a handful of functions.

This is the only module the user interface is allowed to call, and it knows nothing
about HTTP, sessions or browsers. Everything crossing this boundary is a plain dict,
list, string or number -- never a Zone, Mite, DataFrame or image array -- so the UI
can never reach into the analysis internals.

    open_session(...)          cheap: the zones to label, their mites and a preview image
    save_zones_per_plate(...)  cut each plate into one zone or two, for this recording from now on
    set_rejected(...)          mark a detection as not a mite, or take the mark back
    mark_detection(...)        the same from the label page, which it tells how many mites each zone has left
    read_labels(...)           read the names written beside the plates (Google Gemini), to fill in
    save_label_reading(...)    whether the label page reads them: its box, saved in config.yaml
    run_analysis(...)          the full pipeline, writing Excel and figures to out_dir
    correct_call(...)          change one mite's call in one recording by hand, or mark it gone; the results follow
    save_review_band(...)      the band around the threshold whose calls are checked by eye, into config.yaml
    review_again(...)          the results of a folder's last run again, with the band as it is now
    analysis_clip(...)         frames of one recording, of one zone or the whole plate
    describe_movement(...)     each mite's, zone's and group's movement numbers, for the pages
    describe_survival(...)     the mites alive over time and the log-rank tests against the
                               negative controls, for results and a time to count a mite dead

    open_calibration(...)      detect and score the mites of a calibration session
    calibration_clip(...)      frames of one zone in one recording, to judge by eye
    save_ground_truth(...)     store which mites the user saw moving in each recording
    truth_view(...)            the ground truth being entered, as saved with the changes not saved yet
    edit_truth(...)            a click or a fill button on the ground-truth page, not saved yet
    save_truth(...)            save the changes made on the ground-truth page
    poke_view(...)             the poke test of a calibration session, round by round
    edit_poke(...)             a change on the poke-test page, saved at once
    list_calibration_datasets(...)   the recordings with ground truth saved
    open_saved_calibration(...)      reopen one to go on labelling it
    delete_calibration_dataset(...)  delete the ground truth of a recording
    dataset_preview(...)             the first frame of a recording
    dataset_clip(...)                frames of the whole plate in one recording of a saved dataset
    movement_scores()          the metrics a calibration can score with, and their parameters
    evaluate_calibration(...)  score the saved mites with a metric (the one in config.yaml
                               unless another is given), then confusion matrix, ROC, best
                               threshold against the labels, pooled over any saved datasets
    save_threshold(...)        write a new movement threshold into config.yaml
    save_movement_score(...)   write a metric, its parameters and its threshold into config.yaml

    live_options()             the cameras, serial ports and saved test-run settings
    save_live_settings(...)    change the test-run settings (and the camera's frame rate)
    live_plan(...)             how long a test run with some settings takes, and its recordings
    open_live(...)             open the camera for a live run
    set_live_options(...)      rename a live run not started yet, or choose whether it is saved
    live_preview(...)          detect the mites on the newest frame, to label the plates
    live_read_labels(...)      read_labels() for a live run
    set_live_light(...)        switch the fan, or set an intensity, to check the settings
    start_live(...)            start the test run; it is analysed as it is captured
    live_status(...)           how capture and analysis are going
    live_results(...)          the results so far, as run_analysis() gives them
    live_correct_call(...)     correct_call() for a live run
    live_frame(...)            the newest frame as a JPEG, for the live feed
    pause_live / resume_live / stop_live / close_live

    list_recordings()          every recording kept in recordings/, with how it was recorded
    plan_upload(...)           which files of a folder dropped into the page to copy, and where
    results_dir(...)           where the analysis of a folder goes: results/<its name>/
    calibration_folder(...)    the folder in recordings/ a calibration works on (one elsewhere is copied in)
    calibration_dir(...)       where a calibration session of a recording works: results/<name>/calibration/
    new_pooled_report_dir()    a folder for a report pooled over several recordings
    tidy_folders()             move what earlier versions wrote into today's folders

Where things go:

    recordings/<name>/         a recording session (live test runs, folders dropped into the page):
                               its frames, labels, ground truth and poke test (scores/ caches the
                               scores calibration reports computed)
    results/<name>/            the last analysis of <name>: workbook, figures (clips/ is a cache,
                               kept/ the scores, to save scoring the same recordings again);
                               calibration/ its calibration session and report
    results/pooled/            calibration reports pooled over several recordings
    results/scripts/           what the scripts in scripts/ write
"""

import hashlib
import inspect
import itertools
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import cv2
import numpy as np

import reporting
from classes import calibration
from classes import death_calibration
from classes.analyzer import Analyzer
from classes import benchmark as benchmark_module
from classes.benchmark import Benchmark
from classes.call_corrections import CallCorrections
from classes import app_config
from classes.app_config import get_default_config, save_motion_threshold
from classes import plate_stabilizer
from classes.plate_stabilizer import PlateStabilizer
from classes.poke_test import PokeSurvival, PokeTest
from classes.data_loader import DataLoader
from classes.deferred_files import DeferredFiles
from classes.error_map import ErrorMap
from classes.frame_source import RoiSource, open_source
from classes.kept_scores import KeptScores
from classes.label_reader import LabelReader, LabelReadError
from classes.live import camera as live_camera
from classes.live.lights import DEVICES, open_lights, serial_ports
from classes.live.progress import RunProgress
from classes.live.recorder import Recorder
from classes.live.session import LiveSession
from classes.live.settings import RANGES as SETTING_RANGES, Settings
from classes.live.sources import CameraSource
from classes.mite import Mite
from classes.motion_analysis import MotionAnalysis, detect_mites
from classes.outline_view import OutlineView
from classes.movement_stats import MovementReport
from classes.recording_info import RecordingInfo
from classes.roi_conversion import RoiConversion
from classes.roi_recordings import ROI_DIRNAME, RoiRecordings, RoiVideo, is_roi_session, open_recordings, remove_tree
from classes.review_band import ReviewBand
from classes.score_normalizer import ScoreNormalizer
from classes.survival import SurvivalAnalysis, SurvivalReport
from classes.truth_draft import TruthDraft
from classes.truth_overlap import TruthOverlap
from classes.unusual_activity import UnusualActivity
from classes.upload_plan import UploadPlan
from classes.workers import one_ahead, side_by_side
from classes.zone_layout import ZoneLayout
from classes.zones import UNLABELED, ZoneManager

_logger = logging.getLogger(__name__)

# Zone type ids as they appear in the coordinates file.
ZONE_TYPES = {"0": "label", "1": "mite"}
EXCLUDED_TYPES = ["label"]

# One zone per plate. Which file a recording uses is saved with it (classes/zone_layout.py).
DEFAULT_COORDS_FILE = "coords_pixel.txt"
# With two zones per plate these are labels_2.json and controls_2.json: a zone id
# is another plate there.
LABELS_FILENAME = "labels.json"
CONTROLS_FILENAME = "controls.json"  # the zones ticked as negative controls
GROUND_TRUTH_FILENAME = "ground_truth.json"
POKE_FILENAME = "poke_test.json"  # which mites answered a poke, round by round
PREVIEW_NAME = "preview.jpg"
CALIBRATION_SESSION_NAME = "calibration_session.json"
CLIPS_DIRNAME = "clips"  # in a results folder: the frames the pages play, remade when missing

# The app's folders, one for each kind of file it keeps:
APP_DIR = Path(__file__).resolve().parent
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
# Pixels read around the mites when the plate is stabilized: the shift measure
# looks 8 past each box, and the shake plus Lanczos reach a few more.
STABILIZE_MARGIN = 16
DATASET_NAME = "dataset.json"
SCORES_DIRNAME = "scores"
RECORDINGS_DIRNAME = "recordings"


def _build_zone_manager(coords_file):
    return ZoneManager.from_coords_file(
        filepath=coords_file,
        zone_types=ZONE_TYPES,
        excluded_types=EXCLUDED_TYPES,
    )


def _coords_file(data_dir, coords_file=None):
    """The zones of the recordings in `data_dir`: those of the layout saved with
    them, unless a `coords_file` is given."""
    return coords_file or ZoneLayout.of_folder(data_dir).coords_file


def zones_per_plate(data_dir):
    """How many zones each plate of the recordings in `data_dir` is cut into."""
    return ZoneLayout.of_folder(data_dir).zones_per_plate


def save_zones_per_plate(data_dir, out_dir, zones):
    """Cut each plate of the recordings in `data_dir` into `zones` zones (1 or 2),
    for this and every later analysis of them: saved in their .settings.txt.
    Returns the session as open_session() does, with the new zones and the mites
    found in them. The last run of `out_dir` is of the other zones, so its calls
    can no longer be corrected; run the analysis again."""
    ZoneLayout(zones).save(data_dir)
    with _runs_lock:
        _runs.pop(_draft_key(out_dir), None)
    return open_session(data_dir, out_dir)


def _layout_file(data_dir, name):
    return Path(data_dir) / ZoneLayout.of_folder(data_dir).filename(name)


def _describe_zones(zone_manager, labels):
    """The plates in reading order, as plain rectangles in image pixels."""
    labels = {str(key): value for key, value in (labels or {}).items()}

    def text_zone(zone):
        # Where the plate's name is shown: its printed-label area, if it has one.
        area = zone_manager.text_zone_for(zone)
        return None if area is None else {"x1": area.x1, "y1": area.y1, "x2": area.x2, "y2": area.y2}

    return [
        {
            "id": zone.id,
            "x1": zone.x1,
            "y1": zone.y1,
            "x2": zone.x2,
            "y2": zone.y2,
            "text_zone": text_zone(zone),
            "label": labels.get(str(zone.id), ""),
        }
        for zone in zone_manager.labelled_zones
    ]


def load_labels(data_dir):
    """Read previously saved zone labels for this recording session, if any."""
    path = _layout_file(data_dir, LABELS_FILENAME)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_labels(data_dir, labels):
    """Store zone labels next to the recordings so they survive a restart."""
    path = _layout_file(data_dir, LABELS_FILENAME)
    path.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    return str(path)


def label_reading():
    """Whether the names written beside the plates can be read (it takes a Google
    Gemini API key, see classes/label_reader.py), and whether the label page
    does so: its box, off until ticked (save_label_reading)."""
    return {"available": LabelReader.saved_key() is not None, "enabled": bool(get_default_config().label_reader.enabled)}


def save_label_reading(enabled):
    """Read the names from the plates from now on, or stop: the tick of the label
    page's box, saved in config.yaml."""
    app_config.save_label_reading(bool(enabled))
    return label_reading()


def read_labels(data_dir, out_dir, mites, coords_file=None):
    """Read the names written by hand beside the plates of the recordings in
    `data_dir`, on the preview picture in `out_dir`: {zone id (a string): name},
    for the zones with a detection among the label page's `mites` and no name
    saved yet, where something is written. Nothing is saved: the page fills them
    in for the user to check. Raises LabelReadError without a key or the internet."""
    return _read_labels(_build_zone_manager(_coords_file(data_dir, coords_file)), data_dir, out_dir, mites)


def _read_labels(zone_manager, data_dir, out_dir, mites):
    frame = cv2.imread(str(Path(out_dir) / PREVIEW_NAME))
    if frame is None:
        raise FileNotFoundError("There is no picture of the plates to read the names from; open the folder again.")
    saved = {str(key): str(value).strip() for key, value in load_labels(data_dir).items()}
    with_mites = {mite["zone_id"] for mite in mites}
    areas = {}  # a label area and the zones it names: the two halves of a plate share one
    for zone in zone_manager.labelled_zones:
        area = zone_manager.text_zone_for(zone)
        if zone.id in with_mites and not saved.get(str(zone.id)) and area is not None:
            areas.setdefault(id(area), (area, []))[1].append(zone.id)
    if not areas:
        return {}
    reader = LabelReader(model=get_default_config().label_reader.model)
    names = reader.read(frame, [area for area, _zones in areas.values()], sorted(set(filter(None, saved.values()))))
    return {str(zone_id): name for (_area, zone_ids), name in zip(areas.values(), names) if name for zone_id in zone_ids}


def load_controls(data_dir):
    """The ids of the zones ticked as negative controls, which the survival of
    every other zone is compared with; none if nothing was ticked."""
    ids = _read_json(_layout_file(data_dir, CONTROLS_FILENAME), [])
    return sorted({i for i in ids if isinstance(i, int)}) if isinstance(ids, list) else []


def save_controls(data_dir, controls):
    """Store the negative-control zones next to the recordings, beside the labels."""
    ids = sorted({int(i) for i in controls})
    _layout_file(data_dir, CONTROLS_FILENAME).write_text(json.dumps(ids), encoding="utf-8")
    return ids


def _folder_name(path):
    return Path(path).resolve().name or "recording"


def results_dir(data_dir, results_root=RESULTS_ROOT):
    """Where the analysis of a recording folder goes: results/<its name>/. Analysing
    it again replaces what is there."""
    return Path(results_root) / _folder_name(data_dir)


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


def _clear_clips(out_dir):
    """Clips are cached by recording index: another folder of the same name, or a
    run of a name used before, must not play the old ones."""
    shutil.rmtree(Path(out_dir) / CLIPS_DIRNAME, ignore_errors=True)


def open_session(data_dir, out_dir, coords_file=None):
    """Describe a recording session so its zones can be labelled.

    Decodes a single frame, writes it to `out_dir` as a JPEG, and returns the zone
    rectangles in image pixel coordinates, each with the number of mites detected
    in it -- detection only needs that first frame, so the UI can offer only the
    zones with mites for labelling. Drawing is left to the caller: the UI gets
    numbers, not a picture with boxes burnt into it. The zones are those of the
    layout saved with the recordings (one or two per plate), unless a
    `coords_file` is given.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_clips(out_dir)

    loader = open_recordings(data_dir)
    n_recordings = loader.count_recordings()
    if n_recordings == 0:
        raise FileNotFoundError(f"No recordings found in {data_dir}")

    frame = loader.load_preview_frame()
    _write_preview(frame, out_dir)

    zone_manager = _build_zone_manager(_coords_file(data_dir, coords_file))
    # The same detection as an analysis run, on the same first frame.
    detect_mites(zone_manager, frame, Analyzer(), getattr(loader, "boxes", None))
    return _session_view(zone_manager, frame, data_dir, n_recordings)


def _session_view(zone_manager, frame, data_dir, n_recordings):
    """What the labelling page needs: the zones, with their labels and number of
    mites, and every detection, those marked "not a mite" included."""
    # Rejected detections are listed too, marked, so the user can take a mark back.
    rejected = set(map(id, _rejected_detections(zone_manager, _folder_truth(data_dir))))
    mites = [
        {
            "id": mite.text,
            "zone_id": zone.id,
            "x": round(float((mite.x1 + mite.x2) / 2), 1),
            "y": round(float((mite.y1 + mite.y2) / 2), 1),
            "r": round(float((mite.x2 - mite.x1) / 2), 1),
            "rejected": id(mite) in rejected,
        }
        for zone in zone_manager.zones
        for mite in zone.mites
    ]

    zones = _describe_zones(zone_manager, load_labels(data_dir))
    controls = set(load_controls(data_dir))
    for zone in zones:
        zone["control"] = zone["id"] in controls
        zone["n_mites"] = sum(1 for m in mites if m["zone_id"] == zone["id"] and not m["rejected"])
    return {
        "data_dir": str(data_dir),
        "preview": PREVIEW_NAME,
        "image": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
        "n_recordings": n_recordings,
        "zones_per_plate": zones_per_plate(data_dir),
        "zone_layouts": ZoneLayout.choices(),
        "label_reading": label_reading(),
        "zones": zones,
        "mites": mites,
    }


def set_rejected(data_dir, x, y, rejected, restore=None, tolerance=10.0):
    """Mark the detection at (x, y) as not a mite, or take that mark back.

    The mark goes into the session's ground truth, where an analysis run and a
    calibration both read it. Marking replaces any movement labels a calibration
    gave the detection and returns them (None if it had none). Taking the mark
    back puts back the labels passed as `restore`, so a detection marked by
    mistake and unmarked keeps its labels; without them it is left unlabelled.
    """
    data_dir = Path(data_dir)
    saved = _folder_truth(data_dir)
    near = [entry for entry in saved if np.hypot(entry["x"] - x, entry["y"] - y) <= tolerance]
    # a detection matches only the nearest saved entry
    nearest = min(near, key=lambda entry: np.hypot(entry["x"] - x, entry["y"] - y), default=None)

    replaced = None
    if rejected:
        # One entry per detection: a position already in the ground truth is overwritten.
        if nearest is None:
            saved.append({"x": x, "y": y, "truth": calibration.NOT_A_MITE})
        else:
            if not calibration.is_rejected(nearest.get("truth")):
                replaced = nearest.get("truth")
            nearest["truth"] = calibration.NOT_A_MITE
    else:
        for entry in near:
            truth = entry.get("truth")
            if entry is nearest and restore is not None and calibration.is_rejected(truth):
                entry["truth"] = restore
            elif isinstance(truth, list):
                entry["truth"] = [None if state == calibration.NOT_A_MITE else state for state in truth]
            elif truth == calibration.NOT_A_MITE:
                entry["truth"] = None
        saved = [entry for entry in saved if any(entry["truth"] if isinstance(entry.get("truth"), list) else [entry.get("truth")])]

    (data_dir / GROUND_TRUTH_FILENAME).write_text(json.dumps(saved), encoding="utf-8")
    return replaced


# What a "not a mite" mark made from the label page replaced, by folder and
# position, so taking the mark back puts the labels back.
_replaced = {}


def mark_detection(data_dir, mites, mite_id, rejected):
    """Mark the detection `mite_id` of the label page's `mites` ([{id, zone_id, x,
    y}], as open_session() or live_preview() listed them) as not a mite, or take
    the mark back, as set_rejected() does. What a mark replaced is remembered and
    put back when the mark is taken back, so a click by mistake loses nothing.
    Returns the marks now: {mites: {id: rejected}, zones: {zone id: mites left}}."""
    mite = next((m for m in mites if m["id"] == str(mite_id)), None)
    if mite is None:
        raise ValueError(f"No detection {mite_id} in this session.")
    key = (_draft_key(data_dir), mite["x"], mite["y"])
    restore = None if rejected else _replaced.pop(key, None)
    replaced = set_rejected(data_dir, mite["x"], mite["y"], rejected, restore)
    if rejected:
        _replaced[key] = replaced
    return detection_marks(data_dir, mites)


def detection_marks(data_dir, mites):
    """Which of the label page's `mites` are marked "not a mite" in the ground
    truth saved for `data_dir`, and how many mites each zone has left."""
    rejected = [entry for entry in _folder_truth(data_dir) if calibration.is_rejected(entry.get("truth"))]
    positions = [{"id": m["id"], "x": m["x"], "y": m["y"]} for m in mites]
    matched = calibration.match_ground_truth(positions, rejected, n_recordings=1) if rejected else {}
    marks = {m["id"]: m["id"] in matched for m in mites}
    zones = {}
    for m in mites:
        zones[m["zone_id"]] = zones.get(m["zone_id"], 0) + (not marks[m["id"]])
    return {"mites": marks, "zones": zones}


def _detect_and_score(data_dir, coords_file, labels=None, reject=True, score=True,
                      kept_in=None, names=None):
    """Find the mites and, with `score`, decode every recording and score their motion.

    The expensive part shared by an analysis run and a calibration: the analysis
    core (classes/motion_analysis.py) fed from the folder, one recording at a time.
    With `reject`, detections marked "not a mite" in the session's ground truth
    are dropped, so they appear nowhere in the results. With `kept_in`, a folder,
    the scores are kept there, and read back instead of worked out when these
    very frames were scored there before, by this code (classes/kept_scores.py).
    With `names`, only the recordings of those names (FolderSource). A session
    saved as the mites' ROIs has its mites and blobs saved with them (RoiSource).
    """
    source = open_source(data_dir, names)
    rois = isinstance(source, RoiSource)
    analysis = MotionAnalysis(_build_zone_manager(_coords_file(data_dir, coords_file)), score=False,
                              boxes=source.boxes if rois else None, known_blobs=source.blobs() if rois else None)
    if rois and score:
        mite = analysis.analyzer.config.mite
        source.loader.check_margin(Analyzer.roi_padding(mite.metric, mite.params_for(mite.metric))
                                   + (STABILIZE_MARGIN if mite.stabilize_plate else 0))
    if not score or kept_in is not None:
        # The mites and the recordings, from the first frame and the names of
        # the others: those are counted, not decoded.
        analysis.run(source.events(decode=source.FIRST))
    if score:
        kept = key = None
        if kept_in is not None:
            kept = KeptScores(kept_in)
            key = KeptScores.key(analysis.mites, analysis.analyzer.config.mite.stabilize_plate,
                                 source.frame_files(), analysis.first_frame)
        if kept is not None and kept.give(key, analysis.mites, len(analysis.recording_times)):
            analysis.blobs = kept.blobs
        else:
            analysis.score = True
            analysis.recording_times = []
            analysis.run(source.events())
            if kept is not None:
                kept.keep(key, analysis.mites, analysis.blobs)
    _arrange(analysis, data_dir, labels, reject)
    return _run_view(analysis, "rois" if rois else "whole")


def _arrange(analysis, data_dir, labels, reject):
    """Name the zones by `labels` and, with `reject`, leave out the detections
    marked "not a mite" in the ground truth saved for `data_dir`, and the mites
    that flew off (classes/unusual_activity.py: their activity is worked out
    here, on every detection). Folder and live runs both go through here, so the
    same marks give the same results."""
    truth = _folder_truth(data_dir) if reject else []

    def left_out(zone_manager):
        rejected = _rejected_detections(zone_manager, truth)
        analysis.activity = UnusualActivity.of(analysis, rejected, _activity_reach(analysis.analyzer.config.mite))
        if not reject:
            return rejected
        flown = analysis.activity.fly_off_ids
        return [*rejected, *(mite for mite in analysis.mites if mite.text in flown and mite not in rejected)]

    analysis.arrange(labels, left_out)


def _activity_reach(mite):
    """Pixels from a mite's centre to the edge of its scored patch: a mite walking
    closer disturbs its recording (classes/unusual_activity.py)."""
    params = mite.params_for(mite.metric)
    return float(mite.radius) + Analyzer.roi_padding(mite.metric, params)


def _run_view(analysis, frames):
    """`frames`: what was saved of the recordings, for the pages: "whole"
    frames, or the mites' "rois" alone (classes/roi_recordings.py)."""
    return SimpleNamespace(
        frames=frames,
        zone_manager=analysis.zone_manager,
        analyzer=analysis.analyzer,
        first_frame=analysis.first_frame,
        masked=analysis.masked,
        n_recordings=len(analysis.recording_times),
        activity=analysis.activity,
        # One timestamp per recording, in minutes from the start of the session.
        burst_minutes=np.array(analysis.recording_times) / 60,
    )


def _image_size(frame):
    return {"width": int(frame.shape[1]), "height": int(frame.shape[0])}


def _write_preview(frame, out_dir):
    """The first frame as preview.jpg, written whole before it takes the name: a
    page may be loading the one it replaces, e.g. a live run's labels page while
    the first recording's results come in."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    partial = out_dir / f"partial_{PREVIEW_NAME}"
    _write_image(partial, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    # Windows refuses to replace a file while it is being sent; that takes moments.
    for attempt in range(20):
        try:
            partial.replace(out_dir / PREVIEW_NAME)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def run_analysis(data_dir, out_dir, labels=None, coords_file=None,
                 files_later=False):
    """Run the whole pipeline and write its results to `out_dir`.

    `labels` maps zone id (as a string) to the group name the user typed, e.g.
    {"0": "venom 2x", "1": "control"}. Each mite gets one score per recording,
    from all of its frames. Returns the output filenames, a summary, and the
    per-zone and per-mite results the UI browses.

    The scores are kept in `out_dir` (classes/kept_scores.py): a run of the same
    recordings, by the same code and settings, reads them back and is done in a
    moment. With `files_later`, the workbook and the figures are written just
    after the results are handed over, as after a correction, so a page need not
    wait for them (finish_files() does).
    """
    run = _detect_and_score(data_dir, coords_file, labels, kept_in=out_dir)
    corrections = CallCorrections(data_dir)
    normalizer = _normalizer_in_use(run.analyzer.config.mite)
    with _runs_lock:
        _runs[_draft_key(out_dir)] = (run, labels, corrections, normalizer)
    if not files_later:
        # Files of the run before still to be written are not to be written over this one's.
        _files_later.forget(_draft_key(out_dir))
        finish_files(out_dir)
        return _results(run, out_dir, labels, corrections=corrections, normalizer=normalizer)
    results = _results(run, out_dir, labels, write_files=False, corrections=corrections, normalizer=normalizer)
    _write_preview(run.first_frame, out_dir)  # the pages draw on it at once
    _write_files_later(run, out_dir, corrections, normalizer)
    return results


# The last run of each results folder, so a call corrected by hand on its result
# pages gives new results without decoding the recordings again.
_runs = {}
_runs_lock = threading.Lock()
# The files a page need not wait for, written in the background once things are
# quiet (classes/deferred_files.py): the workbook and the figures after a page's
# run and after every call corrected by hand, and a calibration report's workbook.
_files_later = DeferredFiles()

# One at a time: matplotlib's figures are not made for two threads at once.
_files_lock = threading.Lock()


def _annotated(run):
    """The first frame of a run with its zones and mites drawn on it."""
    return run.zone_manager.draw(cv2.cvtColor(run.masked, cv2.COLOR_GRAY2BGR))  # the frames are grey, the zones drawn in colour


def _write_files(annotated, out_dir, mite_data):
    """Write the workbook, the figures and the annotated first frame of a run to
    `out_dir` (reporting.write_outputs()), and say what was written."""
    with _files_lock:
        return reporting.write_outputs(mite_data, annotated, out_dir)


def _write_files_later(run, out_dir, corrections, normalizer, delay=None):
    """Write the files of a folder's run in the background (see _files_later),
    from the table as the corrections are when they are written."""
    _files_later.later(_draft_key(out_dir),
                       lambda: _write_files(_annotated(run), out_dir, _mite_table(run, corrections, normalizer)[0]),
                       delay)


def finish_files(out_dir=None):
    """Return once the files of the results in `out_dir` (by default of all
    results) are as the last call corrected by hand makes them: before one is
    downloaded, and before the program ends."""
    _files_later.finish(None if out_dir is None else _draft_key(out_dir))


def results_file(out_dir, name):
    """The path of the file `name` of the results in `out_dir`, written as the
    last correction makes it if it is one of those. A clip's frames wait for
    nothing."""
    if name in (reporting.EXCEL_NAME, reporting.DETECTIONS_NAME, reporting.CALIBRATION_EXCEL_NAME,
                *(figure for figure, _method in reporting.FIGURES)):
        finish_files(out_dir)
    return Path(out_dir) / name


def _normalizer_in_use(mite):
    """The normalisations config.yaml puts the scores of a folder's analysis
    through (mite.normalize_brightness and mite.normalize_floor), saved there
    with the threshold from the calibration report."""
    return ScoreNormalizer(floor=mite.normalize_floor, brightness=mite.normalize_brightness)


def _review_band(metric):
    """The band around the threshold of `metric` whose calls are checked by eye,
    as config.yaml has it now (a ReviewBand); None without one."""
    return ReviewBand.of(get_default_config().mite, metric)


def _change_call(zone_manager, corrections, mite_id, recording, state, detected=None, checked=False):
    """Make the mite `mite_id` `state` in `recording`, or step it to its next
    state without one (CallCorrections.change()). `detected` maps mite id to
    the detector's call per recording, where normalised scores make them other
    than the mite's own. With `checked` the call is kept as checked by eye."""
    mite = next((m for zone in zone_manager.zones for m in zone.mites if m.text == str(mite_id)), None)
    if mite is None:
        raise ValueError(f"No mite {mite_id} in these results.")
    calls = mite.moving if detected is None else detected[mite.text]
    if not 0 <= recording < len(calls):
        raise ValueError(f"No recording {recording} in these results.")
    corrections.change((mite.x1 + mite.x2) / 2, (mite.y1 + mite.y2) / 2, recording, bool(calls[recording]), state,
                       checked=checked)


def correct_call(out_dir, mite_id, recording, state=None, checked=False):
    """Change by hand what one mite is in one recording of the last run written to
    `out_dir`: `state` is "moving" or "still" (its call; the detector's again is
    no correction any more), "gone" (the mite is not there in this recording,
    e.g. it fell off) or "gone_from" (nor in any later one); without `state`,
    the next of these. A mite gone is censored there. The change is saved next
    to the recordings (see classes/call_corrections.py), so later runs keep it.
    With `checked`, a call is kept as checked by eye, also when it is the
    detector's: the answer to a close call (classes/review_band.py).
    Returns the results as run_analysis() does, every number following the
    change. The workbook and the figures are written again a moment later, once
    the corrections pause (finish_files() waits for them)."""
    with _runs_lock:
        kept = _runs.get(_draft_key(out_dir))
        if kept is None:
            raise ValueError("Run the analysis again to correct its calls.")
        run, labels, corrections, normalizer = kept
        _change_call(run.zone_manager, corrections, mite_id, int(recording), state,
                     _detected_calls(run, corrections, normalizer), checked=checked)
        results = _results(run, out_dir, labels, write_files=False, corrections=corrections, normalizer=normalizer)
    _write_files_later(run, out_dir, corrections, normalizer)
    return results


def save_review_band(low, high):
    """Make `low` to `high`, on the scale of the metric in use, the band around
    its threshold whose calls are checked by eye (classes/review_band.py), for
    every analysis from now on; without both, there is no band any more.
    Returns [low, high] as saved, or None."""
    return app_config.save_review_band(low, high)


def review_again(out_dir):
    """The results of the last run written to `out_dir` again, with the calls to
    check by eye as the band is now; None when that run is no longer kept."""
    with _runs_lock:
        kept = _runs.get(_draft_key(out_dir))
        if kept is None:
            return None
        run, labels, corrections, normalizer = kept
        return _results(run, out_dir, labels, write_files=False, corrections=corrections, normalizer=normalizer)


def death_minutes(data_dir):
    """How long a mite must be still to count as dead, from the test-run settings
    saved with the recordings; 0 (dead from its last movement on) without them.
    The pages take it with the results, for the mites alive over time."""
    path = Path(data_dir) / SETTINGS_FILENAME
    try:
        value = DataLoader._parse_settings_file(path).get("death_minutes", 0) if path.is_file() else 0
        return max(0, int(value))
    except (OSError, TypeError, ValueError):
        return 0


def death_minutes_range():
    """The least and the most a mite can be still to count as dead, in minutes."""
    _label, _unit, lowest, highest = SETTING_RANGES["death_minutes"]
    return [lowest, highest]


def save_death_minutes(data_dir, minutes):
    """Make `minutes` the time a mite must be still to count as dead for the
    recordings in `data_dir`: the death_minutes line of their .settings.txt,
    added or replaced, every other line kept as it is."""
    label, unit, lowest, highest = SETTING_RANGES["death_minutes"]
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number of {unit}.")
    if value != minutes or not lowest <= value <= highest:
        raise ValueError(f"{label} must be a whole number of {unit} between {lowest} and {highest}.")
    path = Path(data_dir) / SETTINGS_FILENAME
    DataLoader.save_setting(path, "death_minutes", value)
    return value


def _mite_table(run, corrections=None, normalizer=None):
    """The mite score table of a run, with the calls corrected by hand in place
    of the detector's and, with a `normalizer` (a ScoreNormalizer), its scores
    normalised and the detector's calls following them; and what the
    corrections changed (CallCorrections.apply())."""
    mite_data = run.zone_manager.get_mite_scores(run.burst_minutes)
    changes = {}
    if corrections is not None:
        mite_data, changes = corrections.apply(mite_data)
    if getattr(run, "activity", None) is not None:
        mite_data, changes = run.activity.censor(mite_data, changes)
    if normalizer is not None:
        mite_data = normalizer.apply(mite_data, run.analyzer.config.mite.motion_threshold)
    return mite_data, changes


def _detected_calls(run, corrections, normalizer):
    """Mite id to the detector's call per recording on the normalised scores;
    None when they are not normalised, so the calls are the mites' own."""
    if normalizer is None or not normalizer.active:
        return None
    mite_data, _changes = _mite_table(run, corrections, normalizer)
    mite_data = mite_data.assign(detected=normalizer.calls(mite_data, run.analyzer.config.mite.motion_threshold))
    return {str(mite_id): list(rows.sort_values("time")["detected"]) for mite_id, rows in mite_data.groupby("mite_ID")}


def _results(run, out_dir, labels, write_files=True, corrections=None, normalizer=None):
    """The results of a run as the UI browses them. With `write_files`, the
    workbook, the figures, the annotated first frame and the preview are written
    to `out_dir` too. A live run describes its results this same way after every
    recording, so its pages are drawn from exactly what a folder run returns. The calls
    corrected by hand (`corrections`, a CallCorrections) replace the detector's,
    and the mites marked gone are censored; with any, the results say which
    ("corrections", "censored", "gone_from", see CallCorrections.apply()). With
    a `normalizer` (a ScoreNormalizer) the results say which normalisations the
    scores went through ("normalization"): config.yaml's for a folder, none for
    a live run. With a band around the threshold in config.yaml, they hold the
    calls to check by eye ("review", see ReviewBand.describe())."""
    burst_minutes = run.burst_minutes
    mite_data, changes = _mite_table(run, corrections, normalizer)

    if write_files:
        _write_preview(run.first_frame, out_dir)
        results = _write_files(_annotated(run), out_dir, mite_data)
    else:
        results = reporting.describe_outputs(mite_data)

    results.update(
        {
            "n_recordings": run.n_recordings,
            "times": [round(float(minute), 2) for minute in burst_minutes],
            "threshold": float(run.analyzer.config.mite.motion_threshold),
            "preview": PREVIEW_NAME,
            "image": _image_size(run.first_frame),
            # "rois": only the mites' surroundings were saved, so the only clips are the mites'
            "frames": run.frames,
            "zones": reporting.describe_zones(mite_data, _describe_zones(run.zone_manager, labels), burst_minutes),
            "mites": reporting.describe_mites(mite_data),
            "groups": reporting.describe_groups(mite_data, burst_minutes),
        }
    )
    results.update(changes)
    if getattr(run, "activity", None) is not None:
        results["activity"] = run.activity.describe()
    if normalizer is not None:
        results["normalization"] = normalizer.describe()
    band = _review_band(run.analyzer.config.mite.metric)
    if band is not None:
        results["review"] = band.describe(mite_data, changes)
    return results


def describe_movement(results):
    """`results` (as run_analysis() returns them) with the numbers the result
    pages show about how the mites move: per mite, per zone (their rests between
    movements too), and the groups in the order the pages list them, each with
    the box of its moving mites' scores (see classes/movement_stats.py)."""
    return {**results, **MovementReport(results).describe()}


def describe_survival(results, death_minutes=0, controls=()):
    """The survival numbers of `results` (as run_analysis() returns them) for the
    result pages, with `death_minutes` the time a mite must be still to count as
    dead and `controls` the zones ticked as negative controls: the mites alive
    over time per group and per zone, and every group, its zones pooled, against
    the controls by the log-rank test (see classes/survival.py). They change with
    those two, with no need to run the analysis again."""
    return SurvivalReport(results, death_minutes, controls).describe()


# --- calibration -------------------------------------------------------------------
#
# A calibration session is a recording in which the user marks, mite by mite and
# recording by recording, whether each mite moves. open_calibration() detects the
# mites and keeps them in out_dir; calibration_clip() supplies the frames to judge
# movement from; evaluate_calibration() scores the labelled mites with the metric
# in use and compares the scores with the labels. Only the ground truth is saved,
# never the scores, so old recordings can be used to judge new metrics.

CLIP_MARGIN = 20        # pixels around a zone in its clip
CLIP_MAX_FRAMES = 15    # frames per clip; a recording is thinned out to this


def load_ground_truth(data_dir):
    """Saved ground truth for a recording session: a list of {x, y, truth}, where
    truth holds one status per recording."""
    path = Path(data_dir) / GROUND_TRUTH_FILENAME
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _folder_truth(data_dir):
    """The ground truth saved for a recording folder, by position, as every window
    reads it: the file next to the recordings."""
    return load_ground_truth(data_dir)


def _rejected_detections(zone_manager, saved):
    """The detected mites the user marked as not being mites."""
    rejected = [entry for entry in saved if calibration.is_rejected(entry.get("truth"))]
    if not rejected:
        return []
    mites = [mite for zone in zone_manager.zones for mite in zone.mites]
    described = [{"id": index, "x": (m.x1 + m.x2) / 2, "y": (m.y1 + m.y2) / 2} for index, m in enumerate(mites)]
    matched = calibration.match_ground_truth(described, rejected, n_recordings=1)
    return [mites[index] for index in matched]


def _read_calibration_session(out_dir):
    path = Path(out_dir) / CALIBRATION_SESSION_NAME
    if not path.is_file():
        raise FileNotFoundError("This calibration session has no mites. Open the folder again.")
    return json.loads(path.read_text(encoding="utf-8"))


def _mite_positions(mites):
    """The mites as the ground truth needs them: where they are, no scores."""
    return [{key: mite[key] for key in ("id", "zone_id", "x", "y", "r")} for mite in mites]


def _calibration_view(stored, truth):
    """What the ground-truth page needs about a calibration session."""
    return {
        "data_dir": stored["data_dir"],
        "dataset_id": dataset_id(stored["data_dir"]),
        "recordings_available": Path(stored["data_dir"]).is_dir(),
        "preview": PREVIEW_NAME,
        "image": stored["image"],
        "n_recordings": len(stored["times"]),
        "times": stored["times"],
        "recordings": [recording["name"] for recording in stored["recordings"]],
        "zones": stored["zones"],
        "mites": stored["mites"],
        "truth": truth,
        "threshold": float(get_default_config().mite.motion_threshold),
    }


def _opened_calibration(stored, out_dir):
    """The ground-truth page's view of a calibration session just opened in
    `out_dir`, whose ground truth is entered from scratch: no changes yet."""
    truth = _saved_truth(stored)
    draft = _new_draft(out_dir, stored, truth)
    with _drafts_lock:
        return {**_calibration_view(stored, truth), "truth_view": _draft_view(draft)}


def open_calibration(data_dir, out_dir, coords_file=None):
    """Detect the mites of a calibration session and keep them in `out_dir`.

    Nothing is scored here, so the page cannot show scores while the user enters
    the ground truth and bias it, and only the first frame is decoded.
    Detections already marked "not a mite" are kept here, so that the mark can
    be undone.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")
    stored = _calibration_session(data_dir, coords_file, out_dir)
    return _opened_calibration(stored, out_dir)


def _calibration_session(data_dir, coords_file, out_dir, names=None):
    """Detect the mites of a calibration session, on the first frame, write its
    preview to `out_dir`, and keep there what it is (calibration_session.json).
    With `names`, only the recordings of those names make the session."""
    stored, first_frame = _describe_calibration(data_dir, coords_file, names)
    _write_preview(first_frame, out_dir)
    _write_calibration_session(out_dir, stored)
    return stored


def _describe_calibration(data_dir, coords_file=None, names=None):
    """(stored, first frame): what a calibration session of `data_dir` is -- its
    recordings and their times, the image's size, the zones with their labels
    and the mites found on the first frame -- and that frame."""
    labels = load_labels(data_dir)
    run = _detect_and_score(data_dir, coords_file, labels, reject=False, score=False, names=names)

    mites = []
    for zone in run.zone_manager.zones:
        for mite in zone.mites:
            mites.append(
                {
                    "id": mite.text,
                    "zone_id": zone.id,
                    "x": round(float((mite.x1 + mite.x2) / 2), 1),
                    "y": round(float((mite.y1 + mite.y2) / 2), 1),
                    "r": round(float((mite.x2 - mite.x1) / 2), 1),
                }
            )
    if not mites:
        raise ValueError("No mites were detected, so there is nothing to calibrate.")
    mites.sort(key=lambda mite: Mite.id_order(mite["id"]))

    stored = {
        "data_dir": str(Path(data_dir).resolve()),
        **_calibration_recordings(data_dir, names),
        "image": _image_size(run.first_frame),
        "zones": _describe_zones(run.zone_manager, labels),
        "mites": mites,
    }
    return stored, run.first_frame


def _calibration_recordings(data_dir, names=None):
    """{times, recordings} of a calibration session: each recording's time, in
    minutes from the start of the first, as the analysis times it
    (MotionAnalysis.recording_times), and its name and frame rate. Read from
    the names alone: nothing is decoded."""
    recordings = open_source(data_dir, names).recordings()
    if not recordings:
        raise FileNotFoundError(f"No recordings found in {data_dir}")
    start = recordings[0].start
    return {
        "times": [round((recording.start - start).total_seconds() / 60, 2) for recording in recordings],
        "recordings": [{"name": recording.name, "fps": recording.fps} for recording in recordings],
    }


def _write_calibration_session(out_dir, stored):
    """Written whole before it takes the name: a live run's session grows while
    its pages read it."""
    path = Path(out_dir) / CALIBRATION_SESSION_NAME
    partial = path.with_name(f"partial_{path.name}")
    partial.write_text(json.dumps(stored), encoding="utf-8")
    partial.replace(path)


def calibration_clip(out_dir, recording, zone_id):
    """Frames of one zone during one recording, so the user can see which mites move.

    Writes up to CLIP_MAX_FRAMES JPEG crops to `out_dir` (once; later calls reuse
    them) and returns their filenames, where the crop sits in the full image, and
    the delay between frames that plays them back in real time.
    """
    stored = _read_calibration_session(out_dir)
    if not 0 <= recording < len(stored["recordings"]):
        raise ValueError(f"No recording {recording} in this session.")
    zone = next((zone for zone in stored["zones"] if zone["id"] == zone_id), None)
    if zone is None:
        raise ValueError(f"No zone {zone_id} in this session.")

    # One session can switch between datasets, so clips are named after theirs.
    name = f"clip_{_clip_key(dataset_id(stored['data_dir']))}_r{recording}_z{zone_id}"
    manifest = Path(out_dir) / CLIPS_DIRNAME / f"{name}.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))
    recordings_dir = Path(stored["data_dir"])
    if not recordings_dir.is_dir():
        raise FileNotFoundError(
            f"The recordings are no longer at {stored['data_dir']}, so there is no clip to play."
        )

    source = stored["recordings"][recording]
    box = (zone["x1"] - CLIP_MARGIN, zone["y1"] - CLIP_MARGIN, zone["x2"] + CLIP_MARGIN, zone["y2"] + CLIP_MARGIN)
    return _write_clip(open_recordings(recordings_dir), source["name"], source["fps"], box, out_dir, name)


def _clip_key(dataset):
    """A short name for `dataset` in its clips' file names: the clips sit in a
    session folder already named after it, and Windows (without long paths)
    refuses a path of more than 259 characters, which a long dataset name
    repeated in both reached."""
    return hashlib.sha1(str(dataset).encode("utf-8")).hexdigest()[:10]


def _write_image(path, image, params=()):
    """cv2.imwrite(), which only returns False where it cannot write (a path too
    long for Windows, a folder gone), made to say so."""
    if not cv2.imwrite(str(path), image, list(params)):
        raise OSError(f"Could not write {path} ({len(str(path))} characters"
                      f"{', longer than Windows allows' if len(str(path)) > 259 else ''}).")


MITE_CLIP_REACH = 40            # pixels from a mite's centre to the edge of its own clip
MITE_VARIATION = (1.0, 8.0)     # grey levels: the standard deviations the variation picture draws black and brightest


def _variation_picture(frames):
    """How much each pixel of `frames` (frames, height, width), grey, varies
    over them, as a picture: its standard deviation, from black at the
    first of MITE_VARIATION (the camera's noise) through orange to nearly
    white at the second."""
    variation = frames.astype(np.float32).std(axis=0)
    least, most = MITE_VARIATION
    shade = np.clip((variation - least) / (most - least), 0, 1)
    colours = np.array([[0, 0, 0], [52, 104, 235], [224, 244, 255]], dtype=np.float32)  # BGR; one hue, growing lighter
    return np.stack([np.interp(shade, [0.0, 0.5, 1.0], colours[:, channel]) for channel in range(3)], axis=-1).astype(np.uint8)


def _mite_clip(recordings_dir, source, mite, out_dir, name):
    """Every frame of one recording (`source`: {name, fps}) cut MITE_CLIP_REACH
    pixels around `mite` ({x, y}) and kept as it is (PNG), to judge by eye
    whether the mite moves, and one picture of how much each pixel varies over
    them (_variation_picture()). Written to out_dir/clips/ once, with a
    manifest `name`_x_y.json that later calls reuse; the name says where the
    cut is, so a mite detected anew elsewhere gets a new clip. Returns the
    files (relative to `out_dir`), where the cut sits in the image, and the
    delay between frames that plays them in real time."""
    x, y = int(round(mite["x"])), int(round(mite["y"]))
    x1, y1 = max(0, x - MITE_CLIP_REACH), max(0, y - MITE_CLIP_REACH)
    name = f"{name}_x{x1}_y{y1}"
    clips_dir = Path(out_dir) / CLIPS_DIRNAME
    manifest = clips_dir / f"{name}.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))
    frames = open_recordings(recordings_dir).load_recording_region(
        source["name"], x1, y1, x + MITE_CLIP_REACH, y + MITE_CLIP_REACH)
    clips_dir.mkdir(parents=True, exist_ok=True)
    names = [f"{CLIPS_DIRNAME}/{name}_{index:02d}.png" for index in range(len(frames))]
    for frame, frame_name in zip(frames, names):
        _write_image(Path(out_dir) / frame_name, frame)
    variation = f"{CLIPS_DIRNAME}/{name}_variation.png"
    _write_image(Path(out_dir) / variation, _variation_picture(frames))
    clip = {
        "frames": names,
        "variation": variation,
        "x": x1,
        "y": y1,
        "width": int(frames.shape[2]),
        "height": int(frames.shape[1]),
        "interval_ms": int(round(1000 / source["fps"])),
    }
    manifest.write_text(json.dumps(clip), encoding="utf-8")
    return clip


def calibration_mite_clip(out_dir, recording, mite_id):
    """Frames of one mite during one recording of a calibration session, cut
    close around it, for the ground-truth page (see _mite_clip())."""
    stored = _read_calibration_session(out_dir)
    if not 0 <= recording < len(stored["recordings"]):
        raise ValueError(f"No recording {recording} in this session.")
    mite = next((mite for mite in stored["mites"] if mite["id"] == str(mite_id)), None)
    if mite is None:
        raise ValueError(f"No mite {mite_id} in this session.")
    recordings_dir = Path(stored["data_dir"])
    if not recordings_dir.is_dir():
        raise FileNotFoundError(
            f"The recordings are no longer at {stored['data_dir']}, so there is no clip to play."
        )
    return _mite_clip(recordings_dir, stored["recordings"][recording], mite, out_dir,
                      f"mite_{_clip_key(dataset_id(stored['data_dir']))}_r{recording}")


def _write_clip(loader, recording_name, fps, box, out_dir, name, max_width=None):
    """Write up to CLIP_MAX_FRAMES JPEGs of the region `box` = (x1, y1, x2, y2) of
    one recording, and a manifest `name`.json that later calls reuse, to out_dir/clips/.

    Returns the frame files (relative to `out_dir`), where the region sits in the
    full image (in full image pixels, even when `max_width` scales the frames
    down), and the delay between frames that plays them back in real time.
    """
    clips_dir = Path(out_dir) / CLIPS_DIRNAME
    manifest = clips_dir / f"{name}.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))
    clips_dir.mkdir(parents=True, exist_ok=True)

    _check_saved(loader, *box)
    n_frames = loader.count_frames(recording_name)
    step = max(1, int(np.ceil(n_frames / CLIP_MAX_FRAMES)))
    x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
    frames = loader.load_recording_region(recording_name, x1, y1, int(box[2]), int(box[3]), step=step)
    height, width = frames.shape[1:3]
    scale = min(1.0, max_width / width) if max_width else 1.0

    names = []
    for index, frame in enumerate(frames):
        if scale < 1:
            frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        names.append(f"{CLIPS_DIRNAME}/{name}_{index:02d}.jpg")
        _write_image(Path(out_dir) / names[-1], frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    clip = {
        "frames": names,
        "x": x1,
        "y": y1,
        "width": int(width),
        "height": int(height),
        "interval_ms": int(round(1000 * step / fps)),
    }
    manifest.write_text(json.dumps(clip), encoding="utf-8")
    return clip


PLATE_CLIP_WIDTH = 1400  # the whole plate is scaled down to this width in its clip


def _check_saved(loader, x1, y1, x2, y2):
    """Refuse a clip of more than was saved: of a session saved as the mites'
    ROIs, only a mite's own clip can be played."""
    if not loader.covers(int(x1), int(y1), int(x2), int(y2)):
        raise ValueError("Only the mites' surroundings of these recordings were saved, so only a mite's own clip can be played.")


def dataset_clip(out_dir, dataset, recording, recordings_root=RECORDINGS_ROOT):
    """Frames of the whole plate, scaled down, during one recording of a saved
    dataset, for the test report to draw the calls on. Like calibration_clip(),
    written to `out_dir` once and reused after."""
    saved = _read_dataset(dataset, recordings_root)
    if not 0 <= recording < len(saved["recordings"]):
        raise ValueError(f"No recording {recording} in {saved['name']}.")
    recordings_dir = Path(saved["data_dir"])
    source = saved["recordings"][recording]
    return _write_clip(open_recordings(recordings_dir), source["name"], source["fps"], (0, 0, 10**6, 10**6),
                       out_dir, f"clip_{_clip_key(dataset)}_r{recording}_plate", PLATE_CLIP_WIDTH)


def _recording_name(loader, recording):
    """The name of recording `recording` of an analysis, counted from 0."""
    recordings = loader.recording_names
    if not 0 <= recording < len(recordings):
        raise ValueError(f"No recording {recording} in this session.")
    return recordings[recording]


def analysis_outlines(data_dir, out_dir, recording, zone_id, mites):
    """What the score sees of each mite of one zone in one recording of an
    analysis, for the result pages to draw over the mites: mite id to
    OutlineView.describe(), None for a mite it finds no outline of. `mites` are
    the results' ({id, zone_id, x, y}). Like analysis_clip(), worked out from
    the frames once, kept in `out_dir` and reused after."""
    loader = open_recordings(data_dir)
    source = _recording_name(loader, recording)
    mites = [mite for mite in mites if mite["zone_id"] == zone_id]
    manifest = Path(out_dir) / CLIPS_DIRNAME / f"outline_r{recording}_z{zone_id}.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))
    if not mites:
        return {}

    mite = get_default_config().mite
    params = Analyzer.check_metric_params(mite.metric, mite.params_for(mite.metric))
    pad, width = Analyzer.roi_padding(mite.metric, params), params.get("width", 1.5)
    reach = int(mite.radius) + pad
    boxes = {m["id"]: (int(round(m["x"])) - reach, int(round(m["y"])) - reach, int(round(m["x"])) + reach, int(round(m["y"])) + reach)
             for m in mites}
    x0, y0 = max(0, min(box[0] for box in boxes.values())), max(0, min(box[1] for box in boxes.values()))
    frames = loader.load_recording_region(source, x0, y0, max(box[2] for box in boxes.values()),
                                          max(box[3] for box in boxes.values()))
    outlines = {}
    for mite_id, (x1, y1, x2, y2) in boxes.items():
        x1, y1 = max(x1, x0), max(y1, y0)
        outlines[mite_id] = OutlineView.describe(frames[:, y1 - y0:y2 - y0, x1 - x0:x2 - x0], x1, y1, width, pad)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(outlines), encoding="utf-8")
    return outlines


def analysis_clip(data_dir, out_dir, recording, zone_id=None, coords_file=None):
    """Frames of one recording of an analysis session: of one zone, or with no
    `zone_id` of the whole plate, scaled down. Like calibration_clip(), written
    to `out_dir` once and reused after."""
    loader = open_recordings(data_dir)
    source = _recording_name(loader, recording)

    if zone_id is None:
        box, name, max_width = (0, 0, 10**6, 10**6), f"clip_r{recording}_plate", PLATE_CLIP_WIDTH
    else:
        zone = next((z for z in _build_zone_manager(_coords_file(data_dir, coords_file)).labelled_zones if z.id == zone_id), None)
        if zone is None:
            raise ValueError(f"No zone {zone_id} in this session.")
        box = (zone.x1 - CLIP_MARGIN, zone.y1 - CLIP_MARGIN, zone.x2 + CLIP_MARGIN, zone.y2 + CLIP_MARGIN)
        name, max_width = f"clip_r{recording}_z{zone_id}", None
    return _write_clip(loader, source, loader.get_fps(source), box, out_dir, name, max_width)


def analysis_mite_clip(data_dir, out_dir, recording, mite_id, mites):
    """Frames of one mite during one recording of an analysis, cut close around
    it, for the mite page of a session saved as the mites' ROIs, which has no
    zone clip (see _mite_clip()). `mites` are the results' ({id, x, y})."""
    mite = next((mite for mite in mites if mite["id"] == str(mite_id)), None)
    if mite is None:
        raise ValueError(f"No mite {mite_id} in these results.")
    loader = open_recordings(data_dir)
    name = _recording_name(loader, recording)
    return _mite_clip(data_dir, {"name": name, "fps": loader.get_fps(name)}, mite, out_dir, f"mite_r{recording}")


ACTIVITY_CLIP_FRAMES = 480     # frames in a clip of unusual activity at most; each recording is thinned to fit
ACTIVITY_CLIP_RECORDINGS = 60   # recordings in one at most
ACTIVITY_CLIP_REACH = 40        # pixels round the mite, or its track, in the clip
ACTIVITY_CLIP_WIDTH = 720       # a wider clip is scaled down to this
ACTIVITY_CLIP_MIN_WIDTH = 320   # a narrower one is scaled up, a whole number of times
ROTATOR_CLIP_SPAN = 6           # recordings before and after a rotator first turned past the limit


def activity_clip(data_dir, out_dir, activity, times, kind, mite_id):
    """One clip of a fly-off or a rotator (results["activity"], see
    classes/unusual_activity.py), every recording it spans played one after
    the other, each frame marked with its recording's time (`times`, minutes):
    a fly-off from the recording before it left to the one after it stopped
    walking, round its whole track; a rotator ROTATOR_CLIP_SPAN recordings
    either side of when it first turned past the limit, round the mite. Like
    analysis_clip(), written to `out_dir` once and reused after."""
    events = activity.get("fly_offs" if kind == "fly_off" else "rotators", []) if kind in ("fly_off", "rotator") else []
    event = next((e for e in events if e["id"] == str(mite_id)), None)
    if event is None:
        raise ValueError(f"No {kind.replace('_', '-')} {mite_id} in these results.")
    n = len(times)
    if kind == "fly_off":
        first, last = max(0, event["from"] - 1), min(n - 1, event.get("walked_to", event["to"]) + 1)
        points = [(x, y) for r, x, y in event["track"] if first <= r <= last] + [(event["x"], event["y"])]
    else:
        first, last = max(0, event["from"] - ROTATOR_CLIP_SPAN), min(n - 1, event["from"] + ROTATOR_CLIP_SPAN)
        points = [(event["x"], event["y"])]
    last = min(last, first + ACTIVITY_CLIP_RECORDINGS - 1)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x1, y1 = max(0, int(min(xs)) - ACTIVITY_CLIP_REACH), max(0, int(min(ys)) - ACTIVITY_CLIP_REACH)
    x2, y2 = int(max(xs)) + ACTIVITY_CLIP_REACH, int(max(ys)) + ACTIVITY_CLIP_REACH
    name = f"activity_{kind}_{re.sub(r'[^0-9A-Za-z]+', '-', str(mite_id))}_r{first}-{last}_x{x1}_y{y1}"
    clips_dir = Path(out_dir) / CLIPS_DIRNAME
    manifest = clips_dir / f"{name}.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))

    loader = open_recordings(data_dir)
    _check_saved(loader, x1, y1, x2, y2)
    recordings = [_recording_name(loader, recording) for recording in range(first, last + 1)]
    n_frames = sum(loader.count_frames(recording) for recording in recordings)
    step = max(1, int(np.ceil(n_frames / ACTIVITY_CLIP_FRAMES)))
    clips_dir.mkdir(parents=True, exist_ok=True)
    names, width, height, fps = [], None, None, None
    for recording, source in zip(range(first, last + 1), recordings):
        fps = fps or loader.get_fps(source)
        for frame in loader.load_recording_region(source, x1, y1, x2, y2, step=step):
            height, width = frame.shape[:2]
            scale = min(1.0, ACTIVITY_CLIP_WIDTH / width)
            if scale < 1:
                frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
            elif width < ACTIVITY_CLIP_MIN_WIDTH:  # a mite's crop: pixels made larger, so the time fits beside it
                grow = int(np.ceil(ACTIVITY_CLIP_MIN_WIDTH / width))
                frame = cv2.resize(frame, (width * grow, height * grow), interpolation=cv2.INTER_NEAREST)
            frame = np.ascontiguousarray(frame)
            label = f"{times[recording]:.1f} min"
            for colour, thickness in (((0, 0, 0), 3), ((255, 255, 255), 1)):
                cv2.putText(frame, label, (6, frame.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, thickness, cv2.LINE_AA)
            names.append(f"{CLIPS_DIRNAME}/{name}_{len(names):03d}.jpg")
            _write_image(Path(out_dir) / names[-1], frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    clip = {
        "frames": names,
        "x": x1,
        "y": y1,
        "width": int(width),
        "height": int(height),
        "interval_ms": int(round(1000 * step / (fps or 10))),
        "recordings": [first, last],
    }
    manifest.write_text(json.dumps(clip), encoding="utf-8")
    return clip


def save_ground_truth(out_dir, truth):
    """Store the ground truth next to the recordings, by mite position.

    `truth` maps mite id to a list with one status per recording: "moving",
    "still", "not_a_mite" or None for unlabelled. Positions rather than ids are
    stored, so the file still applies after a change of detector settings
    renumbers the mites.
    """
    return len(_write_ground_truth(_read_calibration_session(out_dir), truth))


def update_ground_truth(out_dir, changes):
    """Save the changes made on screen on top of what is saved, which another
    window (marking a detection "not a mite" before a run, say) may have changed
    since this session opened. `changes` maps mite id to the statuses that
    changed, by recording index, or to a list of every recording's (see
    calibration.apply_changes()); only those recordings change, so a page that
    has not caught up with a change made elsewhere cannot undo it. Returns the
    whole ground truth by mite id, as save_ground_truth() takes it."""
    stored = _read_calibration_session(out_dir)
    truth = _saved_truth(stored)
    for mite_id, changed in changes.items():
        truth[mite_id] = calibration.apply_changes(truth.get(mite_id), changed, len(stored["times"]))
    return _write_ground_truth(stored, truth)


# --- the ground truth being entered
#
# The changes made on the ground-truth page wait here, one draft per calibration
# session (keyed by its folder), until they are saved: the page saves them as soon
# as they are made, and a click need not wait for the disk. What the page shows
# is always what saving them will store (see classes/truth_draft.py). Every view carries a version, higher for every view
# made, so the page can tell which reply is the latest.

_drafts = {}
_drafts_lock = threading.Lock()
_truth_versions = itertools.count(1)


def _draft_key(out_dir):
    return str(Path(out_dir).resolve())


def _new_draft(out_dir, stored, truth):
    draft = TruthDraft(stored["mites"], stored["zones"], len(stored["times"]), truth)
    with _drafts_lock:
        _drafts[_draft_key(out_dir)] = draft
    return draft


def _draft(out_dir):
    with _drafts_lock:
        draft = _drafts.get(_draft_key(out_dir))
    if draft is None:  # e.g. the server restarted: start again from what is saved
        stored = _read_calibration_session(out_dir)
        draft = _new_draft(out_dir, stored, _saved_truth(stored))
    return draft


def _draft_view(draft, changed=False):
    """The draft's view (TruthDraft.view()), its version, and whether what is shown
    changed. Called holding _drafts_lock."""
    return {**draft.view(), "version": next(_truth_versions), "changed": changed}


def truth_view(out_dir):
    """The ground truth of a calibration session as saved now, which another
    window or the analysis (marking a detection "not a mite") may have changed,
    with the changes not saved yet on top."""
    draft = _draft(out_dir)
    with _drafts_lock:
        saves = draft.saves
    saved = load_calibration_truth(out_dir)
    with _drafts_lock:
        # A save that landed while this was read already brought newer truth.
        changed = draft.load(saved) if draft.saves == saves else False
        return _draft_view(draft, changed)


def edit_truth(out_dir, action, mite=None, zone=None, recording=0, backwards=False, kind=None, state=None):
    """A change on the ground-truth page, not saved yet: "set" a `mite`'s status
    in `recording` to `state` ("moving", "still", "not_a_mite" or None for
    unlabelled), mark it "dead" from `recording` on (TruthDraft.dead_from()),
    "cycle" it to its next status there (its previous one with `backwards`), or
    "fill" the unlabelled mites of a `zone` in `recording` by `kind` (see
    TruthDraft.fill)."""
    draft = _draft(out_dir)
    with _drafts_lock:
        if action == "set":
            if state not in (*calibration.TRUTH_STATES, None):
                raise ValueError(f"Unknown status {state!r}.")
            draft.set(str(mite), int(recording), state)
        elif action == "dead":
            draft.dead_from(str(mite), int(recording))
        elif action == "cycle":
            draft.cycle(str(mite), int(recording), bool(backwards))
        elif action == "fill":
            draft.fill(int(zone), int(recording), kind)
        else:
            raise ValueError(f"Unknown change {action!r}.")
        return _draft_view(draft, changed=True)


def save_truth(out_dir):
    """Save the changes made on the ground-truth page on top of what is saved
    (update_ground_truth()); changes made while saving wait for the next save."""
    draft = _draft(out_dir)
    with _drafts_lock:
        sent = draft.unsaved_now()
    changed = False
    if sent:
        saved = update_ground_truth(out_dir, sent)
        with _drafts_lock:
            changed = draft.saved_as(sent, saved)
    with _drafts_lock:
        return _draft_view(draft, changed)


def load_calibration_truth(out_dir):
    """The ground truth saved for a calibration session's mites, by mite id."""
    return _saved_truth(_read_calibration_session(out_dir))


def _saved_truth(stored):
    """The saved ground truth of a calibration session's mites, by mite id."""
    return calibration.match_ground_truth(stored["mites"], _folder_truth(stored["data_dir"]), len(stored["times"]))


def _write_ground_truth(stored, truth, tolerance=10.0):
    """Write the ground truth of a calibration session's mites (`truth`, by
    mite id) next to its recordings, by position; returns the mites labelled."""
    n_recordings = len(stored["times"])
    labelled = {}
    for mite in stored["mites"]:
        states = calibration.per_recording(truth.get(mite["id"]), n_recordings)
        if any(states):
            labelled[mite["id"]] = states

    recordings_dir = Path(stored["data_dir"])
    if not recordings_dir.is_dir():
        raise FileNotFoundError(f"The recordings are no longer at {stored['data_dir']}, so the ground truth "
                                "cannot be saved with them.")
    if True:
        entries = [{"x": mite["x"], "y": mite["y"], "truth": labelled[mite["id"]]}
                   for mite in stored["mites"] if mite["id"] in labelled]
        # Entries away from every mite of this session, e.g. detections marked
        # "not a mite" under other detector settings, are not this session's to drop.
        entries += [entry for entry in load_ground_truth(recordings_dir)
                    if all(np.hypot(entry["x"] - m["x"], entry["y"] - m["y"]) > tolerance for m in stored["mites"])]
        (recordings_dir / GROUND_TRUTH_FILENAME).write_text(json.dumps(entries), encoding="utf-8")
    return labelled


# --- the poke test
#
# Mites poked by hand between two recordings: one that moves is alive up to then,
# one that does not is dead from then on (classes/poke_test.py). The rounds are
# saved by mite position next to the recordings, like the ground truth, and every
# change at once: the file is small. The test report draws the survival they show
# with the detector's laid over it (evaluate_calibration()).


def load_poke_test(data_dir):
    """The poke test saved for a recording folder: {rounds: [{after, mites: [{x,
    y, state}]}]}, as PokeTest.saved() gives it; {} without one."""
    path = Path(data_dir) / POKE_FILENAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _poke_of(source):
    """The poke test of a calibration session or a saved dataset (`source` has
    its data_dir, mites and times), by mite id. Detections marked not a mite in
    the ground truth have no part in it."""
    n_recordings = len(source["times"])
    truth = source["truth"] if "truth" in source else _saved_truth(source)
    mites = [mite for mite in source["mites"]
             if not calibration.is_rejected(calibration.per_recording(truth.get(mite["id"]), n_recordings))]
    return PokeTest(mites, n_recordings, load_poke_test(source["data_dir"]))


def poke_view(out_dir):
    """The poke test of a calibration session as saved now (PokeTest.view())."""
    return _poke_of(_read_calibration_session(out_dir)).view()


def edit_poke(out_dir, action, after, mite=None, zone=None, state=None):
    """A change on the poke-test page, saved at once: "add" a round poked after
    the recording `after` (-1: before the first) or "remove" it; "set" what a
    `mite` did in it to `state` ("moved", "unmoved" or None for not poked); or
    "fill" the mites of a `zone` (of every zone without one) not poked yet in it
    with `state`, None taking their pokes back. Returns the view with it."""
    stored = _read_calibration_session(out_dir)
    recordings_dir = Path(stored["data_dir"])
    if not recordings_dir.is_dir():
        raise FileNotFoundError(
            f"The recordings are no longer at {stored['data_dir']}, so the poke test cannot be saved with them.")
    poke = _poke_of(stored)
    if action == "add":
        poke.add(after)
    elif action == "remove":
        poke.remove(after)
    elif action == "set":
        poke.set(after, str(mite), state)
    elif action == "fill":
        poke.fill(after, state, None if zone is None else int(zone))
    else:
        raise ValueError(f"Unknown change {action!r}.")
    (recordings_dir / POKE_FILENAME).write_text(json.dumps(poke.saved()), encoding="utf-8")
    return poke.view()


def _poked_mites(dataset, scores, threshold):
    """The poked mites of a dataset with the detector's death of each at
    `threshold` (PokeSurvival.mites()); [] without a poke test."""
    poke = _poke_of(dataset)
    if not poke.rounds:
        return []
    moving = {mite["id"]: [score >= threshold for score in scores[mite["id"]]] for mite in poke.mites}
    return PokeSurvival(poke, dataset["times"], moving).mites()


def _poke_survival(mites, times):
    """The survival of the poked mites of the pooled datasets by the pokes and by
    the detector, for the test report (PokeSurvival.curves()); None without any."""
    curves = PokeSurvival.curves(mites, times)
    if curves:
        for curve in (curves["poke"], curves["detector"]):
            curve.update({key: _rounded(curve[key], 2) for key in ("alive", "low", "high")})
    return curves


# --- datasets: the recordings with ground truth -----------------------------------------
#
# A dataset is a recording folder in recordings/ whose ground truth
# (ground_truth.json, by position) labels any mite; its id is the folder's name.
# What a report needs of it -- its mites, zones and recordings, and the ground
# truth by mite id -- is worked out from the folder itself, as a calibration
# session of it finds them (_describe_calibration()): a session saved as the
# mites' ROIs keeps the mites found when it was saved. scores/ in the folder
# caches the scores reports computed, one file per version of the metric; it can
# be deleted at any time.


def dataset_id(data_dir):
    """The id of the dataset of a recording folder: its name."""
    return Path(data_dir).name


def _dataset_dir(dataset, recordings_root):
    """The recording folder of the dataset `dataset`, in `recordings_root`."""
    dataset = str(dataset)
    if not dataset or dataset in (".", "..") or Path(dataset).name != dataset or "/" in dataset or "\\" in dataset:
        raise ValueError(f"Bad dataset: {dataset}")
    folder = Path(recordings_root) / dataset
    if not folder.is_dir():
        raise FileNotFoundError(f"No recording called {dataset}.")
    return folder


def dataset_folder(dataset, recordings_root=RECORDINGS_ROOT):
    """The recording folder of the dataset `dataset` (its name)."""
    return str(_dataset_dir(dataset, recordings_root))


def _scores_dir(dataset):
    """Where a dataset's scores are cached: scores/ in its recording folder."""
    return Path(dataset["data_dir"]) / SCORES_DIRNAME


# What _read_dataset() worked out, by folder and what it was worked out from.
_described = {}
_described_lock = threading.Lock()


def _read_dataset(dataset, recordings_root=RECORDINGS_ROOT):
    """A dataset as a report needs it: what a calibration session of its folder
    stores (_describe_calibration()) with its name, the ground truth by mite id
    ("truth") and when that was saved ("saved_at"). Worked out again only when
    the folder's ground truth, labels or recordings changed."""
    folder = _dataset_dir(dataset, recordings_root)
    truth_file = folder / GROUND_TRUTH_FILENAME
    if not _labelled(load_ground_truth(folder)):
        raise FileNotFoundError(f"No ground truth is saved for {dataset}.")
    changed = [path.stat().st_mtime_ns if path.exists() else None
               for path in (truth_file, _layout_file(folder, LABELS_FILENAME), folder / SETTINGS_FILENAME,
                            folder / ROI_DIRNAME / "index.json", folder)]
    key = (str(folder.resolve()), *changed)
    with _described_lock:
        stored = _described.get(key)
    if stored is None:
        stored, _first_frame = _describe_calibration(folder)
        with _described_lock:
            _described[key] = stored
    return {**stored, "name": folder.name,
            "saved_at": datetime.fromtimestamp(truth_file.stat().st_mtime).isoformat(timespec="seconds"),
            "truth": _saved_truth(stored)}


def _labelled(entries):
    """Whether ground truth (load_ground_truth()) labels any mite, as moving,
    still or not a mite."""
    return any(any(entry.get("truth") if isinstance(entry.get("truth"), list) else [entry.get("truth")])
               for entry in entries if isinstance(entry, dict))


def _label_counts(truth, n_recordings):
    """Mites with a movement label, and moving and still labels, in ground truth
    (its statuses, one entry per mite)."""
    states = [calibration.per_recording(value, n_recordings) for value in truth]
    states = [s for s in states if not calibration.is_rejected(s)]
    return {
        "n_mites": sum(any(s) for s in states),
        "n_moving": sum(s.count(calibration.MOVING) for s in states),
        "n_still": sum(s.count(calibration.STILL) for s in states),
    }


def list_calibration_datasets(recordings_root=RECORDINGS_ROOT):
    """Every recording in `recordings_root` with a mite labelled moving or still
    in its ground truth, the most recently saved first. Read from the files
    alone: nothing is decoded. The labels are counted over every recording
    labelled, should the folder hold fewer."""
    datasets = []
    for folder in sorted(Path(recordings_root).iterdir()) if Path(recordings_root).is_dir() else []:
        entries = load_ground_truth(folder) if folder.is_dir() else []
        if not _labelled(entries):
            continue
        try:
            n_recordings = open_recordings(folder).count_recordings()
        except (OSError, ValueError):
            continue
        counts = _label_counts([entry.get("truth") for entry in entries],
                               max([n_recordings, 1] + [len(entry["truth"]) for entry in entries
                                                        if isinstance(entry.get("truth"), list)]))
        if not counts["n_moving"] + counts["n_still"]:
            continue  # only "not a mite" marks, from the label page: nothing to calibrate with
        datasets.append(
            {
                "id": folder.name,
                "name": folder.name,
                "data_dir": str(folder.resolve()),
                "saved_at": datetime.fromtimestamp((folder / GROUND_TRUTH_FILENAME).stat().st_mtime)
                .isoformat(timespec="seconds"),
                "n_recordings": n_recordings,
                **counts,
            }
        )
    return sorted(datasets, key=lambda d: d["saved_at"], reverse=True)


def open_saved_calibration(dataset, out_dir, recordings_root=RECORDINGS_ROOT):
    """Reopen a dataset to go on labelling it: open_calibration() of its folder.
    `out_dir` may already hold another dataset -- a pooled report jumping to
    one of its mites -- which this one then replaces; the files of earlier
    evaluations stay."""
    return open_calibration(_dataset_dir(dataset, recordings_root), out_dir)


def dataset_preview(dataset, recordings_root=RECORDINGS_ROOT, results_root=RESULTS_ROOT):
    """Path of a dataset's first frame: the preview of its results, written
    when there is none yet."""
    folder = _dataset_dir(dataset, recordings_root)
    path = results_dir(folder, results_root) / PREVIEW_NAME
    if not path.is_file():
        _write_preview(open_recordings(folder).load_preview_frame(), path.parent)
    return str(path)


def delete_calibration_dataset(dataset, recordings_root=RECORDINGS_ROOT):
    """Delete the ground truth of a recording -- its ground_truth.json and
    poke_test.json -- and the scores cached for it. The recordings stay."""
    folder = _dataset_dir(dataset, recordings_root)
    if not _labelled(load_ground_truth(folder)):
        raise FileNotFoundError(f"No ground truth is saved for {dataset}.")
    for name in (GROUND_TRUTH_FILENAME, POKE_FILENAME):
        (folder / name).unlink(missing_ok=True)
    remove_tree(folder / SCORES_DIRNAME)
    return dataset


# --- a folder opened by its path, for a calibration
#
# A calibration keeps its ground truth with the recordings, in recordings/: a
# folder opened elsewhere by its path is copied there first, its frames shrunk
# to the mites' surroundings as a folder dropped into the page is
# (classes/roi_conversion.py), and calibrated there.

# Files never written again once they have their name: the frames, the mites'
# videos (a stitch writes a new one) and a session's whole first frame.
_WRITTEN_ONCE = {".bmp", ".mkv", ".png"}


def _keep_once(source, target):
    """`target`, a copy of a recording file. A frame is never written again once
    it has its name, so its copy is a hard link where one can be made: on disk
    once. The folder's own files (settings, labels, ground truth, a session's
    index of ROIs) are written in place, so they are copied."""
    if source.suffix.lower() in _WRITTEN_ONCE:
        try:
            os.link(source, target)
            return
        except OSError:
            pass
    shutil.copy2(source, target)


def _copy_recordings(data_dir, target):
    """Copy a recording folder to `target`: its own files (settings, labels,
    ground truth, poke test) and every recording in it, each frame linked
    rather than copied where it can be (_keep_once()). A file still being
    written (*.part) is not one yet."""
    data_dir = Path(data_dir)
    files = [path for path in data_dir.iterdir() if path.is_file()]
    if is_roi_session(data_dir):
        rois_dir = data_dir / ROI_DIRNAME
        files += [path for path in rois_dir.rglob("*") if path.is_file()
                  and not any(part.endswith(".part") or part == "stitching" for part in path.relative_to(rois_dir).parts)]
    else:
        for name in DataLoader(data_dir).recording_names:
            files += [path for path in (data_dir / name).rglob("*") if path.is_file()]
    for source in (path for path in files if path.suffix != ".part"):
        copy = target / source.relative_to(data_dir)
        copy.parent.mkdir(parents=True, exist_ok=True)
        partial = copy.with_name(copy.name + ".part")
        partial.unlink(missing_ok=True)  # left by a copy cut short: a link needs the name free
        _keep_once(source, partial)
        partial.replace(copy)  # only a complete file ever has the real name


def _free_name(name, recordings_root):
    """`name`, or `name-2`, `name-3`... : the first not taken in `recordings_root`."""
    candidates = itertools.chain([name], (f"{name}-{number}" for number in itertools.count(2)))
    return next(candidate for candidate in candidates if not (Path(recordings_root) / candidate).exists())


ORIGIN_NAME = "copied_from.txt"  # in a copy calibration_folder() made: the folder it is a copy of


def calibration_folder(data_dir, recordings_root=RECORDINGS_ROOT):
    """The folder in `recordings_root` a calibration of `data_dir` works on:
    `data_dir` itself when it is there, else its copy there -- made now, its
    frames shrunk to the mites' surroundings, the first time; the one made
    before after. Its ground truth, poke test and labels come along."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")
    if data_dir.resolve().parent == Path(recordings_root).resolve():
        return data_dir
    origin = os.path.normcase(str(data_dir.resolve()))
    for folder in sorted(Path(recordings_root).glob(f"*/{ORIGIN_NAME}")):
        if folder.read_text(encoding="utf-8").strip() == origin:
            return folder.parent
    target = Path(recordings_root) / _free_name(_folder_name(data_dir), recordings_root)
    partial = target.with_name(target.name + ".copying")
    remove_tree(partial)
    _copy_recordings(data_dir, partial)
    (partial / ORIGIN_NAME).write_text(origin, encoding="utf-8")
    partial.rename(target)
    convert_folder(target)
    return target


# --- one-off: the calibration library of earlier versions ------------------------------
#
# Earlier versions kept a second home for calibration work, calibration_data/: per
# dataset a copy of its recordings, dataset.json (its mites and ground truth by mite
# id) and scores/, and in reports/ the calibration sessions' folders and the
# scripts' outputs. dissolve_calibration_library() brings all of it home: run by
# scripts/convert_stored_recordings.py before the server starts, and deleted with it.

OLD_LIBRARY = APP_DIR / "calibration_data"
EARLIER_REPORTS = "earlier calibration reports"


def _merged_truth(kept, extra):
    """Ground truth `kept` (by position) with the entries of `extra` that are not
    within 10 px of one of its own added."""
    merged = list(kept)
    for entry in extra:
        if all(np.hypot(entry["x"] - other["x"], entry["y"] - other["y"]) > 10.0 for other in merged):
            merged.append(entry)
    return merged


def _rekeyed_scores(scores_dir, old_mites, new_mites):
    """Rename the cached scores in `scores_dir` of mites saved under the ids of
    an earlier version (`old_mites`, {id, x, y, r}) to those of the same mites
    now (`new_mites`, in their order), so the scores of this very code are
    read back, not worked out again. The mites are matched by position; files
    of older code, or with mites that do not all match, are left as they are.
    Returns how many files were renamed."""
    new_at = {(round(m["x"], 1), round(m["y"], 1), round(m["r"], 1)): m["id"] for m in new_mites}
    ids = {m["id"]: new_at.get((round(m["x"], 1), round(m["y"], 1), round(m["r"], 1))) for m in old_mites}
    if not old_mites or None in ids.values() or len(set(ids.values())) != len(ids) or len(ids) != len(new_mites) \
            or all(old == new for old, new in ids.items()):
        return 0

    def mites_key(mites):
        return [[m["id"], m["x"], m["y"], m["r"]] for m in mites]

    def short(*parts):
        return hashlib.sha1(json.dumps(list(parts)).encode("utf-8")).hexdigest()[:12]

    benchmark_source = inspect.getsource(benchmark_module)
    stabilizer_source = inspect.getsource(plate_stabilizer)
    renamed = 0
    for path in sorted(Path(scores_dir).glob("*.json")):
        cached = _read_json(path)
        if not isinstance(cached, dict):
            continue
        name, by_mite, new_name = path.stem, None, None
        if "scores" in cached and "metric" in cached:
            for stabilize in (False, True):
                if _metric_version(cached["metric"], cached.get("params"), old_mites, stabilize) == name:
                    by_mite, new_name = "scores", _metric_version(cached["metric"], cached.get("params"), new_mites, stabilize)
        elif "calls" in cached and name == f"benchmark-{short(benchmark_source, mites_key(old_mites))}":
            by_mite, new_name = "calls", f"benchmark-{short(benchmark_source, mites_key(new_mites))}"
        elif "brightness" in cached:
            for pad, stabilize in itertools.product(range(65), (False, True)):
                if name == f"brightness-{short(stabilizer_source, pad, stabilize, mites_key(old_mites))}":
                    by_mite, new_name = "brightness", f"brightness-{short(stabilizer_source, pad, stabilize, mites_key(new_mites))}"
        if by_mite is None or not set(cached[by_mite]) <= set(ids):
            continue
        target = path.with_name(f"{new_name}.json")
        if not target.exists():
            target.write_text(json.dumps({**cached, by_mite: {ids[key]: value for key, value in cached[by_mite].items()}}),
                              encoding="utf-8")
            renamed += 1
    return renamed


def dissolve_calibration_library(library_dir=OLD_LIBRARY, recordings_root=RECORDINGS_ROOT,
                                 results_root=RESULTS_ROOT, report=None):
    """Bring what an earlier version kept in `library_dir` home, and remove it.

    Each saved dataset goes to its recording folder in `recordings_root`: the
    folder it was saved from when that is there (one elsewhere is copied in, as
    calibration_folder() copies it), else the library's copy of it, moved there.
    Its ground truth is merged into the folder's (the folder's entries win; the
    copy's and dataset.json's others are added), a poke test the folder lacks is
    taken from the copy (one that differs is kept beside it as
    poke_test.from_library.json), and its cached scores move into the folder's
    scores/. The reports' folders that hold a report go to `results_root`/earlier
    calibration reports/, the scripts' outputs to `results_root`/scripts/.
    Nothing is overwritten; run again, it carries on where it stopped.
    `report(text)` hears of each thing done."""
    report = report or (lambda text: None)
    library_dir = Path(library_dir)
    if not library_dir.is_dir():
        return
    for path in sorted(library_dir.glob(f"*/{DATASET_NAME}")):
        folder = path.parent
        saved = _read_json(path)
        if not isinstance(saved, dict):
            continue
        original = Path(str(saved.get("data_dir", "")))
        copy = folder / RECORDINGS_DIRNAME
        if original.is_dir():
            run = calibration_folder(original, recordings_root)
        elif copy.is_dir():
            run = Path(recordings_root) / _free_name(_folder_name(PurePosixPath(str(original).replace("\\", "/")))
                                                     if str(original) else folder.name, recordings_root)
            run.parent.mkdir(parents=True, exist_ok=True)
            copy.rename(run)
            report(f"moved the library's copy of {saved.get('name', folder.name)} to {run}")
        else:
            report(f"left {folder}: neither its recordings nor a copy of them are there")
            continue

        truth = load_ground_truth(run)
        extra = load_ground_truth(copy) if copy.is_dir() else []
        positions = {mite["id"]: mite for mite in saved.get("mites", [])}
        extra += [{"x": positions[mite_id]["x"], "y": positions[mite_id]["y"], "truth": states}
                  for mite_id, states in (saved.get("truth") or {}).items() if mite_id in positions]
        merged = _merged_truth(truth, extra)
        if len(merged) > len(truth):
            (run / GROUND_TRUTH_FILENAME).write_text(json.dumps(merged), encoding="utf-8")
            report(f"{run.name}: {len(merged) - len(truth)} ground truth entries added from the library")
        poke = copy / POKE_FILENAME if copy.is_dir() else None
        if poke is not None and poke.is_file():
            if not (run / POKE_FILENAME).is_file():
                shutil.copy2(poke, run / POKE_FILENAME)
            elif poke.read_bytes() != (run / POKE_FILENAME).read_bytes():
                shutil.copy2(poke, run / "poke_test.from_library.json")
                report(f"{run.name}: the library's poke test differs; kept beside it as poke_test.from_library.json")
        for cached in sorted((folder / SCORES_DIRNAME).glob("*")):
            target = run / SCORES_DIRNAME / cached.name
            if cached.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cached), target)
        try:  # cached under the ids of an earlier version: the same mites' ids now
            renamed = _rekeyed_scores(run / SCORES_DIRNAME, saved.get("mites", []),
                                      _read_dataset(run.name, recordings_root)["mites"])
        except (OSError, ValueError) as error:
            renamed = 0
            report(f"{run.name}: its cached scores keep their names ({error})")
        if renamed:
            report(f"{run.name}: {renamed} cached scores renamed to today's ids of its mites")
        remove_tree(folder)
        report(f"{run.name}: brought home from {folder}")

    reports = library_dir / "reports"
    for item in sorted(reports.iterdir()) if reports.is_dir() else []:
        if item.is_dir() and any(item.glob("*.xlsx")):
            target = Path(results_root) / EARLIER_REPORTS / item.name
        elif item.is_file():
            target = Path(results_root) / SCRIPTS_OUTPUT_DIRNAME / item.name
        else:
            remove_tree(item, ignore_errors=True)  # a session that made no report
            continue
        if target.exists():
            report(f"left {item}: {target} already exists")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item), target)
    for folder in (reports, library_dir):
        if folder.is_dir() and not any(folder.iterdir()):
            remove_tree(folder, ignore_errors=True)
    if not library_dir.exists():
        report(f"removed {library_dir}")


# --- evaluation -------------------------------------------------------------------------


def _metric_version(metric, params, mites, stabilize=False):
    """Changes whenever the scores of these mites could: another metric, other
    parameters, plate stabilization switched, an edit to the scoring code, or
    other mites."""
    source = inspect.getsource(Analyzer) + inspect.getsource(plate_stabilizer)
    key = json.dumps([metric, params, source, [[m["id"], m["x"], m["y"], m["r"]] for m in mites]]
                     + ([True] if stabilize else []), sort_keys=True)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def mite_boxes(mites, pad=0):
    """Mite id to (x1, y1, x2, y2): the same box around each saved mite as
    Mite.get_ROI() cuts in an analysis run, grown by `pad` pixels on each side.
    x1 and y1 can be negative; the caller cuts them off at the image's edge."""
    return {
        m["id"]: (int(round(m["x"] - m["r"])) - pad, int(round(m["y"] - m["r"])) - pad,
                  int(round(m["x"] + m["r"])) + pad, int(round(m["y"] + m["r"])) + pad)
        for m in mites
    }


def _measure_mites(dataset, recordings_dir, measure, pad=0, stabilize=False):
    """Per recording of a dataset, in order: {mite id: measure(its patch)}, the
    patch being the mite's box grown by `pad` in every frame, as an analysis run
    cuts it. Slow: every frame is decoded, a recording at a time (the next one
    while this one is measured), and only the part of the image holding mites
    is kept; the mites of a recording are measured side by side. With
    `stabilize`, the cuts follow a shaking plate, as mite.stabilize_plate makes
    an analysis run cut them."""
    loader = open_recordings(recordings_dir)
    boxes = mite_boxes(dataset["mites"], pad)
    # Stabilizing reads a little around each cut; keep real pixels there.
    margin = STABILIZE_MARGIN if stabilize else 0
    x0 = max(0, min(box[0] for box in boxes.values()) - margin)
    y0 = max(0, min(box[1] for box in boxes.values()) - margin)
    x_end = max(box[2] for box in boxes.values()) + margin
    y_end = max(box[3] for box in boxes.values()) + margin
    local = {mite_id: (x1 - x0, y1 - y0, x2 - x0, y2 - y0)
             for mite_id, (x1, y1, x2, y2) in mite_boxes(dataset["mites"]).items()}

    def measured(frames):
        shifts = PlateStabilizer().shifts(frames, list(local.values())) if stabilize else None

        def one(mite_id):
            x1, y1, x2, y2 = boxes[mite_id]
            if shifts is None:
                return measure(frames[:, max(0, y1) - y0:y2 - y0, max(0, x1) - x0:x2 - x0])
            return measure(PlateStabilizer.cut(frames, local[mite_id], pad, shifts))

        return dict(zip(boxes, side_by_side(one, boxes)))

    loads = (partial(loader.load_recording_region, recording["name"], x0, y0, x_end, y_end)
             for recording in dataset["recordings"])
    for frames in one_ahead(loads):
        yield measured(frames)


def _check_recordings(dataset, recordings_dir, what):
    if not Path(recordings_dir).is_dir():
        raise FileNotFoundError(
            f"The recordings of {dataset['name']} are no longer at {dataset['data_dir']}, so {what}."
        )


def _score_mites(dataset, metric, recordings_dir, params=None, stabilize=False):
    """Score every mite of a dataset in every recording with `metric` and its
    `params`: mite id to one score per recording (see _measure_mites())."""
    _check_recordings(dataset, recordings_dir, f"its mites cannot be scored with {metric}")
    scores = {mite["id"]: [] for mite in dataset["mites"]}

    def score(roi):
        return round(float(Analyzer._motion_score(roi, metric, params)), 3)

    for recording in _measure_mites(dataset, recordings_dir, score, Analyzer.roi_padding(metric, params), stabilize):
        for mite_id, value in recording.items():
            scores[mite_id].append(value)
    return scores


def _brightness_mites(dataset, recordings_dir, pad=0, stabilize=False):
    """The brightness of every mite's patch in every recording, as an analysis
    run records it with the score (Analyzer.score_pool()): mite id to one mean
    pixel value per recording."""
    _check_recordings(dataset, recordings_dir, "the brightness of its mites cannot be measured")
    brightness = {mite["id"]: [] for mite in dataset["mites"]}

    def mean(roi):
        return round(Analyzer.brightness(np.asarray(roi, dtype=np.float32)), 3)

    for recording in _measure_mites(dataset, recordings_dir, mean, pad, stabilize):
        for mite_id, value in recording.items():
            brightness[mite_id].append(value)
    return brightness


def _dataset_brightness(key, dataset, pad, stabilize=False):
    """The brightness of the dataset's mites, from the cache when exactly these
    patches were measured before."""
    version = hashlib.sha1(json.dumps(
        [inspect.getsource(plate_stabilizer), pad, bool(stabilize),
         [[m["id"], m["x"], m["y"], m["r"]] for m in dataset["mites"]]]).encode("utf-8")).hexdigest()[:12]
    cache = _scores_dir(dataset) / f"brightness-{version}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))["brightness"]
    brightness = _brightness_mites(dataset, Path(dataset["data_dir"]), pad, stabilize)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"brightness": brightness}), encoding="utf-8")
    return brightness


def _normalised_scores(key, dataset, scores, normalizer, pad, stabilize):
    """A dataset's scores as the analysis of a folder would have them with
    `normalizer`: over the dataset's recordings, the mites marked not a mite
    left out of it, as an analysis leaves them out."""
    if not normalizer.active:
        return scores
    brightness = _dataset_brightness(key, dataset, pad, stabilize) if normalizer.brightness else None
    n_recordings = len(dataset["times"])
    mites = [mite["id"] for mite in dataset["mites"]
             if not calibration.is_rejected(calibration.per_recording(dataset["truth"].get(mite["id"]), n_recordings))]
    normalised = normalizer.by_mite({mite_id: scores[mite_id] for mite_id in mites},
                                    brightness and {mite_id: brightness[mite_id] for mite_id in mites})
    return {**scores, **{mite_id: [round(value, 3) for value in values] for mite_id, values in normalised.items()}}


def _dataset_scores(key, dataset, metric, params, stabilize=False):
    """The dataset's mites scored with `metric` and `params`, from the cache when
    exactly this metric, with these parameters, this plate stabilization and
    this scoring code, has scored them before. The cache is only a shortcut:
    deleting it just means decoding the recordings again."""
    version = _metric_version(metric, params, dataset["mites"], stabilize)
    cache = _scores_dir(dataset) / f"{version}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))["scores"]
    scores = _score_mites(dataset, metric, Path(dataset["data_dir"]), params, stabilize)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"metric": metric, "params": params, "scores": scores}), encoding="utf-8")
    return scores


def _benchmark_mites(dataset, recordings_dir):
    """Whether the benchmark (classes/benchmark.py) calls each mite of a dataset
    moving in each recording: mite id to one True or False per recording. Slow:
    every frame is decoded and denoised, in the part of the image holding mites."""
    _check_recordings(dataset, recordings_dir, "the benchmark cannot be run on them")
    loader = open_recordings(recordings_dir)
    boxes = mite_boxes(dataset["mites"])
    x0 = max(0, min(box[0] for box in boxes.values()) - Benchmark.MARGIN)
    y0 = max(0, min(box[1] for box in boxes.values()) - Benchmark.MARGIN)
    x_end = max(box[2] for box in boxes.values()) + Benchmark.MARGIN
    y_end = max(box[3] for box in boxes.values()) + Benchmark.MARGIN
    local = {mite_id: (x1 - x0, y1 - y0, x2 - x0, y2 - y0) for mite_id, (x1, y1, x2, y2) in boxes.items()}

    calls = {mite_id: [] for mite_id in boxes}
    for recording in dataset["recordings"]:
        frames = loader.load_recording_region(recording["name"], x0, y0, x_end, y_end)
        for mite_id, moving in Benchmark.calls(frames, local).items():
            calls[mite_id].append(moving)
    return calls


def _dataset_benchmark(key, dataset):
    """The benchmark's calls for the dataset's mites, from the cache when this
    benchmark code has called exactly these mites before."""
    source = inspect.getsource(benchmark_module)
    version = hashlib.sha1(json.dumps(
        [source, [[m["id"], m["x"], m["y"], m["r"]] for m in dataset["mites"]]]).encode("utf-8")).hexdigest()[:12]
    cache = _scores_dir(dataset) / f"benchmark-{version}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))["calls"]
    calls = _benchmark_mites(dataset, Path(dataset["data_dir"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"benchmark": Benchmark.NAME, "calls": calls}), encoding="utf-8")
    return calls


def _benchmark_circles(recordings_dir, recording_name):
    """The circles the benchmark draws on one recording (Benchmark.circles()).
    Slow: every whole frame is decoded and denoised. None for a session saved
    as the mites' ROIs: there are no whole frames to draw them on."""
    if is_roi_session(recordings_dir):
        return None
    return Benchmark.circles(DataLoader(recordings_dir, grayscale=True).load_recording(recording_name))


def _dataset_circles(key, dataset, recording):
    """The benchmark's circles on one recording of the dataset, from the cache
    when this benchmark code has drawn them before; None when the recording's
    frames are gone, so there is nothing to draw them from."""
    name = dataset["recordings"][recording]["name"]
    version = hashlib.sha1(json.dumps([inspect.getsource(benchmark_module), name]).encode("utf-8")).hexdigest()[:12]
    cache = _scores_dir(dataset) / f"benchmark-circles-{version}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))["circles"]
    try:
        circles = _benchmark_circles(Path(dataset["data_dir"]), name)
    except FileNotFoundError:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"benchmark": Benchmark.NAME, "recording": name, "circles": circles}), encoding="utf-8")
    return circles


def _last_recording(dataset, scores, threshold, benchmark=None, circles=None):
    """The last recording of a dataset as its callers see it, for the test
    report: every mite not marked "not a mite" with its box (x1, y1, x2, y2),
    its score there, the detector's call at `threshold` and its label, None
    when it has none there. With `benchmark` (its calls, see
    _dataset_benchmark()) each mite also has the benchmark's call, and
    `circles` are what the benchmark draws on that recording, each of radius
    "circle_radius" (see _dataset_circles())."""
    n_recordings = len(dataset["times"])
    last = n_recordings - 1
    boxes = mite_boxes(dataset["mites"])
    mites = []
    for mite in dataset["mites"]:
        states = calibration.per_recording(dataset["truth"].get(mite["id"]), n_recordings)
        if calibration.is_rejected(states):
            continue
        score = scores[mite["id"]][last]
        mites.append(
            {
                "id": mite["id"],
                "zone_id": mite["zone_id"],
                "box": list(boxes[mite["id"]]),
                "score": score,
                "call": calibration.MOVING if score >= threshold else calibration.STILL,
                "movement": states[last],
                **({} if benchmark is None else {
                    "benchmark_call": calibration.MOVING if benchmark[mite["id"]][last] else calibration.STILL}),
            }
        )
    return {
        "recording": last,
        "recording_name": dataset["recordings"][last]["name"] if last < len(dataset["recordings"]) else "",
        "time": dataset["times"][last],
        "mites": mites,
        "circles": circles,
        "circle_radius": Benchmark.CIRCLE,
    }


def _observations(dataset, dataset_key, scores, benchmark=None):
    """One row per (mite, recording) of a dataset labelled moving or still, and
    the number of mites marked not a mite and of unlabelled mite-recordings.
    With `benchmark` (its calls, see _dataset_benchmark()), each row also says
    what the benchmark called it."""
    times = dataset["times"]
    n_recordings = len(times)
    groups = {zone["id"]: zone["label"] or UNLABELED for zone in dataset["zones"]}
    recording_names = [recording["name"] for recording in dataset["recordings"]]
    recording_names += [""] * (n_recordings - len(recording_names))
    rows, n_rejected, n_unlabelled = [], 0, 0
    for mite in dataset["mites"]:
        states = calibration.per_recording(dataset["truth"].get(mite["id"]), n_recordings)
        if calibration.is_rejected(states):
            n_rejected += 1
            continue
        for recording, movement in enumerate(states):
            if movement is None:
                n_unlabelled += 1
                continue
            rows.append(
                {
                    "dataset": dataset_key,
                    "dataset_name": dataset["name"],
                    "recording_name": recording_names[recording],
                    "mite_id": mite["id"],
                    "zone_id": mite["zone_id"],
                    "group": groups.get(mite["zone_id"], UNLABELED),
                    "x": mite["x"],
                    "y": mite["y"],
                    "recording": recording,
                    "time": times[recording],
                    "movement": movement,
                    "score": scores[mite["id"]][recording],
                    **({} if benchmark is None else {
                        "benchmark_call": calibration.MOVING if benchmark[mite["id"]][recording] else calibration.STILL}),
                }
            )
    return rows, n_rejected, n_unlabelled


def _pooled_times(datasets):
    """Recordings are pooled by their order; each gets the mean of its times."""
    n_recordings = max(len(dataset["times"]) for dataset in datasets)
    times = []
    for recording in range(n_recordings):
        here = [dataset["times"][recording] for dataset in datasets if recording < len(dataset["times"])]
        times.append(round(float(np.mean(here)), 2))
    return times


def _n_mites(rows):
    return len({(row["dataset"], row["mite_id"]) for row in rows})


def _calibration_by_zone(rows):
    """Per zone of each dataset, at the threshold in use: the movement labels and
    how many the detector called wrong, each way."""
    zones = []
    for dataset, zone_id in sorted({(row["dataset"], row["zone_id"]) for row in rows}):
        here = [row for row in rows if row["dataset"] == dataset and row["zone_id"] == zone_id]
        zones.append(
            {
                "dataset": dataset,
                "dataset_name": here[0]["dataset_name"],
                "id": zone_id,
                "group": here[0]["group"],
                "n_mites": _n_mites(here),
                "n_moving": sum(row["movement"] == calibration.MOVING for row in here),
                "n_still": sum(row["movement"] == calibration.STILL for row in here),
                "moving_called_still": sum(row["outcome"] == "moving_called_still" for row in here),
                "still_called_moving": sum(row["outcome"] == "still_called_moving" for row in here),
            }
        )
    return zones


def _rounded(values, digits=4):
    return [None if value is None else round(float(value), digits) for value in values]


def movement_scores():
    """The metrics a calibration can score with -- for each its name, a one-line
    description, its default parameters, which of them are whole numbers and
    its parameters after config.yaml's -- and the metric, parameters and
    threshold in use."""
    mite = get_default_config().mite
    return {
        "metrics": [
            {
                "name": name,
                "description": Analyzer.metric_description(name),
                "defaults": Analyzer.metric_defaults(name),
                # JSON does not tell 0.0 from 0, and the page has to know which of the two to ask for
                "whole": [param for param, value in Analyzer.metric_defaults(name).items() if isinstance(value, int)],
                "params": Analyzer.check_metric_params(name, mite.params_for(name)),
            }
            for name in Analyzer.metric_names()
        ],
        "in_use": _in_use(mite),
    }


def _in_use(mite):
    return {
        "metric": mite.metric,
        "params": Analyzer.check_metric_params(mite.metric, mite.params_for(mite.metric)),
        "threshold": float(mite.motion_threshold),
        "stabilize_plate": bool(mite.stabilize_plate),
        "normalize_brightness": bool(mite.normalize_brightness),
        "normalize_floor": bool(mite.normalize_floor),
        # the band around the threshold whose calls are checked by eye: [low, high], or None
        "review_band": list(mite.review_band_for(mite.metric) or []) or None,
    }


# Checks by eye per mite the band suggested with a threshold may ask for, unless the report is asked for another number.
REVIEW_CHECKS = 0.5
# Edges tried on each side of the threshold for that band.
REVIEW_BAND_STEPS = 24


def _suggested_band(runs, threshold, checks_per_mite):
    """The band to check by eye that goes with a suggested threshold, for a
    calibration report: the one with the smallest death error among those asking
    for at most `checks_per_mite` checks per mite, the labels standing in for
    the eye (death_calibration.best_band()), with what it leaves:

        {checks_allowed, low, high, mae, checks_per_mite, exact,
         frontier: what the checks buy (death_calibration.checks_frontier()), up
                   to four times the checks allowed}

    low == high when no band does better than the threshold alone."""
    threshold = round(threshold, 3)
    grid = death_calibration.band_grid(runs, threshold, REVIEW_BAND_STEPS)
    low, high = death_calibration.best_band(runs, threshold, checks_per_mite, grid=grid)
    low, high = min(round(low, 3), threshold), max(round(high, 3), threshold)
    shown = max(4 * checks_per_mite, 2.0)

    def rounded(band):
        return {"low": round(band["low"], 3), "high": round(band["high"], 3), "mae": round(band["mae"], 3),
                "checks_per_mite": round(band["checks_per_mite"], 3), "exact": round(band["exact"], 4)}

    return {"checks_allowed": checks_per_mite,
            **rounded({"low": low, "high": high, **death_calibration.band_outcome(runs, low, high)}),
            "frontier": [rounded(band) for band in death_calibration.checks_frontier(grid)
                         if band["checks_per_mite"] <= shown]}


def _resolve_metric(metric, params):
    """The metric to score with and all its parameters: the one in config.yaml
    unless `metric` is given; its defaults, then config.yaml's values for it,
    then `params`."""
    mite = get_default_config().mite
    metric = metric or mite.metric
    if metric not in Analyzer.metric_names():
        raise ValueError(f"Unknown movement score {metric!r}; choose one of {', '.join(Analyzer.metric_names())}.")
    return metric, Analyzer.check_metric_params(metric, {**mite.params_for(metric), **(params or {})})


def evaluate_calibration(out_dir, datasets, metric=None, params=None, recordings_root=RECORDINGS_ROOT,
                         stabilize=None, benchmark=False, normalize_brightness=None, normalize_floor=None,
                         checks_per_mite=None):
    """Score the saved mites with a metric and compare the scores with the
    movement the user saw, pooled over the saved datasets whose ids are in
    `datasets`.

    The metric is the one in config.yaml unless `metric` is given, with its
    parameters overridden by `params` (e.g. {"n": 20} for topN_variability), so
    other movement scores can be tried without editing the file; likewise
    `stabilize` (following a shaking plate, see PlateStabilizer) is config.yaml's
    mite.stabilize_plate unless given, and `normalize_brightness` and
    `normalize_floor` (the scores of each dataset put on one scale for every
    mite, as the analysis of a folder does, see ScoreNormalizer) config.yaml's
    too. The threshold "in use" is always config.yaml's; it only fits these
    scores when the metric, parameters, stabilization and normalisations are
    config.yaml's too, which `threshold_fits` says.

    Each (mite, recording) labelled moving or still is one observation; the
    detector calls it moving when that recording's score reaches the threshold.
    Mites marked "not a mite" are left out entirely. Scoring decodes a dataset's
    recordings the first time it meets a version of the metric; later evaluations
    reuse those scores. Recordings are pooled by their order (first, second, ...)
    for the fraction moving over time.

    Returns the confusion counts at the threshold in use and, when there are
    both moving and still labels, the ROC curve and the suggested threshold with
    its confusion counts: the one that puts the mites' deaths closest to where
    the labels put them (death_calibration.best_threshold()), as in a long run
    the one that best tells moving from still recording by recording puts many
    deaths late. Also the fraction of mites moving per recording and the
    Kaplan-Meier survival curves (of the mites seen moving at least once) by the
    labels and by the detector; how far the detector puts each mite's death from
    where the labels put it, in recordings ("death_error", see
    calibration.death_errors()) and, with a suggested threshold, that error by
    threshold around the two ("death_curve", see death_calibration.death_curve())
    and the band around it to check by eye, for `checks_per_mite` checks per
    mite at most (REVIEW_CHECKS unless given; "review_band", see
    _suggested_band()); every observation with its outcome; and, where a poke
    test was entered, the survival of the poked mites by the pokes and by the
    detector at the threshold in use ("poke", see _poke_survival()).
    Everything is also written to calibration.xlsx in `out_dir`, a moment later:
    the workbook takes longer to write than the report to work out, so the page
    has the report first (results_file() waits for the workbook).

    With `benchmark`, the same observations are also called by the Discobox's
    original software (classes/benchmark.py): its confusion counts, with
    precision, recall and F1 as for the detector, come as "benchmark", and its
    survival curve and its death errors join the others. Slow the first time a dataset meets it.
    """
    ids = list(dict.fromkeys(datasets))
    if not ids:
        raise ValueError("Choose at least one dataset.")
    loaded = [_read_dataset(key, recordings_root) for key in ids]
    metric, params = _resolve_metric(metric, params)
    in_use = _in_use(get_default_config().mite)
    checks_per_mite = REVIEW_CHECKS if checks_per_mite is None else float(checks_per_mite)
    if not 0 <= checks_per_mite <= 100:
        raise ValueError("The checks allowed per mite must be between 0 and 100.")
    stabilize = in_use["stabilize_plate"] if stabilize is None else bool(stabilize)
    normalizer = ScoreNormalizer(
        floor=in_use["normalize_floor"] if normalize_floor is None else normalize_floor,
        brightness=in_use["normalize_brightness"] if normalize_brightness is None else normalize_brightness)
    current = in_use["threshold"]
    times = _pooled_times(loaded)
    n_recordings = len(times)

    rows, n_rejected, n_unlabelled, summaries, poked = [], 0, 0, [], []
    for key, dataset in zip(ids, loaded):
        scores = _dataset_scores(key, dataset, metric, params, stabilize)
        scores = _normalised_scores(key, dataset, scores, normalizer, Analyzer.roi_padding(metric, params),
                                    stabilize)
        called = _dataset_benchmark(key, dataset) if benchmark else None
        here, rejected, unlabelled = _observations(dataset, key, scores, called)
        last = len(dataset["times"]) - 1
        circles = _dataset_circles(key, dataset, last) if benchmark and last < len(dataset["recordings"]) else None
        rows += here
        poked += _poked_mites(dataset, scores, current)
        n_rejected += rejected
        n_unlabelled += unlabelled
        summaries.append(
            {
                "id": key,
                "name": dataset["name"],
                "data_dir": dataset["data_dir"],
                "n_observations": len(here),
                "n_mites": _n_mites(here),
                # enough to draw the dataset's plate on its own preview
                "image": dataset["image"],
                "zones": [{k: zone[k] for k in ("id", "x1", "y1", "x2", "y2")} for zone in dataset["zones"]],
                # its last recording, every mite with the call at the threshold in use and the benchmark's
                "last_recording": _last_recording(dataset, scores, current, called, circles),
            }
        )
    if not rows:
        raise ValueError("Mark at least one mite moving or still first.")

    scores = np.array([row["score"] for row in rows])
    is_moving = np.array([row["movement"] == calibration.MOVING for row in rows], dtype=bool)
    both = calibration.has_both_classes(is_moving)
    runs = death_calibration.runs_of_rows(rows)
    suggested = death_calibration.best_threshold(runs)[0] if both else None

    thresholds = {"current": current}
    if suggested is not None:
        thresholds["suggested"] = suggested
    for row in rows:
        is_moving_row = row["movement"] == calibration.MOVING
        row["outcome"] = calibration.outcome(is_moving_row, row["score"], current)
        if suggested is not None:
            row["outcome_suggested"] = calibration.outcome(is_moving_row, row["score"], suggested)

    def over_time(subset):
        curves = calibration.moving_over_time(subset, n_recordings, thresholds)
        return {key: values if key == "n" else _rounded(values) for key, values in curves.items()}

    def survival(subset):
        curves = calibration.survival_curves(subset, times, thresholds,
                                             {"benchmark": "benchmark_call"} if benchmark else None)
        return {name: {key: _rounded(value, 2) if isinstance(value, list) else value for key, value in curve.items()}
                for name, curve in curves.items()}

    roc = None
    if both:
        fpr, tpr, roc_thresholds = calibration.roc_curve(scores, is_moving)
        roc = {
            "fpr": _rounded(fpr),
            "tpr": _rounded(tpr),
            # the first point is at an infinite threshold, which JSON cannot hold
            "thresholds": [None if np.isinf(t) else round(float(t), 3) for t in roc_thresholds],
        }

    result = {
        "metric": metric,
        "metric_params": params,
        "stabilize_plate": stabilize,
        "normalize_brightness": normalizer.brightness,
        "normalize_floor": normalizer.floor,
        "in_use": in_use,
        "threshold_fits": (metric == in_use["metric"] and params == in_use["params"]
                           and stabilize == in_use["stabilize_plate"]
                           and normalizer.brightness == in_use["normalize_brightness"]
                           and normalizer.floor == in_use["normalize_floor"]),
        "datasets": summaries,
        "times": times,
        "threshold": current,
        "suggested_threshold": None if suggested is None else round(suggested, 3),
        "auc": calibration.auc(scores, is_moving) if both else None,
        "roc": roc,
        "n_mites": _n_mites(rows),
        "n_moving": int(is_moving.sum()),
        "n_still": int((~is_moving).sum()),
        "n_not_a_mite": n_rejected,
        "n_unlabelled": n_unlabelled,
        "current": calibration.confusion(scores, is_moving, current),
        "best": calibration.confusion(scores, is_moving, suggested) if suggested is not None else None,
        # the same observations as called by the Discobox's original software
        "benchmark": {
            "name": Benchmark.NAME,
            "threshold": Benchmark.THRESHOLD,
            **calibration.calls_confusion([row["benchmark_call"] == calibration.MOVING for row in rows], is_moving),
        } if benchmark else None,
        "moving_over_time": over_time(rows),
        # the survival curves by the labels and by the detector, see calibration.survival_curves()
        "survival": survival(rows),
        # how far the detector, and the benchmark, put each mite's death from the labels', in recordings
        "death_error": {name: {key: value if value is None or isinstance(value, int) else round(value, 3)
                               for key, value in errors.items()}
                        for name, errors in calibration.death_errors(
                            rows, thresholds, {"benchmark": "benchmark_call"} if benchmark else None).items()},
        # the death error by threshold, around the one in use and the suggested one: what the suggestion is chosen on
        "death_curve": death_calibration.death_curve(runs, [current, suggested]) if suggested is not None else None,
        # the band around the suggested threshold to check by eye, and what the checks buy
        "review_band": _suggested_band(runs, suggested, checks_per_mite) if suggested is not None else None,
        "groups": [
            {
                "group": group,
                "n_mites": _n_mites([row for row in rows if row["group"] == group]),
                **over_time([row for row in rows if row["group"] == group]),
                "survival": survival([row for row in rows if row["group"] == group]),
            }
            for group in sorted({row["group"] for row in rows})
        ],
        "observations": rows,
        "zones": _calibration_by_zone(rows),
        # where the calls at the threshold in use go wrong, for the test report's map
        "error_map": ErrorMap(rows).describe(),
        # the survival of the mites poked by hand, by the pokes and by the detector at the threshold in use; None without a poke test
        "poke": _poke_survival(poked, times),
    }
    # each outcome as a fraction of its row, for the confusion matrices and the ROC curve
    result["rates"] = {key: None if result[key] is None else calibration.outcome_rates(result[key]) for key in ("current", "best")}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    result["excel"] = reporting.CALIBRATION_EXCEL_NAME
    _files_later.later(_draft_key(out_dir), lambda: reporting.write_calibration_excel(result, out_dir))
    return result


def save_threshold(value):
    """Make `value` the movement threshold for every analysis from now on."""
    return save_motion_threshold(value)


def save_movement_score(metric, params, threshold, stabilize=None, normalize_brightness=None, normalize_floor=None,
                        review_band=None):
    """Make `metric` with `params`, and `threshold` on its scale, the movement
    score of every analysis from now on; with `stabilize`, plate stabilization
    on or off too, and with `normalize_brightness` and `normalize_floor` the
    normalisations of a folder's scores (each left as it is when None). With
    `review_band` ([low, high], holding the threshold), the band whose calls are
    checked by eye is saved with them (classes/review_band.py); without it, the
    metric's band stays as it is, and is not used while the threshold is
    outside it."""
    metric, params = _resolve_metric(metric, params)
    if not float(threshold) > 0:
        raise ValueError("The threshold must be positive.")
    return app_config.save_movement_score(metric, params, threshold, stabilize_plate=stabilize,
                                          normalize_brightness=normalize_brightness, normalize_floor=normalize_floor,
                                          review_band=review_band)


# --- TEMPORARY: checking the ground truth where the labels overlap ---------------------
#
# The page web/static/overlap.html lists the mite-recordings whose score lies where
# those labelled moving and those labelled still overlap (classes/truth_overlap.py),
# plays each one cut close around its mite, and lets its label be changed. A change
# is saved at once, where save_truth() saves. To take the page out again, delete
# this block with the two imports only it uses (tempfile and TruthOverlap), its
# routes in web/server.py, classes/truth_overlap.py, web/static/overlap.html,
# web/static/js/overlap/ and unit_tests/truth_overlap_test.py.

OVERLAP_METRIC = "outline_variability"
# The clips the page plays: a cache, made again when missing.
OVERLAP_DIR = Path(tempfile.gettempdir()) / "varroa_truth_overlap"
_OVERLAP_LETTERS = {calibration.MOVING: "m", calibration.STILL: "s"}


def _overlap_states(states, n_recordings):
    """A mite's statuses as one letter per recording: m, s, or - for neither."""
    return "".join(_OVERLAP_LETTERS.get(state, "-") for state in calibration.per_recording(states, n_recordings))


def truth_overlap(datasets=None, low=None, high=None, beyond=True, metric=OVERLAP_METRIC,
                  recordings_root=RECORDINGS_ROOT):
    """The mite-recordings to check by eye: those whose score lies where the
    scores labelled moving and those labelled still overlap, pooled over the
    saved datasets whose ids are in `datasets` (all of them by default).

    They are scored with `metric` and config.yaml's parameters for it, plate
    stabilization and normalisations, as a calibration report scores them
    (slow the first time a dataset meets them, see evaluate_calibration()).
    The overlap is the band of scores TruthOverlap suggests unless `low` and
    `high` give another; with `beyond`, the recordings beyond it on the wrong
    side are listed too.

    Returns TruthOverlap.describe(), each datapoint with its mite's radius "r",
    and with it the metric and its parameters, every saved dataset with whether
    it is among the chosen, and for each mite with a datapoint
    ("<dataset id>/<mite id>") its statuses (_overlap_states()) and scores in
    every recording."""
    saved = list_calibration_datasets(recordings_root)
    ids = [summary["id"] for summary in saved] if datasets is None else list(dict.fromkeys(datasets))
    if not ids:
        raise ValueError("Choose at least one dataset.")
    metric, params = _resolve_metric(metric, None)
    in_use = _in_use(get_default_config().mite)
    stabilize = in_use["stabilize_plate"]
    normalizer = ScoreNormalizer(floor=in_use["normalize_floor"], brightness=in_use["normalize_brightness"])

    rows, loaded = [], {}
    for key in ids:
        dataset = _read_dataset(key, recordings_root)
        scores = _dataset_scores(key, dataset, metric, params, stabilize)
        scores = _normalised_scores(key, dataset, scores, normalizer, Analyzer.roi_padding(metric, params),
                                    stabilize)
        rows += _observations(dataset, key, scores)[0]
        loaded[key] = (dataset, scores, {mite["id"]: mite["r"] for mite in dataset["mites"]})
    if not rows:
        raise ValueError("Mark at least one mite moving or still first.")

    overlap = TruthOverlap(rows).describe(low, high, beyond)
    mites = {}
    for point in overlap["datapoints"]:
        dataset, scores, radius = loaded[point["dataset"]]
        point["r"] = radius[point["mite_id"]]
        mites.setdefault(f"{point['dataset']}/{point['mite_id']}", {
            "states": _overlap_states(dataset["truth"].get(point["mite_id"]), len(dataset["times"])),
            "scores": scores[point["mite_id"]],
        })
    return {
        "metric": metric,
        "metric_params": params,
        "datasets": [{**{key: summary[key] for key in ("id", "name", "n_recordings", "n_moving", "n_still")},
                      "chosen": summary["id"] in ids} for summary in saved],
        **overlap,
        "mites": mites,
    }


def overlap_clip(dataset, mite_id, recording, recordings_root=RECORDINGS_ROOT):
    """Frames of one mite during one recording of a saved dataset, cut close
    around it (see _mite_clip()), kept in OVERLAP_DIR."""
    saved = _read_dataset(dataset, recordings_root)
    mite = next((mite for mite in saved["mites"] if mite["id"] == str(mite_id)), None)
    if mite is None:
        raise ValueError(f"No mite {mite_id} in {saved['name']}.")
    if not 0 <= recording < len(saved["recordings"]):
        raise ValueError(f"No recording {recording} in {saved['name']}.")
    recordings_dir = Path(saved["data_dir"])
    _check_recordings(saved, recordings_dir, "there is no clip to play")
    return _mite_clip(recordings_dir, saved["recordings"][recording], mite, OVERLAP_DIR, f"{dataset}_r{recording}")


def set_overlap_label(dataset, mite_id, recording, state, recordings_root=RECORDINGS_ROOT):
    """Give one mite of a saved dataset the label `state` in one recording
    ("moving", "still", or None for unlabelled) and save it at once, next to the
    recordings, on top of what is saved now
    (update_ground_truth() does the same for a calibration session). Returns
    the label and the mite's statuses as saved (_overlap_states())."""
    if state not in (calibration.MOVING, calibration.STILL, None):
        raise ValueError(f"A label here is moving, still or none, not {state!r}.")
    saved = _read_dataset(dataset, recordings_root)
    stored = {key: saved[key] for key in ("data_dir", "times", "recordings", "image", "zones", "mites")}
    n_recordings = len(stored["times"])
    mite_id = str(mite_id)
    if all(mite["id"] != mite_id for mite in stored["mites"]):
        raise ValueError(f"No mite {mite_id} in {saved['name']}.")
    if not 0 <= recording < n_recordings:
        raise ValueError(f"No recording {recording} in {saved['name']}.")

    truth = _saved_truth(stored)
    if calibration.is_rejected(truth.get(mite_id)):
        raise ValueError(f"Mite {mite_id} is marked not a mite; take that back on the ground-truth page first.")
    truth[mite_id] = calibration.apply_changes(truth.get(mite_id), {recording: state}, n_recordings)
    if not any(any(states) for states in truth.values()):
        raise ValueError(f"That is the last label of {saved['name']}; delete its ground truth on the calibration page instead.")
    labelled = _write_ground_truth(stored, truth)
    return {"movement": state, "states": _overlap_states(labelled.get(mite_id), n_recordings)}


# --- live runs ----------------------------------------------------------------------
#
# A live run is a Discobox test run: the camera streams all the time for the live
# feed, and every `recording_timeout` minutes the fan and LEDs come on and a burst
# of frames is recorded. Each burst is analysed as soon as it is complete, by the
# same core as a folder (MotionAnalysis), and its results are described by the same
# _arrange() and _results() as run_analysis() uses, so the live pages are the
# folder pages, filling in. The bursts are saved, as the Discobox app saves them, to
# recordings/<run name>/, which is then a folder like any other: folder mode reads
# it back and gets exactly the same results. Its results go to results/<run name>/.
#
# The plate labels and "not a mite" marks of a run live in its folder, as for any
# folder, so the label page works on a live run unchanged. So does run.json: how
# the run was made (the camera, frames dropped), kept up to date
# after every recording.

CameraError = live_camera.CameraError  # the camera or Vimba X cannot be used


class LiveRunNotOpen(ValueError):
    """No live run is open by that id: closed, or the server restarted since."""
LIVE_SETTINGS_FILE = APP_DIR / "settings.txt"
SETTINGS_FILENAME = ".settings.txt"
RUN_INFO_NAME = "run.json"
LIVE_FEED_WIDTH = 960
LIVE_STATES = ("running", "paused", "stopping")
LEDS = ("led1", "led2")
# Seconds for the camera's automatic exposure to follow the LEDs coming on.
LIGHTS_SETTLE = 1.5

_live = {}  # live id -> the run's parts
_live_lock = threading.Lock()


def _setting_ranges():
    return {name: {"label": label, "unit": unit, "min": low, "max": high}
            for name, (label, unit, low, high) in SETTING_RANGES.items()}


def live_options(settings_path=LIVE_SETTINGS_FILE, recordings_root=RECORDINGS_ROOT):
    """What the live page offers before a run: the cameras (or why there are none),
    the serial ports, the saved test-run settings with their ranges, and a run
    name not taken yet."""
    cameras, camera_error = [], None
    try:
        cameras = live_camera.list_cameras()
    except live_camera.CameraError as error:
        camera_error = str(error)
    return {
        "cameras": cameras,
        "camera_error": camera_error,
        "serial_ports": serial_ports(),
        "settings": Settings.from_file(settings_path).as_dict(),
        "plan": Settings.from_file(settings_path).plan(),
        "ranges": _setting_ranges(),
        "run_name": default_run_name(recordings_root),
        "recordings_root": str(recordings_root),
        "open": [live_status(live_id) for live_id in list(_live)],
    }


def print_cameras():
    """Print every camera Vimba X sees, as the Discobox app's --list does."""
    live_camera.print_cameras()


def default_run_name(recordings_root=RECORDINGS_ROOT):
    """test_run_<today>, as the Discobox app names a run, with a number added if
    that name is taken."""
    base = f"test_run_{date.today():%Y-%m-%d}"
    name, number = base, 1
    while (Path(recordings_root) / name).exists():
        number += 1
        name = f"{base}_{number}"
    return name


def _run_dir_for(run_name, recordings_root):
    """The folder of a test run called `run_name`, a name no recording has yet."""
    run_name = (run_name or "").strip()
    if not run_name:
        raise ValueError("Enter a name for the test run.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", run_name) or run_name.endswith("."):
        raise ValueError("A test run name may only hold letters, digits, spaces, dots, dashes and underscores.")
    run_dir = Path(recordings_root) / run_name
    if run_dir.exists():
        raise ValueError(f"A recording called {run_name} already exists in {recordings_root}.")
    return run_dir


def save_live_settings(values, live_id=None, settings_path=LIVE_SETTINGS_FILE):
    """Change the saved test-run settings (only the names in `values`), checked
    against their ranges; with an open live run not started yet, it uses them
    too, and the camera takes the new frame rate at once."""
    settings = Settings.from_dict({**Settings.from_file(settings_path).as_dict(), **values})
    run = _live.get(live_id) if live_id else None
    if run is not None and run.session.state != "ready":
        raise ValueError("The settings cannot change while the test run is going on.")
    settings.save(settings_path)
    if run is not None:
        fps_changed = settings.fps != run.source.settings.fps
        run.source.settings = settings
        if fps_changed:
            run.source.set_fps(settings.fps)
        if settings.zones_per_plate != run.layout.zones_per_plate:
            _set_live_layout(run, ZoneLayout(settings.zones_per_plate))
    return settings.as_dict()


def live_plan(settings):
    """Settings.plan() of `settings` (name -> value): how long each recording and
    the whole test run take."""
    return Settings.from_dict(settings).plan()


def open_live(live_id, out_dir, run_name, camera_id=None, serial_port="auto", save_frames=True,
              settings_path=LIVE_SETTINGS_FILE, settings=None, recordings_root=RECORDINGS_ROOT,
              results_root=RESULTS_ROOT, coords_file=None):
    """Open the camera, with the fan and LEDs, for a live run called `run_name`,
    whose recordings go to recordings_root/run_name and whose results go to
    `out_dir` (by default results_root/run_name). The live feed starts, with
    both LEDs on so the plates can be seen; nothing is recorded until
    start_live(), which switches them off and leaves them to the test run. Until
    then the run's name and whether it is saved can still change
    (set_live_options()), and so can its settings (save_live_settings()).
    Only one live run can be open: opening another closes the one that is open,
    unless that one is running.

    The test run's settings are those saved in `settings_path`, with `settings`
    (name -> value, e.g. {"fps": 30}) overriding them for this run only. Its
    zones per plate are among them."""
    with _live_lock:
        for other_id, other in list(_live.items()):
            if other.session.state in LIVE_STATES:
                raise ValueError(f"The test run {other.run_dir.name} is still going on; stop it first.")
            _close_live(other_id)

        settings = Settings.from_dict({**Settings.from_file(settings_path).as_dict(), **(settings or {})})
        camera_id = live_camera.choose_camera(camera_id)
        lights = open_lights(serial_port)
        live_source = CameraSource(camera_id, settings, lights)
        layout = ZoneLayout(settings.zones_per_plate)

        run_dir = None
        try:
            run_dir = _run_dir_for(run_name, recordings_root)
            run_dir.mkdir(parents=True)
            live_source.open()
        except Exception:
            lights.close()
            if run_dir is not None:
                shutil.rmtree(run_dir, ignore_errors=True)
            raise
        # Without its LEDs the Discobox is dark: both stay on, for the camera's
        # image and for labelling, until the run starts and switches them itself.
        _leds_on(lights, settings)

        # Results in results/<run name>/ follow the run when it is renamed.
        own_results = out_dir is None
        out_dir = results_dir(run_dir, results_root) if own_results else Path(out_dir)
        new_results = not out_dir.exists()
        _clear_clips(out_dir)
        # With the run's folder from the start: its plate labels go by the layout.
        layout.save(run_dir)
        run = SimpleNamespace(
            live_id=live_id, source=live_source, lights=lights, run_dir=run_dir,
            out_dir=out_dir, results_root=Path(results_root) if own_results else None, new_results=new_results,
            save_frames=bool(save_frames),
            coords_file=coords_file, layout=layout, feed=(None, None), feed_lock=threading.Lock(), started_at=None,
            movement=(0, -1), preview_written=False, files_due=None,
        )
        run.analysis = analysis = MotionAnalysis(_live_zone_manager(run))
        live_source.movement = lambda: run.movement
        run.session = LiveSession(live_source, analysis, publish=lambda session, write: _publish_live(run, write),
                                  on_finish=lambda session: _live_run_ended(run))
        _live[live_id] = run
    return live_status(live_id)


def set_live_options(live_id, run_name=None, save_frames=None):
    """Change what open_live() was told of a live run not started yet: its name
    (its folder in recordings/ takes it, with the plate labels and marks already
    in it, and so does its results folder unless one was given) and whether its
    recordings are saved. What is None stays as it is."""
    with _live_lock:
        run = _get_live(live_id)
        if run.session.state != "ready":
            raise ValueError("The test run has started: its name and whether it is saved can no longer change.")
        if run_name is not None and run_name.strip() != run.run_dir.name:
            _rename_live(run, run_name)
        if save_frames is not None:
            run.save_frames = bool(save_frames)
    return live_status(live_id)


def _rename_live(run, run_name):
    run_dir = _run_dir_for(run_name, run.run_dir.parent)
    with run.session.lock:
        run.run_dir.rename(run_dir)
        run.run_dir = run_dir
        if run.results_root is None:
            return
        old, run.out_dir = run.out_dir, results_dir(run_dir, run.results_root)
        made, run.new_results = run.new_results, not run.out_dir.exists()
        _clear_clips(run.out_dir)
        if old.is_dir():
            # the picture the label page shows, and what was read from it
            shutil.copytree(old, run.out_dir, dirs_exist_ok=True)
            if made:  # results of an earlier recording of the old name are not this run's to remove
                shutil.rmtree(old, ignore_errors=True)


def _live_zone_manager(run):
    return _build_zone_manager(run.coords_file or run.layout.coords_file)


def _set_live_layout(run, layout):
    """Cut the plates of a live run not started yet into other zones: nothing is
    analysed yet, so its analysis starts again on them."""
    with run.session.lock:
        run.layout = layout
        layout.save(run.run_dir)
        run.analysis = run.session.analysis = MotionAnalysis(_live_zone_manager(run))
    _clear_clips(run.out_dir)


def _get_live(live_id):
    run = _live.get(live_id)
    if run is None:
        raise LiveRunNotOpen("This live run is not open any more.")
    return run


def _leds_on(lights, settings):
    """Switch on the LEDs that are off, at their set intensity. True if any was
    off. A failure is only logged: the camera works without its light."""
    if not lights.connected:
        return False
    off = [device for device in LEDS if not lights.on[device]]
    try:
        for device in off:
            lights.switch(device, True, getattr(settings, device))
    except Exception:
        _logger.exception("Could not switch the LEDs on")
        return False
    return bool(off)


def _light_for_labelling(run):
    """The mites can only be found on a lit plate: before the run starts, switch
    on any LED that is off, and give the camera's exposure time to follow."""
    if run.session.state == "ready" and _leds_on(run.lights, run.source.settings):
        time.sleep(LIGHTS_SETTLE)


# Seconds at most between two writes of a live run's workbook and figures while it
# goes on. On a long run they take seconds of work, which grows with every
# recording: too much to do after each one. A download waits for them
# (results_file()), and the end of the run writes them at once.
LIVE_FILES_EVERY = 600


def _publish_live(run, write_files):
    """The results of a live run so far, exactly as run_analysis() describes a
    folder: the same labels and "not a mite" marks, read from the run's folder.
    After each recording (`write_files`), run.json says how far the run got,
    and the files follow (_write_live_files_later())."""
    labels = load_labels(run.run_dir)
    recordings = list(run.session.recordings)
    # A call corrected after the run's end writes the files again, and nothing else.
    going = write_files and run.session.state != "finished"
    if going:  # even if no results can be described, these recordings are analysed
        run.movement = (len(recordings), run.movement[1])
    _arrange(run.analysis, run.run_dir, labels, True)
    # The scores are normalised over a whole run, so not while it goes on.
    results = _results(_run_view(run.analysis, _live_frames(run)), run.out_dir, labels, False,
                       corrections=CallCorrections(run.run_dir), normalizer=ScoreNormalizer())
    if write_files:
        if not run.preview_written:  # the first frame, which the pages draw on: it never changes
            _write_preview(run.analysis.first_frame, run.out_dir)
            run.preview_written = True
        _write_live_files_later(run)
    if going:
        run.movement = (len(recordings), _last_movement(results, recordings))
        _write_run_info(run)
    return results


def _live_run_ended(run):
    """The test run is over: its run.json says so, and its last files are
    written before the session counts as finished."""
    _write_run_info(run, ended=True)
    finish_files(run.out_dir)


def _write_live_files_later(run):
    """Write a live run's workbook and figures in the background: at most
    LIVE_FILES_EVERY seconds after the recording that first changed them, and
    at once when its stream has ended. They all go through _files_later, one
    after another, so the last written is always of the latest results."""
    if run.source.state == "finished":
        delay = 0.0
    else:
        now = time.monotonic()
        if run.files_due is None:
            run.files_due = now + LIVE_FILES_EVERY
        delay = max(0.0, run.files_due - now)
    _files_later.later(_draft_key(run.out_dir), lambda: _write_live_files(run), delay)


def _live_frames(run):
    """What a live run saves of its recordings (see _run_view()): the mites' ROIs, or nothing."""
    return "rois" if run.save_frames else "none"


def _last_movement(results, recordings):
    """The last of `recordings` (names, in order) in which any mite moved, from
    0; -1 if none did. A result's times are its recordings', in minutes from
    the start of the first."""
    moved = [time for index, time in enumerate(results["times"])
             if any(mite["moving"][index] for mite in results["mites"])]
    if not moved or not recordings:
        return -1
    first = DataLoader.parse_start_time(recordings[0])
    starts = [(DataLoader.parse_start_time(name) - first).total_seconds() / 60 for name in recordings]
    return max(index for index, start in enumerate(starts) if start <= moved[-1] + 1e-3)


def _write_run_info(run, ended=False):
    """Write run.json next to the recordings: how the test run was made, and how
    far it got. Never fails the run: it is only a record."""
    if run.started_at is None or not run.run_dir.is_dir():
        return
    try:
        status = run.session.status()
        info = {
            "source": status["source"],
            "camera": status["camera"],
            "started_at": run.started_at,
            "ended_at": datetime.now().isoformat(timespec="seconds") if ended else None,
            "recordings_planned": status["recordings"],
            "recordings_analysed": status["analysed"],
            "frames_saved": run.save_frames,
            "frames_dropped": status["dropped"],
            "frames_incomplete": status["incomplete"],
            "error": status["error"] or status["save_error"],
        }
        path = run.run_dir / RUN_INFO_NAME
        partial = path.with_name(path.name + ".part")
        partial.write_text(json.dumps(info, indent=2), encoding="utf-8")
        partial.replace(path)
    except Exception:
        _logger.exception("Could not write %s", RUN_INFO_NAME)


def live_preview(live_id, out_dir=None):
    """Detect the mites on a frame so the plates can be labelled, as
    open_session() does for a folder: on the newest frame before the run, and on
    the frame the run's results come from once it has one."""
    run = _get_live(live_id)
    with run.session.lock:
        frame = run.analysis.first_frame
    if frame is None:
        _light_for_labelling(run)
        _count, frame = run.source.latest.get()
        if frame is None:
            raise ValueError("No frame has come from the camera yet.")
    out_dir = Path(out_dir or run.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_preview(frame, out_dir)
    zone_manager = _live_zone_manager(run)
    detect_mites(zone_manager, frame, Analyzer())
    return _session_view(zone_manager, frame, run.run_dir, run.source.completed)


def live_read_labels(live_id, out_dir, mites):
    """read_labels() for a live run: the names on the picture live_preview() made."""
    run = _get_live(live_id)
    return _read_labels(_live_zone_manager(run), run.run_dir, out_dir or run.out_dir, mites)


def set_live_light(live_id, device, on=None, level=None):
    """Switch the fan on or off, or set the intensity of the fan or of an LED,
    to check the settings before the run. Both LEDs stay on until it starts."""
    run = _get_live(live_id)
    if device not in DEVICES:
        raise ValueError(f"Unknown device {device!r}; it is one of {', '.join(DEVICES)}.")
    if run.session.state != "ready":
        raise ValueError("The fan and LEDs are the test run's to switch while it is going on.")
    if device in LEDS and on is False:
        raise ValueError("Both LEDs stay on until the test run starts.")
    if on is None:
        run.lights.set_level(device, level)
    elif on:
        run.lights.switch(device, True, level)
    else:
        run.lights.switch_off(device)
    return run.lights.state()


def start_live(live_id, labels=None):
    """Start the test run: record, analyse and publish results as it goes.
    `labels`, when given, are saved as the run's plate labels first."""
    run = _get_live(live_id)
    if run.session.state != "ready":
        raise ValueError("This test run has already been started.")
    if labels is not None:
        save_labels(run.run_dir, labels)
    run.lights.all_off()  # the LEDs, and the fan if it was switched on to check it: the test run's from here on
    (run.run_dir / SETTINGS_FILENAME).write_text(run.source.settings_text, encoding="utf-8")
    if run.save_frames:
        RoiVideo.check_codec(run.run_dir)
    run.session.recorder = Recorder(run.run_dir) if run.save_frames else None
    run.started_at = datetime.now().isoformat(timespec="seconds")
    _write_run_info(run)
    try:
        run.session.start()
    except Exception:
        if run.session.recorder is not None:
            run.session.recorder.close()
            run.session.recorder = None
        raise
    return live_status(live_id)


def mites_alive(results, death_minutes):
    """{alive, mites}: of the results' mites in the study (seen moving at least
    once), how many are alive in their last recording, by the rule of the
    survival charts (classes/survival.py): a mite that moved in it, or has not
    yet been still for `death_minutes` since its last movement."""
    survival = SurvivalAnalysis(results["times"], death_minutes)
    movings = SurvivalAnalysis.study([mite["moving"] for mite in results["mites"]])
    return {"alive": survival.alive_count(movings, len(results["times"]) - 1), "mites": len(movings)}


def live_status(live_id):
    run = _get_live(live_id)
    results = run.session.results
    alive = None
    if results is not None:
        alive = mites_alive(results, death_minutes(run.run_dir))
    status = {
        **run.session.status(),
        "live_id": live_id,
        "run_name": run.run_dir.name,
        "run_dir": str(run.run_dir),
        "out_dir": str(run.out_dir),
        "save_frames": run.save_frames,
        "zones_per_plate": run.layout.zones_per_plate,
        "alive": alive,  # the mites alive now, of those in the study; None before the first results
    }
    # the progress bar over the live result pages
    return {**status, "progress": RunProgress(status).describe()}


def live_results(live_id):
    """The results published last (None before the first recording is
    analysed), and their version, which changes with every update."""
    run = _get_live(live_id)
    return {"version": run.session.version, "results": run.session.results}


def live_correct_call(live_id, mite_id, recording, state=None, checked=False):
    """correct_call() for a live run: the results published next, at once, follow
    the change. Once the run is over, the workbook and the figures are written
    again too, a moment later as correct_call() does; before, they are after
    every recording anyway."""
    run = _get_live(live_id)
    with run.session.lock:
        _change_call(run.analysis.zone_manager, CallCorrections(run.run_dir), mite_id, int(recording), state,
                     checked=checked)
    run.session.publish(write_files=False)
    if run.session.state == "finished":
        _files_later.later(_draft_key(run.out_dir), lambda: _write_live_files(run))
    return live_results(live_id)


def open_live_calibration(live_id, out_dir):
    """A calibration session on a live run's recordings, to enter their ground
    truth and poke test while the run goes on: open_calibration() of the run's
    folder, but of the recordings analysed so far alone, the one being captured
    left out. grow_live_calibration() adds the recordings that come after. The
    ground truth is judged on the recordings' clips and kept with them, so the
    run must save its recordings."""
    run = _get_live(live_id)
    if not run.save_frames:
        raise ValueError("This test run does not save its recordings, so there is no clip to enter a ground truth "
                         "on and no folder to keep it in.")
    names = list(run.session.recordings)
    if not names:
        raise ValueError("The ground truth and the poke test can be entered once the first recording is analysed.")
    stored = _calibration_session(run.run_dir, run.coords_file, out_dir, names)
    return _opened_calibration(stored, out_dir)


def grow_live_calibration(out_dir, live_id):
    """Bring a calibration session made by open_live_calibration() up to the
    recordings its live run has analysed since: they come unlabelled, and the
    ground truth's changes not saved yet stay (TruthDraft.grow()). Returns the
    session as open_live_calibration() does. A session showing another dataset
    by now, e.g. one a pooled report opened, is left as it is."""
    run = _get_live(live_id)
    stored = _read_calibration_session(out_dir)
    names = list(run.session.recordings)
    if Path(stored["data_dir"]) == run.run_dir.resolve() and len(names) > len(stored["recordings"]):
        stored.update(_calibration_recordings(run.run_dir, names))
        _write_calibration_session(out_dir, stored)
        draft = _draft(out_dir)
        with _drafts_lock:
            draft.grow(len(stored["times"]))
    return {**_calibration_view(stored, _saved_truth(stored)), "truth_view": truth_view(out_dir)}


def _write_live_files(run):
    """The workbook and the figures of a live run, as its recordings and
    corrections are now. The lock is held only to read the run, not while the
    files are written."""
    run.files_due = None  # a recording from now on is in the next write
    with run.session.lock:
        view = _run_view(run.analysis, _live_frames(run))
        mite_data, _changes = _mite_table(view, CallCorrections(run.run_dir), ScoreNormalizer())
        annotated = _annotated(view)
    _write_files(annotated, run.out_dir, mite_data)


def live_refresh(live_id):
    """Describe the results again, e.g. after the plate labels changed."""
    run = _live.get(live_id)
    if run is not None:
        run.session.publish(write_files=False)


def live_frame(live_id, width=LIVE_FEED_WIDTH):
    """The newest frame as JPEG bytes, at most `width` pixels wide (None before
    the first frame). Encoded once per frame and width, whoever asks."""
    run = _get_live(live_id)
    count, image = run.source.latest.get()
    if image is None:
        return None
    width = max(64, min(int(width), 4096))
    with run.feed_lock:
        key, data = run.feed
        if key == (count, width):
            return data
        if image.shape[1] > width:
            height = round(image.shape[0] * width / image.shape[1])
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        data = encoded.tobytes() if ok else None
        run.feed = ((count, width), data)
        return data


def pause_live(live_id):
    _get_live(live_id).session.pause()
    return live_status(live_id)


def resume_live(live_id):
    _get_live(live_id).session.resume()
    return live_status(live_id)


def stop_live(live_id, wait=False, timeout=None):
    """Stop the test run: capture stops, the frames already captured are analysed
    and saved, and the final results written. With `wait`, returns when done."""
    _get_live(live_id).session.stop(wait=wait, timeout=timeout)
    return live_status(live_id)


def close_live(live_id):
    """Stop the run if it is going on, release the camera and the fan and LEDs,
    and forget the run. A run folder with nothing recorded in it is removed."""
    with _live_lock:
        _close_live(live_id)


def _close_live(live_id):
    run = _live.pop(live_id, None)
    if run is None:
        return
    run.session.stop(wait=True, timeout=60)
    run.source.wait_closed(30)
    run.lights.close()
    if run.run_dir.is_dir() and not open_recordings(run.run_dir).recording_names:
        shutil.rmtree(run.run_dir, ignore_errors=True)


def live_running():
    """Whether a live run is recording, paused or finishing."""
    return any(run.session.state in LIVE_STATES for run in list(_live.values()))


def close_all_live():
    """Stop every live run cleanly and release the camera: on shutdown. The
    files a correction left to write are written first."""
    finish_files()
    with _live_lock:
        for live_id in list(_live):
            _close_live(live_id)


# --- the recordings kept ------------------------------------------------------------
#
# recordings/ holds every recording session the app has: each live test run and
# each folder dropped into the page. The pages list them with how they were
# recorded, so any of them can be analysed, or calibrated on, again.


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def list_recordings(recordings_root=RECORDINGS_ROOT, results_root=RESULTS_ROOT):
    """Every folder in `recordings_root` that holds a recording, the most recently
    recorded first, as describe_recording() describes it, and whether it is the
    live run being recorded now."""
    root = Path(recordings_root)
    if not root.is_dir():
        return []
    finish_files()  # a list of the results on disk: those still to be written are, first
    recording_now = {run.run_dir.resolve() for run in list(_live.values()) if run.session.state in LIVE_STATES}
    listed = []
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        try:
            described = describe_recording(folder, results_root)
        except Exception:  # one odd folder must not hide the others
            _logger.exception("Could not describe the recording %s", folder)
            continue
        if described is not None:
            now = folder.resolve() in recording_now
            listed.append({**described, "recording_now": now, "state": RecordingInfo.state(described["run"], now)})
    return sorted(listed, key=lambda entry: entry["started"], reverse=True)


def plan_upload(name, files, uploads_root=RECORDINGS_ROOT):
    """Which files of the folder `name` dropped into the page to copy, of `files`
    ([{path, size}], every file in it): {name (of the folder they go to in
    `uploads_root`), data_dir (that folder), missing ([{path (as dropped),
    target (in that folder)}])}. See classes/upload_plan.py."""
    plan = UploadPlan(name, files)
    folder = Path(uploads_root) / plan.name

    def size_of(target):
        path = folder.joinpath(*target.split("/"))
        return path.stat().st_size if path.is_file() else None

    # recordings dropped before, whose frames were shrunk to the mites' surroundings since
    converted = set(RoiRecordings(folder).recording_names) if is_roi_session(folder) else set()
    return {"name": plan.name, "data_dir": str(folder), "missing": plan.missing(size_of, converted)}


def finish_upload(name, uploads_root=RECORDINGS_ROOT):
    """Once every file of a dropped folder is in: its recordings of whole frames
    are shrunk to what a live run saves, the mites' surroundings
    (classes/roi_conversion.py), so they take a thirtieth of the space and give
    the same results. {data_dir, converted (recordings)}."""
    UploadPlan.check_part(name)
    folder = Path(uploads_root) / name
    if not folder.is_dir():
        raise FileNotFoundError(f"Nothing was copied to {folder}.")
    return {"data_dir": str(folder), "converted": convert_folder(folder)}


def convert_folder(folder, results_root=RESULTS_ROOT):
    """Shrink the recordings of whole frames in `folder` to the mites'
    surroundings (classes/roi_conversion.py). Returns how many were."""
    folder = Path(folder)
    converted = RoiConversion(folder, _build_zone_manager(_coords_file(folder))).run()
    if converted:
        # clips of the whole frames, which are gone: those of its analysis and of its calibration
        _clear_clips(results_dir(folder, results_root))
        _clear_clips(results_dir(folder, results_root) / CALIBRATION_DIRNAME)
    return converted


def convert_stored_recordings(recordings_root=RECORDINGS_ROOT, results_root=RESULTS_ROOT, report=None):
    """Shrink every recording folder in `recordings_root` to the mites'
    surroundings. Only for scripts/convert_stored_recordings.py, run before the
    server starts: nothing may read a folder while it changes. `report(text)`
    hears of each folder. Returns {folder: recordings converted, or the error}."""
    report = report or (lambda text: None)
    todo = [folder for folder in sorted(Path(recordings_root).iterdir()) if folder.is_dir()] \
        if Path(recordings_root).is_dir() else []
    done = {}
    for folder in todo:
        if not DataLoader(folder).recording_names:
            continue  # no whole frames left
        frames = sum(path.stat().st_size for path in folder.rglob("*.bmp"))
        report(f"Shrinking {folder} ({frames / 1e9:.1f} GB of frames)...")
        try:
            done[str(folder)] = convert_folder(folder, results_root)
        except Exception as error:  # the next folder all the same; this one stays as it was, or carries on next time
            _logger.exception("Could not shrink %s", folder)
            done[str(folder)] = f"{type(error).__name__}: {error}"
        report(f"  {done[str(folder)]}" if isinstance(done[str(folder)], str) else
               f"  {done[str(folder)]} recordings shrunk" if done[str(folder)] else "  left whole: no mites found")
    if any(isinstance(result, int) and result for result in done.values()):
        # the pooled reports' clips, cut from frames that are gone: remade from the ROIs when asked for
        for clips in Path(results_root).glob(f"{POOLED_DIRNAME}/*/{CLIPS_DIRNAME}"):
            remove_tree(clips, ignore_errors=True)
    return done


def describe_recording(data_dir, results_root=RESULTS_ROOT):
    """One recording folder as the list of recordings shows it (None when it holds
    no recording): when it was recorded, how -- the Discobox settings of its
    .settings.txt and, for a live run, its run.json -- and what the app has of it:
    plate labels, ground truth and results."""
    data_dir = Path(data_dir)
    loader = open_recordings(data_dir)
    recordings = loader.recording_names
    if not recordings:
        return None
    first, last = recordings[0], recordings[-1]
    fps = loader.get_fps(first)
    frames = loader.count_frames(first)
    ended = DataLoader.parse_start_time(last) + timedelta(seconds=loader.count_frames(last) / loader.get_fps(last))

    run = _read_json(data_dir / RUN_INFO_NAME)
    if not isinstance(run, dict):
        run = None
    labels = _read_json(_layout_file(data_dir, LABELS_FILENAME), {})
    groups = [str(group).strip() for group in labels.values() if str(group).strip()] if isinstance(labels, dict) else []
    truth = [entry.get("truth") for entry in _folder_truth(data_dir) if isinstance(entry, dict)]
    rejected = sum(calibration.is_rejected(value) for value in truth)
    labelled = sum(1 for value in truth
                   if not calibration.is_rejected(value) and any(calibration.per_recording(value, len(recordings))))
    workbook = results_dir(data_dir, results_root) / reporting.EXCEL_NAME
    started = DataLoader.parse_start_time(first)
    # as the Discobox app saved them; None for a folder without .settings.txt
    # the zones per plate are the analysis's, told apart below
    settings = {name: loader.settings[name] for name in ("recording_count", *SETTING_RANGES)
                if name in loader.settings and name != ZoneLayout.SETTING} or None
    return {
        "name": data_dir.name,
        "path": str(data_dir.resolve()),
        "started": started.isoformat(timespec="seconds"),
        "ended": ended.isoformat(timespec="seconds"),
        # between the times shown, to the second
        "seconds": (ended.replace(microsecond=0) - started.replace(microsecond=0)).total_seconds(),
        "n_recordings": len(recordings),
        "planned": RecordingInfo.planned(run, settings),
        "frames": frames,
        "fps": fps,
        "settings": settings,
        "zones_per_plate": zones_per_plate(data_dir),
        "lights": RecordingInfo.lights(settings),
        "run": run,
        "n_labelled_plates": len(groups),
        "groups": sorted(set(groups)),
        "n_not_a_mite": rejected,
        "n_ground_truth": labelled,
        "results": None if not workbook.is_file() else {
            "file": workbook.name,
            "saved_at": datetime.fromtimestamp(workbook.stat().st_mtime).isoformat(timespec="seconds"),
        },
    }


def recording_results_file(name, filename, results_root=RESULTS_ROOT):
    """The path of one file of a recording's results: results/<name>/<filename>."""
    for part in (name, filename):
        if not part or part in (".", "..") or Path(part).name != part:
            raise ValueError(f"Bad name: {part}")
    path = results_file(Path(results_root) / name, filename)
    if not path.is_file():
        raise FileNotFoundError(f"{name} has no {filename}.")
    return str(path)


# --- the folders of earlier versions ------------------------------------------------
#
# Earlier versions saved live runs to output/, copied dropped folders to uploads/,
# and gave every page session a folder named by a random id in outputs/.
# tidy_folders() moves all of it into today's folders, once, when the app starts.

OLD_RECORDING_FOLDERS = ("output", "uploads")
OLD_RESULTS_FOLDER = "outputs"
EARLIER_SESSIONS = "earlier sessions"  # results/earlier sessions/: outputs/, as it was


def _shown(path, app_dir):
    try:
        return Path(path).relative_to(app_dir).as_posix()
    except ValueError:
        return str(path)


def _subfolders(folder):
    return sorted(path for path in Path(folder).iterdir() if path.is_dir()) if Path(folder).is_dir() else []


def _move(folder, target, app_dir, done):
    """Rename `folder` to `target` unless `target` is taken; True if moved."""
    if target.exists():
        done.append(f"left {_shown(folder, app_dir)} where it is: {_shown(target, app_dir)} already exists")
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(target)
    except OSError as error:
        done.append(f"could not move {_shown(folder, app_dir)}: {error}")
        return False
    done.append(f"moved {_shown(folder, app_dir)} to {_shown(target, app_dir)}")
    return True


def _remove_if_empty(folder):
    """Remove a folder that has been emptied. On Windows a read-only flag, which
    OneDrive sets on its folders, keeps even an empty folder: it is cleared first."""
    try:
        folder.rmdir()
    except PermissionError:
        if os.name != "nt":
            return
        try:
            os.chmod(folder, stat.S_IWRITE)
            folder.rmdir()
        except OSError:
            pass
    except OSError:  # not there, or not empty
        pass


def tidy_folders(app_dir=APP_DIR, recordings_root=RECORDINGS_ROOT, results_root=RESULTS_ROOT):
    """Move what earlier versions wrote into today's folders -- recordings from
    output/ and uploads/ to recordings/, outputs/ to results/earlier sessions/ --
    and remove the folders of pooled calibration reports that made no report.
    Nothing is overwritten: a folder whose new place is taken stays where it
    is. Returns a line for each thing done."""
    app_dir = Path(app_dir)
    done = []
    for old in OLD_RECORDING_FOLDERS:
        for folder in _subfolders(app_dir / old):
            _move(folder, Path(recordings_root) / folder.name, app_dir, done)
    for folder in _subfolders(app_dir / OLD_RESULTS_FOLDER):
        _move(folder, Path(results_root) / EARLIER_SESSIONS / folder.name, app_dir, done)
    for old in (*OLD_RECORDING_FOLDERS, OLD_RESULTS_FOLDER):
        _remove_if_empty(app_dir / old)
    # A pooled report's folder is only of use for its report.
    for folder in _subfolders(Path(results_root) / POOLED_DIRNAME):
        if not any(folder.glob("*.xlsx")):
            remove_tree(folder, ignore_errors=True)
    return done
