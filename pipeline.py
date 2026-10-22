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
    review_mites(...)          how many mites the result pages ask to check by eye, for some recordings
    save_review_mites(...)     change that number for them, or go back to config.yaml's
    review_again(...)          the results of a folder's last run again, with the calls to check as they are now
    analysis_clip(...)         frames of one recording, of one zone or the whole plate
    playback_timeline(...)     what the playback page plays of each recording, one after the other
    playback_sheet(...)        every mite of one zone in every frame of one recording, for the playback page
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
    save_live_settings(...)    change the test-run settings
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
    live_find_mites(...)       light the plates and detect mites not followed yet, to add during a run
    live_add_mites(...)        follow the mites chosen of those from the next recording on
    live_frame(...)            the newest frame as a JPEG, for the live feed
    pause_live / resume_live / stop_live / close_live

    list_recordings()          every recording kept in recordings/, with how it was recorded
    plan_upload(...)           which files of a folder dropped into the page to copy, and where
    results_dir(...)           where the analysis of a folder goes: results/<its name>/
    calibration_folder(...)    the folder in recordings/ a calibration works on (one elsewhere is copied in)
    calibration_dir(...)       where a calibration session of a recording works: results/<name>/calibration/
    new_pooled_report_dir()    a folder for a report pooled over several recordings
    remove_empty_pooled_reports()   the folders of pooled reports that made none, when the app starts

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
from classes import positions, settings_file
from classes.files import (read_json, remove_tree, try_json, write_image, write_image_whole, write_jpeg,
                           write_json)
from classes.follow_up import FollowUp
from classes.frame_source import RoiSource, open_source
from classes.kept_scores import KeptScores
from classes.label_reader import LabelReader, LabelReadError
from classes.live import camera as live_camera
from classes.live.lights import DEVICES, open_lights, serial_ports
from classes.live.progress import RunProgress, ZoneProgress
from classes.live.recorder import Recorder
from classes.live.session import LiveSession
from classes.live.settings import FIXED as FIXED_SETTINGS, RANGES as SETTING_RANGES, Settings
from classes.live.sources import CameraSource
from classes.mite import Mite
from classes.motion_analysis import DETECTION_LOCK, MotionAnalysis, detect_mites
from classes import outline_change as outline_change_module
from classes.outline_change import OutlineChange
from classes.outline_view import OutlineView
from classes.movement_stats import MovementReport
from classes.recording_info import RecordingInfo
from classes.roi_conversion import RoiConversion
from classes.roi_recordings import ROI_DIRNAME, RoiRecordings, RoiVideo, is_roi_session, open_recordings
from classes.review_band import ReviewBand
from classes.score_normalizer import ScoreNormalizer
from classes.survival import SurvivalReport
from classes.truth_draft import TruthDraft
from classes.unusual_activity import UnusualActivity
from classes.upload_plan import UploadPlan
from classes.workers import one_ahead, side_by_side
from classes.zone_layout import ZoneLayout
from classes.rect import Rect
from classes.zones import UNLABELED, ZoneManager, mite_ids

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
SETTINGS_FILENAME = settings_file.FILENAME  # the recordings' Discobox settings, with the app's own lines
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
# Pixels read around the scored patches when the plate is stabilized: a mite's
# shift (followed up to 12 px) and the Lanczos interpolation's reach.
STABILIZE_MARGIN = plate_stabilizer.MARGIN
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
    return read_json(_layout_file(data_dir, LABELS_FILENAME), {})


def save_labels(data_dir, labels):
    """Store zone labels next to the recordings so they survive a restart."""
    path = _layout_file(data_dir, LABELS_FILENAME)
    write_json(path, labels, indent=2)
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
    ids = try_json(_layout_file(data_dir, CONTROLS_FILENAME), [])
    return sorted({i for i in ids if isinstance(i, int)}) if isinstance(ids, list) else []


def save_controls(data_dir, controls):
    """Store the negative-control zones next to the recordings, beside the labels."""
    ids = sorted({int(i) for i in controls})
    write_json(_layout_file(data_dir, CONTROLS_FILENAME), ids)
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
    rejected = set(map(id, _rejected_detections(zone_manager, load_ground_truth(data_dir))))
    mites = [_mite_view(mite, zone.id, rejected=id(mite) in rejected) for zone in zone_manager.zones for mite in zone.mites]

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


def _mite_view(mite, zone_id, **more):
    """A detected mite (a Mite) as the pages and the ground truth know it: {id,
    zone_id, x, y (its centre), r (half its box's width)}, and `more`."""
    x, y = mite.home
    return {"id": mite.text, "zone_id": zone_id, "x": round(float(x), 1), "y": round(float(y), 1),
            "r": round(float((mite.x2 - mite.x1) / 2), 1), **more}


def set_rejected(data_dir, x, y, rejected, restore=None, tolerance=positions.TOLERANCE):
    """Mark the detection at (x, y) as not a mite, or take that mark back.

    The mark goes into the session's ground truth, where an analysis run and a
    calibration both read it. Marking replaces any movement labels a calibration
    gave the detection and returns them (None if it had none). Taking the mark
    back puts back the labels passed as `restore`, so a detection marked by
    mistake and unmarked keeps its labels; without them it is left unlabelled.
    """
    data_dir = Path(data_dir)
    saved = load_ground_truth(data_dir)
    near = positions.within(saved, x, y, tolerance)
    nearest = positions.nearest(saved, x, y, tolerance)  # a detection matches only the nearest saved entry

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

    _write_truth(data_dir, saved)
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
    mite = _find(mites, mite_id, "this session", what="detection")
    key = (_draft_key(data_dir), mite["x"], mite["y"])
    restore = None if rejected else _replaced.pop(key, None)
    replaced = set_rejected(data_dir, mite["x"], mite["y"], rejected, restore)
    if rejected:
        _replaced[key] = replaced
    return detection_marks(data_dir, mites)


def detection_marks(data_dir, mites):
    """Which of the label page's `mites` are marked "not a mite" in the ground
    truth saved for `data_dir`, and how many mites each zone has left."""
    rejected = [entry for entry in load_ground_truth(data_dir) if calibration.is_rejected(entry.get("truth"))]
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
                              boxes=source.boxes if rois else None, known_blobs=source.blobs() if rois else None,
                              starts=source.starts if rois else None, placements=source.placements if rois else None)
    if rois and score:
        mite = analysis.analyzer.config.mite
        source.loader.check_margin(_metric_pad(mite) + (STABILIZE_MARGIN if mite.stabilize_plate else 0))
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
            analysis.restart(score=True)
            analysis.run(source.events())
            if kept is not None:
                kept.keep(key, analysis.mites, analysis.blobs)
    _arrange(analysis, data_dir, labels, reject)
    return _run_view(analysis, "rois" if rois else "whole", data_dir)


def _arrange(analysis, data_dir, labels, reject):
    """Name the zones by `labels` and, with `reject`, leave out the detections
    marked "not a mite" in the ground truth saved for `data_dir`, and the mites
    that flew off (classes/unusual_activity.py: their activity is worked out
    here, on every detection). Folder and live runs both go through here, so the
    same marks give the same results."""
    truth = load_ground_truth(data_dir) if reject else []

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
    return float(mite.radius) + _metric_pad(mite)


def _metric_pad(mite):
    """Pixels the metric in use (config.yaml's `mite`) reads round a mite's box."""
    return Analyzer.roi_padding(mite.metric, mite.params_for(mite.metric))


def _run_view(analysis, frames, data_dir=None):
    """`frames`: what was saved of the recordings, for the pages: "whole"
    frames, or the mites' "rois" alone (classes/roi_recordings.py); `data_dir`
    the recordings' folder, where a live run keeps the frames mites were added
    on (_added_previews())."""
    return SimpleNamespace(
        frames=frames,
        data_dir=data_dir,
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
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    write_image_whole(Path(out_dir) / PREVIEW_NAME, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])


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


def _review(run, mite_data, changes, data_dir):
    """The calls to check by eye (ReviewBand.describe()): those of the narrowest
    band around the threshold, shaped as config.yaml's, that asks about the
    mites to check for the recordings in `data_dir` (review_mites()); None when
    it asks about none."""
    mite = get_default_config().mite
    band = ReviewBand.fitted(mite_data, run.analyzer.config.mite.motion_threshold, review_mites(data_dir),
                             mite.review_band_for(mite.metric))
    return band.describe(mite_data, changes) if band is not None else None


def _change_call(zone_manager, corrections, mite_id, recording, state, detected=None, checked=False):
    """Make the mite `mite_id` `state` in `recording`, or step it to its next
    state without one (CallCorrections.change()). `detected` maps mite id to
    the detector's call per recording, where normalised scores make them other
    than the mite's own. With `checked` the call is kept as checked by eye."""
    mite = next((m for m in zone_manager.mites if m.text == str(mite_id)), None)
    if mite is None:
        raise ValueError(f"No mite {mite_id} in these results.")
    calls = mite.moving if detected is None else detected[mite.text]
    _check_recording(recording, len(calls), "these results")
    corrections.change(*mite.home, recording, bool(calls[recording]), state,
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


REVIEW_MITES = "review_mites"  # the line of a run's .settings.txt with its own number of mites to check


def review_mites(data_dir=None):
    """How many mites the result pages ask to check by eye for the recordings in
    `data_dir`: their own number, saved with them, or config.yaml's
    (mite.review_mites) without one or without `data_dir`."""
    default = max(0, int(get_default_config().mite.review_mites))
    return default if data_dir is None else settings_file.whole_number(data_dir, REVIEW_MITES, default)


def save_review_mites(data_dir, mites):
    """Make `mites` the number of mites to check by eye for the recordings in
    `data_dir`: the review_mites line of their .settings.txt. With None the
    line goes, and config.yaml's number holds again. Returns the number now."""
    if mites is None:
        settings_file.remove(data_dir, REVIEW_MITES)
        return review_mites(data_dir)
    value = _whole_number(mites, "The mites to check must be a whole number", 0)
    settings_file.save(data_dir, REVIEW_MITES, value)
    return value


def _whole_number(value, what, lowest, highest=None):
    """`value` as an int from `lowest` (to `highest`, if given), or a ValueError
    saying `what` (e.g. "The time must be a whole number of minutes") it must be."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what}.")
    if number != value or number < lowest or (highest is not None and number > highest):
        raise ValueError(f"{what}, {lowest} or more." if highest is None else f"{what} between {lowest} and {highest}.")
    return number


def review_again(out_dir):
    """The results of the last run written to `out_dir` again, with the calls to
    check by eye as they are now; None when that run is no longer kept."""
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
    return settings_file.whole_number(data_dir, "death_minutes", 0)


def death_minutes_range():
    """The least and the most a mite can be still to count as dead, in minutes."""
    _label, _unit, lowest, highest = SETTING_RANGES["death_minutes"]
    return [lowest, highest]


def save_death_minutes(data_dir, minutes):
    """Make `minutes` the time a mite must be still to count as dead for the
    recordings in `data_dir`: the death_minutes line of their .settings.txt,
    added or replaced, every other line kept as it is."""
    label, unit, lowest, highest = SETTING_RANGES["death_minutes"]
    value = _whole_number(minutes, f"{label} must be a whole number of {unit}", lowest, highest)
    settings_file.save(data_dir, "death_minutes", value)
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
    mite_data, changes = FollowUp.of(run.zone_manager.mites).censor(mite_data, changes)
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
    a live run. With mites to check by eye, they hold the calls to check
    ("review", see _review()): by the number saved with the recordings, which
    are where the corrections are kept."""
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
    if run.frames == "rois" and getattr(run, "data_dir", None) is not None:
        # The plate as it was in each recording, so a mite added during the run is
        # drawn where it can be seen: only a live run that added mites has them.
        previews = _added_previews(run.data_dir, out_dir, run.n_recordings, again=False)
        if any(name != PREVIEW_NAME for name in previews):
            results["previews"] = previews
    if getattr(run, "activity", None) is not None:
        results["activity"] = run.activity.describe()
    if normalizer is not None:
        results["normalization"] = normalizer.describe()
    review = _review(run, mite_data, changes, corrections.path.parent if corrections is not None else None)
    if review is not None:
        results["review"] = review
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
    truth holds one status per recording, as every window reads it."""
    return read_json(Path(data_dir) / GROUND_TRUTH_FILENAME, [])


def _write_truth(data_dir, entries):
    """Save ground truth (entries by position, as load_ground_truth() reads them)
    next to the recordings in `data_dir`."""
    write_json(Path(data_dir) / GROUND_TRUTH_FILENAME, entries)


def _rejected_detections(zone_manager, saved):
    """The detected mites the user marked as not being mites."""
    rejected = [entry for entry in saved if calibration.is_rejected(entry.get("truth"))]
    if not rejected:
        return []
    mites = zone_manager.mites
    described = [{"id": index, "x": m.home[0], "y": m.home[1]} for index, m in enumerate(mites)]
    matched = calibration.match_ground_truth(described, rejected, n_recordings=1)
    return [mites[index] for index in matched]


def _read_calibration_session(out_dir):
    stored = read_json(Path(out_dir) / CALIBRATION_SESSION_NAME)
    if stored is None:
        raise FileNotFoundError("This calibration session has no mites. Open the folder again.")
    return stored


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
        # the picture to draw each recording's mites on (_added_previews()); the first frame
        # throughout for a session written before it had them
        "previews": stored.get("previews") or [PREVIEW_NAME] * len(stored["times"]),
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
    stored["previews"] = _added_previews(data_dir, out_dir, len(stored["times"]))
    _write_calibration_session(out_dir, stored)
    return stored


def _added_previews(data_dir, out_dir, n_recordings, again=True):
    """The picture of the plate for each recording, for the calibration and
    result pages to draw the mites on: the first frame (PREVIEW_NAME), or from a
    recording a live run added mites in, the frame they were found on
    (live_add_mites()), copied to `out_dir` as preview_from_<recording>.jpg. So a
    mite is drawn where it can be seen. Without `again`, a copy already there
    stays: `out_dir` is the run's own (its results), where it can only be this
    run's, and a frame is final once its recording is analysed."""
    previews = [PREVIEW_NAME] * n_recordings
    folder = Path(data_dir) / ADDED_FRAMES_DIRNAME
    added = sorted((int(path.stem.split("_")[1]), path) for path in folder.glob("from_*.jpg")
                   if path.stem.split("_")[1].isdigit()) if folder.is_dir() else []
    for start, path in added:
        if start >= n_recordings:
            continue
        name = f"preview_from_{start}.jpg"
        if again or not (Path(out_dir) / name).is_file():  # anew: `out_dir` may have shown another dataset
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, Path(out_dir) / name)
        previews[start:] = [name] * (n_recordings - start)
    return previews


def _describe_calibration(data_dir, coords_file=None, names=None):
    """(stored, first frame): what a calibration session of `data_dir` is -- its
    recordings and their times, the image's size, the zones with their labels
    and the mites found on the first frame -- and that frame."""
    labels = load_labels(data_dir)
    run = _detect_and_score(data_dir, coords_file, labels, reject=False, score=False, names=names)

    # with the recordings a live run followed each in (calibration.followed()): from the
    # one it was added in (0 but for one added later), up to the one it counted dead from
    mites = [_mite_view(mite, zone.id, start=mite.start, stop=mite.stopped)
             for zone in run.zone_manager.zones for mite in zone.mites]
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
    write_json(Path(out_dir) / CALIBRATION_SESSION_NAME, stored)


def _find(items, item_id, where, what="mite"):
    """The item of `items` ({id, ...}) whose id is `item_id`, or a ValueError:
    no such `what` in `where`."""
    found = next((item for item in items if item["id"] == str(item_id)), None)
    if found is None:
        raise ValueError(f"No {what} {item_id} in {where}.")
    return found


def _check_recording(recording, count, where="this session"):
    """Refuse a recording index that is not one of `count`."""
    if not 0 <= recording < count:
        raise ValueError(f"No recording {recording} in {where}.")


def _recordings_dir(source, what):
    """The folder of the recordings of `source` (a calibration session or a
    dataset: its data_dir), or a FileNotFoundError: they are gone, so `what`."""
    folder = Path(source["data_dir"])
    if not folder.is_dir():
        of = f" of {source['name']}" if "name" in source else ""
        raise FileNotFoundError(f"The recordings{of} are no longer at {source['data_dir']}, so {what}.")
    return folder


def _kept_clip(out_dir, name, make):
    """What `make()` works out from the frames (a clip, the mites' outlines, a
    playback sheet), kept in out_dir/clips/ as `name`.json and read back from
    there after: the frames are read once. make() writes its pictures into
    clips/, which is there when it is called."""
    manifest = Path(out_dir) / CLIPS_DIRNAME / f"{name}.json"
    kept = read_json(manifest)
    if kept is not None:
        return kept
    manifest.parent.mkdir(parents=True, exist_ok=True)
    made = make()
    write_json(manifest, made)
    return made


def _square(mite, reach):
    """(x1, y1, x2, y2): `reach` pixels round the whole pixel nearest a mite's
    centre ({x, y}); x1 and y1 may be negative."""
    x, y = int(round(mite["x"])), int(round(mite["y"]))
    return x - reach, y - reach, x + reach, y + reach


def _bounds(boxes, margin=0):
    """(x0, y0, x_end, y_end): the region holding every one of `boxes` grown by
    `margin`, cut at the image's top left."""
    boxes = list(boxes)
    return (max(0, min(box[0] for box in boxes) - margin), max(0, min(box[1] for box in boxes) - margin),
            max(box[2] for box in boxes) + margin, max(box[3] for box in boxes) + margin)


def _local(boxes, x0, y0):
    """`boxes` (id to (x1, y1, x2, y2)) in a region whose top left is (x0, y0)."""
    return {key: (x1 - x0, y1 - y0, x2 - x0, y2 - y0) for key, (x1, y1, x2, y2) in boxes.items()}


def calibration_clip(out_dir, recording, zone_id):
    """Frames of one zone during one recording, so the user can see which mites move.

    Writes up to CLIP_MAX_FRAMES JPEG crops to `out_dir` (once; later calls reuse
    them) and returns their filenames, where the crop sits in the full image, and
    the delay between frames that plays them back in real time.
    """
    stored = _read_calibration_session(out_dir)
    _check_recording(recording, len(stored["recordings"]))
    zone = next((zone for zone in stored["zones"] if zone["id"] == zone_id), None)
    if zone is None:
        raise ValueError(f"No zone {zone_id} in this session.")

    # One session can switch between datasets, so clips are named after theirs.
    name = f"clip_{_clip_key(dataset_id(stored['data_dir']))}_r{recording}_z{zone_id}"
    source = stored["recordings"][recording]
    box = (zone["x1"] - CLIP_MARGIN, zone["y1"] - CLIP_MARGIN, zone["x2"] + CLIP_MARGIN, zone["y2"] + CLIP_MARGIN)
    # the recordings are only needed for a clip not kept yet
    return _write_clip(lambda: open_recordings(_recordings_dir(stored, "there is no clip to play")),
                       source["name"], source["fps"], box, out_dir, name)


def _clip_key(dataset):
    """A short name for `dataset` in its clips' file names: the clips sit in a
    session folder already named after it, and Windows (without long paths)
    refuses a path of more than 259 characters, which a long dataset name
    repeated in both reached."""
    return hashlib.sha1(str(dataset).encode("utf-8")).hexdigest()[:10]


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


def _where_in(loader, name, mite):
    """`mite` ({x, y}: where it was found) where it was in recording `name`:
    where a live run followed it to (RoiRecordings.centre_in()), else where it
    was found. What is cut round a mite from its frames is cut there."""
    if not isinstance(loader, RoiRecordings):
        return mite
    x, y = loader.centre_in(name, mite["x"], mite["y"])
    return {**mite, "x": x, "y": y}


def _mite_clip(recordings_dir, source, mite, out_dir, name):
    """Every frame of one recording (`source`: {name, fps}) cut MITE_CLIP_REACH
    pixels around `mite` ({x, y}, where it was found) where it was in that
    recording (_where_in()) and kept as it is (PNG), to judge by eye whether
    the mite moves, and one picture of how much each pixel varies over them
    (_variation_picture()). Written to out_dir/clips/ once, with a manifest
    `name`_x_y.json that later calls reuse; the name says where the cut is, so
    a mite detected anew elsewhere gets a new clip. Returns the files
    (relative to `out_dir`), where the cut sits in the image, the mite's centre
    in it ("mite": {x, y}, in image pixels) and the delay between frames that
    plays them in real time."""
    loader = open_recordings(recordings_dir)
    here = _where_in(loader, source["name"], mite)
    x1, y1, x2, y2 = _square(here, MITE_CLIP_REACH)
    x1, y1 = max(0, x1), max(0, y1)
    name = f"{name}_x{x1}_y{y1}"

    def make():
        frames = loader.load_recording_region(source["name"], x1, y1, x2, y2)
        names = [f"{CLIPS_DIRNAME}/{name}_{index:02d}.png" for index in range(len(frames))]
        for frame, frame_name in zip(frames, names):
            write_image(Path(out_dir) / frame_name, frame)
        variation = f"{CLIPS_DIRNAME}/{name}_variation.png"
        write_image(Path(out_dir) / variation, _variation_picture(frames))
        return {
            "frames": names,
            "variation": variation,
            "x": x1,
            "y": y1,
            "width": int(frames.shape[2]),
            "height": int(frames.shape[1]),
            "mite": {"x": here["x"], "y": here["y"]},
            "interval_ms": int(round(1000 / source["fps"])),
        }

    return _kept_clip(out_dir, name, make)


def calibration_mite_clip(out_dir, recording, mite_id):
    """Frames of one mite during one recording of a calibration session, cut
    close around it, for the ground-truth page (see _mite_clip())."""
    stored = _read_calibration_session(out_dir)
    _check_recording(recording, len(stored["recordings"]))
    mite = _find(stored["mites"], mite_id, "this session")
    recordings_dir = _recordings_dir(stored, "there is no clip to play")
    return _mite_clip(recordings_dir, stored["recordings"][recording], mite, out_dir,
                      f"mite_{_clip_key(dataset_id(stored['data_dir']))}_r{recording}")


def _write_clip(loader, recording_name, fps, box, out_dir, name, max_width=None):
    """Write up to CLIP_MAX_FRAMES JPEGs of the region `box` = (x1, y1, x2, y2) of
    one recording, and a manifest `name`.json that later calls reuse, to
    out_dir/clips/ (_kept_clip()). `loader` reads the recordings, or is called
    for the one that does when the clip is not kept yet.

    Returns the frame files (relative to `out_dir`), where the region sits in the
    full image (in full image pixels, even when `max_width` scales the frames
    down), and the delay between frames that plays them back in real time.
    """
    def make():
        reader = loader() if callable(loader) else loader
        _check_saved(reader, *box)
        n_frames = reader.count_frames(recording_name)
        step = max(1, int(np.ceil(n_frames / CLIP_MAX_FRAMES)))
        x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
        frames = reader.load_recording_region(recording_name, x1, y1, int(box[2]), int(box[3]), step=step)
        height, width = frames.shape[1:3]
        scale = min(1.0, max_width / width) if max_width else 1.0

        names = []
        for index, frame in enumerate(frames):
            if scale < 1:
                frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
            names.append(f"{CLIPS_DIRNAME}/{name}_{index:02d}.jpg")
            write_jpeg(Path(out_dir) / names[-1], frame)
        return {
            "frames": names,
            "x": x1,
            "y": y1,
            "width": int(width),
            "height": int(height),
            "interval_ms": int(round(1000 * step / fps)),
        }

    return _kept_clip(out_dir, name, make)


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
    _check_recording(recording, len(saved["recordings"]), saved["name"])
    recordings_dir = Path(saved["data_dir"])
    source = saved["recordings"][recording]
    return _write_clip(open_recordings(recordings_dir), source["name"], source["fps"], (0, 0, 10**6, 10**6),
                       out_dir, f"clip_{_clip_key(dataset)}_r{recording}_plate", PLATE_CLIP_WIDTH)


def _recording_name(loader, recording):
    """The name of recording `recording` of an analysis, counted from 0."""
    recordings = loader.recording_names
    _check_recording(recording, len(recordings))
    return recordings[recording]


def analysis_outlines(data_dir, out_dir, recording, zone_id, results):
    """What the score sees of each mite of one zone in one recording of an
    analysis, where it was in that recording (_where_in()), for the result
    pages to draw over the mites: mite id to
    OutlineView.describe(), None for a mite it finds no outline of; the
    fly-offs' too (_with_fly_offs()). `results` as run_analysis() gives them.
    Like analysis_clip(), worked out from the frames once, kept in `out_dir`
    under a name that says where the mites are, and reused after."""
    loader = open_recordings(data_dir)
    source = _recording_name(loader, recording)
    mites = [_where_in(loader, source, mite) for mite in _with_fly_offs(results) if mite["zone_id"] == zone_id]
    if not mites:
        return {}

    def make():
        mite = get_default_config().mite
        pad, width = _metric_pad(mite), Analyzer.check_metric_params(mite.metric, mite.params_for(mite.metric)).get("width", 1.5)
        boxes = {m["id"]: _square(m, int(mite.radius) + pad) for m in mites}
        x0, y0, x_end, y_end = _bounds(boxes.values())
        frames = loader.load_recording_region(source, x0, y0, x_end, y_end)
        outlines = {}
        for mite_id, (x1, y1, x2, y2) in boxes.items():
            x1, y1 = max(x1, x0), max(y1, y0)
            outlines[mite_id] = OutlineView.describe(frames[:, y1 - y0:y2 - y0, x1 - x0:x2 - x0], x1, y1, width, pad)
        return outlines

    return _kept_clip(out_dir, f"outline_r{recording}_z{zone_id}_{_where_key(mites)}", make)


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
    mite = _find(mites, mite_id, "these results")
    loader = open_recordings(data_dir)
    name = _recording_name(loader, recording)
    return _mite_clip(data_dir, {"name": name, "fps": loader.get_fps(name)}, mite, out_dir, f"mite_r{recording}")


PLAYBACK_MAX_FRAMES = 100  # frames of one recording in its playback at most; a longer one is thinned to fit
PLAYBACK_MARGIN = 4  # pixels round a mite's box (its detector radius round its centre) in its playback square


def playback_reach():
    """Pixels from a mite's centre to the edge of its square in the playback:
    its box, the detector's radius round it, and PLAYBACK_MARGIN, so the mite
    fills it."""
    return int(get_default_config().mite.radius) + PLAYBACK_MARGIN


def _playback_step(loader, name):
    """Every how many frames of recording `name` the playback shows one."""
    return max(1, int(np.ceil(loader.count_frames(name) / PLAYBACK_MAX_FRAMES)))


def _with_fly_offs(results):
    """The mites of `results` (as run_analysis() gives them), then the
    fly-offs, which the analysis leaves out, in that order: [{id, zone_id, x,
    y, flew_off}], `flew_off` the recording a fly-off left its place in, None
    for the others. The playback shows them all, the drift squares the
    fly-offs' outlines too."""
    mites = [{"id": mite["id"], "zone_id": mite["zone_id"], "x": mite["x"], "y": mite["y"], "flew_off": None}
             for mite in results["mites"]]
    known = {mite["id"] for mite in mites}
    mites += [{"id": fly_off["id"], "zone_id": fly_off["zone"], "x": fly_off["x"], "y": fly_off["y"], "flew_off": fly_off["from"]}
              for fly_off in (results.get("activity") or {}).get("fly_offs", []) if fly_off["id"] not in known]
    return mites


def _where_key(mites):
    """A short name for where `mites` ({id, x, y}) are, for the file names of
    what is cut round them: mites detected anew elsewhere get new files."""
    where = json.dumps([[mite["id"], round(mite["x"]), round(mite["y"])] for mite in mites])
    return hashlib.sha1(where.encode("utf-8")).hexdigest()[:8]


def playback_timeline(data_dir, results):
    """What the playback page plays of the recordings of an analysis
    (`results`, as run_analysis() gives them), one after the other: per
    recording, how many frames it shows and the delay between them (ms) that
    plays them in real time; the side of a mite's picture (px); and the mites,
    by zone in their order (_with_fly_offs(), without where they are)."""
    loader = open_recordings(data_dir)
    recordings = []
    for name in loader.recording_names:
        step = _playback_step(loader, name)
        recordings.append({"frames": len(range(0, loader.count_frames(name), step)),
                           "interval_ms": int(round(1000 * step / loader.get_fps(name)))})
    mites = [{key: mite[key] for key in ("id", "zone_id", "flew_off")} for mite in _with_fly_offs(results)]
    return {"recordings": recordings, "tile": 2 * playback_reach(), "mites": mites}


def playback_sheet(data_dir, out_dir, recording, zone_id, results):
    """Every mite of one zone in every frame of one recording, for the playback
    page: one picture with a row per mite (_with_fly_offs(), the fly-offs
    too) and a column per frame (as playback_timeline() thins them), each
    2 * playback_reach() pixels square round the mite's centre where it was in
    that recording (_where_in()), black where nothing was saved (of a session
    saved as the mites' ROIs, beyond the mite's own there). `results` as run_analysis() gives them. Returns the picture's
    file (relative to `out_dir`), the mites in its rows, the side of a square
    and the frames. Written to out_dir/clips/ once, under a name that says
    where the mites are, and reused after."""
    mites = [mite for mite in _with_fly_offs(results) if mite["zone_id"] == zone_id]
    if not mites:
        raise ValueError(f"No mites in zone {zone_id}.")
    loader = open_recordings(data_dir)
    source = _recording_name(loader, recording)
    reach = playback_reach()
    placed = [_where_in(loader, source, mite) for mite in mites]
    name = f"playback_r{recording}_z{zone_id}_s{2 * reach}_{_where_key(placed)}"

    def make():
        step, side = _playback_step(loader, source), 2 * reach
        n_frames = len(range(0, loader.count_frames(source), step))
        sheet = np.zeros((len(mites) * side, n_frames * side), dtype=np.uint8)
        for row, (mite, here) in enumerate(zip(mites, placed)):
            x1, y1, x2, y2 = _square(here, reach)
            cut = [max(0, x1), max(0, y1), x2, y2]
            if isinstance(loader, RoiRecordings):
                roi = loader.roi_in(source, mite["x"], mite["y"])
                if roi is None:
                    continue
                cut = [max(cut[0], roi[0]), max(cut[1], roi[1]), min(cut[2], roi[2]), min(cut[3], roi[3])]
            frames = loader.load_recording_region(source, *cut, step=step)
            top, left = row * side + cut[1] - y1, cut[0] - x1
            height, width = frames.shape[1:3]
            for column, frame in enumerate(frames[:n_frames]):
                sheet[top:top + height, column * side + left:column * side + left + width] = frame
        picture = f"{CLIPS_DIRNAME}/{name}.jpg"
        write_jpeg(Path(out_dir) / picture, sheet)
        return {"sheet": picture, "mites": [mite["id"] for mite in mites], "tile": side, "frames": n_frames}

    return _kept_clip(out_dir, name, make)


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
    return calibration.match_ground_truth(stored["mites"], load_ground_truth(stored["data_dir"]), len(stored["times"]))


def _write_ground_truth(stored, truth, tolerance=positions.TOLERANCE):
    """Write the ground truth of a calibration session's mites (`truth`, by
    mite id) next to its recordings, by position; returns the mites labelled."""
    n_recordings = len(stored["times"])
    labelled = {}
    for mite in stored["mites"]:
        states = calibration.per_recording(truth.get(mite["id"]), n_recordings)
        if any(states):
            labelled[mite["id"]] = states

    recordings_dir = _recordings_dir(stored, "the ground truth cannot be saved with them")
    if True:
        entries = [{"x": mite["x"], "y": mite["y"], "truth": labelled[mite["id"]]}
                   for mite in stored["mites"] if mite["id"] in labelled]
        # Entries away from every mite of this session, e.g. detections marked
        # "not a mite" under other detector settings, are not this session's to drop.
        entries += [entry for entry in load_ground_truth(recordings_dir)
                    if positions.away_from_all(entry, stored["mites"], tolerance)]
        _write_truth(recordings_dir, entries)
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
    return read_json(Path(data_dir) / POKE_FILENAME, {})


def _poke_of(source):
    """The poke test of a calibration session or a saved dataset (`source` has
    its data_dir, mites and times), by mite id. Detections marked not a mite in
    the ground truth have no part in it."""
    mites = [mite for mite, _states in _mite_states(source, source["truth"] if "truth" in source else _saved_truth(source))]
    return PokeTest(mites, len(source["times"]), load_poke_test(source["data_dir"]))


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
    recordings_dir = _recordings_dir(stored, "the poke test cannot be saved with them")
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
    write_json(recordings_dir / POKE_FILENAME, poke.saved())
    return poke.view()


def _poked_mites(dataset, scores, threshold, outline=None):
    """The poked mites of a dataset with the detector's death of each at
    `threshold` (PokeSurvival.mites()) and, with `outline` (mite id to the
    outline change's calls, see OutlineChange.calls()), the outline change's;
    [] without a poke test."""
    poke = _poke_of(dataset)
    if not poke.rounds:
        return []
    moving = {mite["id"]: [score >= threshold for score in scores[mite["id"]]] for mite in poke.mites}
    others = {} if outline is None else {"outline": {mite["id"]: outline[mite["id"]] for mite in poke.mites}}
    return PokeSurvival(poke, dataset["times"], moving, others).mites()


def _poke_survival(mites, times):
    """The survival of the poked mites of the pooled datasets by the pokes and by
    the detector, for the test report (PokeSurvival.curves()); None without any."""
    curves = PokeSurvival.curves(mites, times)
    if curves:
        for curve in [curves["poke"], curves["detector"], *curves["others"].values()]:
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


def _mite_states(dataset, truth=None):
    """[(mite, its statuses per recording, see calibration.per_recording())] of a
    dataset or a calibration session (`truth` by mite id, the dataset's own by
    default), the mites marked not a mite left out."""
    truth = dataset["truth"] if truth is None else truth
    n_recordings = len(dataset["times"])
    states = ((mite, calibration.per_recording(truth.get(mite["id"]), n_recordings)) for mite in dataset["mites"])
    return [(mite, mite_states) for mite, mite_states in states if not calibration.is_rejected(mite_states)]


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


def _cached_per_recording(cache, field, dataset):
    """What `cache` holds under `field` (mite id to one value per recording), or
    None when there is no cache or it was written when the dataset had another
    number of recordings: a run recorded on after it was scored."""
    cached = read_json(cache)
    if cached is None:
        return None
    by_mite = cached[field]
    n_recordings = len(dataset["recordings"])
    return by_mite if all(len(values) == n_recordings for values in by_mite.values()) else None


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


def _free_name(name, recordings_root, separator="-"):
    """`name`, or `name-2`, `name-3`... (`separator` before the number): the
    first not taken in `recordings_root`."""
    candidates = itertools.chain([name], (f"{name}{separator}{number}" for number in itertools.count(2)))
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


# --- evaluation -------------------------------------------------------------------------


def _digest(*parts, sort_keys=False):
    """Twelve hex digits that change with `parts` (as JSON): the version in a
    cached file's name."""
    return hashlib.sha1(json.dumps(list(parts), sort_keys=sort_keys).encode("utf-8")).hexdigest()[:12]


def _mites_key(mites):
    """What of the mites ({id, x, y, r}) a cached measure of them depends on."""
    return [[m["id"], m["x"], m["y"], m["r"]] for m in mites]


def _metric_version(metric, params, mites, stabilize=False):
    """Changes whenever the scores of these mites could: another metric, other
    parameters, plate stabilization switched, an edit to the scoring code, or
    other mites."""
    source = inspect.getsource(Analyzer) + inspect.getsource(plate_stabilizer)
    return _digest(metric, params, source, _mites_key(mites), *([True] if stabilize else []), sort_keys=True)


def _brightness_name(mites, pad, stabilize):
    return f"brightness-{_digest(inspect.getsource(plate_stabilizer), pad, bool(stabilize), _mites_key(mites))}.json"


def _benchmark_name(mites):
    return f"benchmark-{_digest(inspect.getsource(benchmark_module), _mites_key(mites))}.json"


def _outline_name(mites, stabilize):
    source = inspect.getsource(outline_change_module) + inspect.getsource(plate_stabilizer)
    return f"outline-{_digest(source, bool(stabilize), _mites_key(mites))}.json"


def _cached_by_mite(dataset, filename, field, measure, **more):
    """`measure()` of a dataset's mites (mite id to one value per recording),
    kept in its scores/ as `filename` under `field` (with `more` beside it) and
    read back from there while the dataset has as many recordings
    (_cached_per_recording()). The cache is only a shortcut: deleting it just
    means decoding the recordings again."""
    cache = _scores_dir(dataset) / filename
    cached = _cached_per_recording(cache, field, dataset)
    if cached is not None:
        return cached
    values = measure()
    cache.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache, {**more, field: values})
    return values


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
    x0, y0, x_end, y_end = _bounds(boxes.values(), STABILIZE_MARGIN if stabilize else 0)
    local = _local(mite_boxes(dataset["mites"]), x0, y0)

    def measured(frames):
        shifts = dict(zip(local, PlateStabilizer().shifts(frames, list(local.values())))) if stabilize else None

        def one(mite_id):
            x1, y1, x2, y2 = boxes[mite_id]
            if shifts is None:
                return measure(frames[:, max(0, y1) - y0:y2 - y0, max(0, x1) - x0:x2 - x0])
            return measure(PlateStabilizer.cut(frames, local[mite_id], pad, shifts[mite_id]))

        return dict(zip(boxes, side_by_side(one, boxes)))

    loads = (partial(loader.load_recording_region, recording["name"], x0, y0, x_end, y_end)
             for recording in dataset["recordings"])
    for frames in one_ahead(loads):
        yield measured(frames)


def _check_there(dataset, recordings_dir, what):
    """_recordings_dir() of `dataset`, its recordings read from `recordings_dir`."""
    _recordings_dir({**dataset, "data_dir": str(recordings_dir)}, what)


def _score_mites(dataset, metric, recordings_dir, params=None, stabilize=False):
    """Score every mite of a dataset in every recording with `metric` and its
    `params`: mite id to one score per recording (see _measure_mites())."""
    _check_there(dataset, recordings_dir, f"its mites cannot be scored with {metric}")
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
    _check_there(dataset, recordings_dir, "the brightness of its mites cannot be measured")
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
    return _cached_by_mite(dataset, _brightness_name(dataset["mites"], pad, stabilize), "brightness",
                           lambda: _brightness_mites(dataset, Path(dataset["data_dir"]), pad, stabilize))


def _normalised_scores(key, dataset, scores, normalizer, pad, stabilize):
    """A dataset's scores as the analysis of a folder would have them with
    `normalizer`: over the dataset's recordings, the mites marked not a mite
    left out of it, as an analysis leaves them out."""
    if not normalizer.active:
        return scores
    brightness = _dataset_brightness(key, dataset, pad, stabilize) if normalizer.brightness else None
    mites = [mite["id"] for mite, _states in _mite_states(dataset)]
    normalised = normalizer.by_mite({mite_id: scores[mite_id] for mite_id in mites},
                                    brightness and {mite_id: brightness[mite_id] for mite_id in mites})
    return {**scores, **{mite_id: [round(value, 3) for value in values] for mite_id, values in normalised.items()}}


def _dataset_scores(key, dataset, metric, params, stabilize=False):
    """The dataset's mites scored with `metric` and `params`, from the cache when
    exactly this metric, with these parameters, this plate stabilization and
    this scoring code, has scored them before. The cache is only a shortcut:
    deleting it just means decoding the recordings again."""
    return _cached_by_mite(dataset, f"{_metric_version(metric, params, dataset['mites'], stabilize)}.json", "scores",
                           lambda: _score_mites(dataset, metric, Path(dataset["data_dir"]), params, stabilize),
                           metric=metric, params=params)


def _benchmark_mites(dataset, recordings_dir):
    """Whether the benchmark (classes/benchmark.py) calls each mite of a dataset
    moving in each recording: mite id to one True or False per recording. Slow:
    every frame is decoded and denoised, in the part of the image holding mites."""
    _check_there(dataset, recordings_dir, "the benchmark cannot be run on them")
    loader = open_recordings(recordings_dir)
    boxes = mite_boxes(dataset["mites"])
    x0, y0, x_end, y_end = _bounds(boxes.values(), Benchmark.MARGIN)
    local = _local(boxes, x0, y0)

    calls = {mite_id: [] for mite_id in boxes}
    for recording in dataset["recordings"]:
        frames = loader.load_recording_region(recording["name"], x0, y0, x_end, y_end)
        for mite_id, moving in Benchmark.calls(frames, local).items():
            calls[mite_id].append(moving)
    return calls


def _dataset_benchmark(key, dataset):
    """The benchmark's calls for the dataset's mites, from the cache when this
    benchmark code has called exactly these mites before."""
    return _cached_by_mite(dataset, _benchmark_name(dataset["mites"]), "calls",
                           lambda: _benchmark_mites(dataset, Path(dataset["data_dir"])), benchmark=Benchmark.NAME)


def _outline_mites(dataset, recordings_dir, stabilize=False):
    """How much each mite's outline changed from the recording before
    (OutlineChange.changes()): mite id to one change per recording, in px, None
    for the first. Slow: every frame is decoded, as scoring decodes them
    (_measure_mites()), each mite cut with outline_change.PAD pixels around it."""
    _check_there(dataset, recordings_dir, "their outlines cannot be compared")
    outlines = {mite["id"]: [] for mite in dataset["mites"]}
    for recording in _measure_mites(dataset, recordings_dir, OutlineChange.outline_of, outline_change_module.PAD,
                                    stabilize):
        for mite_id, outline in recording.items():
            outlines[mite_id].append(outline)
    return {mite_id: [None if change is None else round(change, 4) for change in OutlineChange.changes(found)]
            for mite_id, found in outlines.items()}


def _dataset_outline_changes(key, dataset, stabilize=False):
    """_outline_mites() of the dataset, from the cache when this outline code,
    with this plate stabilization, has measured exactly these mites before."""
    return _cached_by_mite(dataset, _outline_name(dataset["mites"], stabilize), "changes",
                           lambda: _outline_mites(dataset, Path(dataset["data_dir"]), stabilize))


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
    cache = _scores_dir(dataset) / f"benchmark-circles-{_digest(inspect.getsource(benchmark_module), name)}.json"
    cached = read_json(cache)
    if cached is not None:
        return cached["circles"]
    try:
        circles = _benchmark_circles(Path(dataset["data_dir"]), name)
    except FileNotFoundError:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache, {"benchmark": Benchmark.NAME, "recording": name, "circles": circles})
    return circles


def _last_recording(dataset, scores, threshold, benchmark=None, circles=None):
    """The last recording of a dataset as its callers see it, for the test
    report: every mite not marked "not a mite" with its box (x1, y1, x2, y2),
    its score there, the detector's call at `threshold` and its label, None
    when it has none there. With `benchmark` (its calls, see
    _dataset_benchmark()) each mite also has the benchmark's call, and
    `circles` are what the benchmark draws on that recording, each of radius
    "circle_radius" (see _dataset_circles()). A mite a live run did not follow
    there (counted dead by then, see calibration.followed()) is left out."""
    last = len(dataset["times"]) - 1
    boxes = mite_boxes(dataset["mites"])
    mites = []
    for mite, states in _mite_states(dataset):
        if not calibration.followed(mite, last):
            continue
        score = scores[mite["id"]][last]
        mites.append(
            {
                "id": mite["id"],
                "zone_id": mite["zone_id"],
                "box": list(boxes[mite["id"]]),
                "score": score,
                "call": calibration.call(score >= threshold),
                "movement": states[last],
                **({} if benchmark is None else {"benchmark_call": calibration.call(benchmark[mite["id"]][last])}),
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


def _observations(dataset, dataset_key, scores, benchmark=None, outline=None):
    """One row per (mite, recording) of a dataset labelled moving or still, and
    the number of mites marked not a mite and of unlabelled mite-recordings.
    With `benchmark` (its calls, see _dataset_benchmark()), each row also says
    what the benchmark called it; with `outline` ({changes, calls}, each mite id
    to one per recording, see _between_recordings()), the outline's change from
    the recording before and what it calls it. A mite a live run did not follow
    in a recording (added later, or counted dead, see calibration.followed())
    has no row there: nothing of it was saved."""
    times = dataset["times"]
    n_recordings = len(times)
    groups = {zone["id"]: zone["label"] or UNLABELED for zone in dataset["zones"]}
    recording_names = [recording["name"] for recording in dataset["recordings"]]
    recording_names += [""] * (n_recordings - len(recording_names))
    rows, n_unlabelled = [], 0
    kept = _mite_states(dataset)
    n_rejected = len(dataset["mites"]) - len(kept)
    for mite, states in kept:
        start = mite.get("start", 0)
        for recording, movement in enumerate(states):
            if not calibration.followed(mite, recording):
                continue
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
                    "start": start,
                    "movement": movement,
                    "score": scores[mite["id"]][recording],
                    **({} if benchmark is None else {"benchmark_call": calibration.call(benchmark[mite["id"]][recording])}),
                    **({} if outline is None else {
                        "outline_change": outline["changes"][mite["id"]][recording],
                        "outline_call": calibration.call(outline["calls"][mite["id"]][recording])}),
                }
            )
    return rows, n_rejected, n_unlabelled


def _between_recordings(key, dataset, stabilize=False):
    """The outline change of every mite of a dataset from the recording before
    (_dataset_outline_changes()) and whether it says the mite moved
    (OutlineChange.calls()): {changes, calls}, each mite id to one per recording.
    A change into or out of a recording a live run did not follow the mite in
    (calibration.followed()) is None: nothing of it was saved there."""
    changes = dict(_dataset_outline_changes(key, dataset, stabilize))
    for mite in dataset["mites"]:
        if mite.get("start") or mite.get("stop") is not None:
            changes[mite["id"]] = [None if not (calibration.followed(mite, at) and calibration.followed(mite, at - 1)) else change
                                   for at, change in enumerate(changes[mite["id"]])]
    judge = OutlineChange()
    return {"changes": changes, "calls": {mite_id: judge.calls(values) for mite_id, values in changes.items()}}


def _outline_rows(dataset, key, outline):
    """Every mite of a dataset not marked not a mite, for the figure of the
    outline change (OutlineChange.raster()): where it is, its labels per
    recording (True moving, False still, None unlabelled) and its changes."""
    rows = []
    for mite, states in _mite_states(dataset):
        rows.append({"dataset": key, "dataset_name": dataset["name"], "mite_id": mite["id"], "zone_id": mite["zone_id"],
                     "moving": [None if state is None or not calibration.followed(mite, at) else state == calibration.MOVING
                                for at, state in enumerate(states)],
                     "changes": outline["changes"][mite["id"]], "calls": outline["calls"][mite["id"]]})
    return rows


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
                         checks_per_mite=None, between=False):
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
    _suggested_band(); its shape is kept in config.yaml at once when the report
    scores as the analyses do, see _keep_band_shape()); every observation with
    its outcome; and, where a poke
    test was entered, the survival of the poked mites by the pokes and by the
    detector at the threshold in use ("poke", see _poke_survival()).
    Everything is also written to calibration.xlsx in `out_dir`, a moment later:
    the workbook takes longer to write than the report to work out, so the page
    has the report first (results_file() waits for the workbook).

    With `benchmark`, the same observations are also called by the Discobox's
    original software (classes/benchmark.py): its confusion counts, with
    precision, recall and F1 as for the detector, come as "benchmark", and its
    survival curve and its death errors join the others. Slow the first time a dataset meets it.

    With `between`, each mite's outline is also compared from each recording to
    the next (classes/outline_change.py): a change that opening the box to poke
    the mites does not fake. Each observation then has its "outline_change" and
    "outline_call", the outline's calls join the others' survival curves and
    death errors (as "outline"), and the poked mites' ("others" of "poke"); and
    "between_recordings" holds every mite's changes for the figure of them all
    (OutlineChange.raster()). Slow the first time a dataset meets it, as every
    frame is decoded.
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

    rows, n_rejected, n_unlabelled, summaries, poked, outline_rows = [], 0, 0, [], [], []
    for key, dataset in zip(ids, loaded):
        scores = _dataset_scores(key, dataset, metric, params, stabilize)
        scores = _normalised_scores(key, dataset, scores, normalizer, Analyzer.roi_padding(metric, params),
                                    stabilize)
        called = _dataset_benchmark(key, dataset) if benchmark else None
        outline = _between_recordings(key, dataset, stabilize) if between else None
        here, rejected, unlabelled = _observations(dataset, key, scores, called, outline)
        last = len(dataset["times"]) - 1
        circles = _dataset_circles(key, dataset, last) if benchmark and last < len(dataset["recordings"]) else None
        rows += here
        poked += _poked_mites(dataset, scores, current, outline and outline["calls"])
        if outline:
            outline_rows += _outline_rows(dataset, key, outline)
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

    # who else calls the observations: the benchmark, and the outline change between recordings
    calls = {**({"benchmark": "benchmark_call"} if benchmark else {}), **({"outline": "outline_call"} if between else {})}

    def survival(subset):
        curves = calibration.survival_curves(subset, times, thresholds, calls)
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
                        for name, errors in calibration.death_errors(rows, thresholds, calls).items()},
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
        # every mite's outline change from each recording to the next, by its death; None without `between`
        "between_recordings": OutlineChange().raster(outline_rows) if between else None,
    }
    if result["threshold_fits"] and result["review_band"] is not None:
        kept = _keep_band_shape(result["review_band"], suggested, current)
        if kept is not None:
            in_use["review_band"] = kept
    # each outcome as a fraction of its row, for the confusion matrices and the ROC curve
    result["rates"] = {key: None if result[key] is None else calibration.outcome_rates(result[key]) for key in ("current", "best")}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    result["excel"] = reporting.CALIBRATION_EXCEL_NAME
    _files_later.later(_draft_key(out_dir), lambda: reporting.write_calibration_excel(result, out_dir))
    return result


def _keep_band_shape(band, suggested, threshold):
    """Keep the shape of the band a calibration report suggests (around the
    `suggested` threshold) in config.yaml, moved to hold the `threshold` in use:
    the result pages widen or narrow it to the mites to check
    (classes/review_band.py), so only how far it reaches below the threshold
    against above counts. Nothing when the report suggests no band. Returns
    [low, high] as saved, or None."""
    if not band["high"] > band["low"]:
        return None
    try:
        return app_config.save_review_band(threshold - (suggested - band["low"]), threshold + (band["high"] - suggested))
    except ValueError:  # too narrow to tell apart from the threshold, once rounded
        return None


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
RUN_INFO_NAME = "run.json"
LIVE_FEED_WIDTH = 960
LIVE_STATES = ("running", "paused", "stopping")
LEDS = ("led1", "led2")
# Seconds for the camera's automatic exposure to follow the LEDs coming on.
LIGHTS_SETTLE = 1.5
# The same when lighting the plates to find mites to add (_lit_frame()): between
# recordings the camera has been in the dark, its exposure at its longest, and it
# takes longer to come down than LIGHTS_SETTLE.
FIND_MITES_SETTLE = 10
# Seconds to spare before the next recording's cycle starts, for lighting the
# plates to find mites to add (live_find_mites()): FIND_MITES_SETTLE and the
# wait for a frame after it.
FIND_MITES_SPARE = 20
# Pixels round a mite already followed in which a blob found is that mite.
FOUND_MITE_REACH = 4
ADD_PREVIEW_NAME = "add_mites.jpg"
# In a live run's folder: the frame mites were added on, from_<recording>.jpg, the
# recording they were added in (live_add_mites(), _added_previews()).
ADDED_FRAMES_DIRNAME = "added_frames"

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
    return _free_name(f"test_run_{date.today():%Y-%m-%d}", recordings_root, "_")


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
    too."""
    settings = Settings.from_dict({**Settings.from_file(settings_path).as_dict(), **values})
    run = _live.get(live_id) if live_id else None
    if run is not None and run.session.state != "ready":
        raise ValueError("The settings cannot change while the test run is going on.")
    settings.save(settings_path)
    if run is not None:
        run.source.settings = settings
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
    (name -> value, e.g. {"death_minutes": 240}) overriding them for this run only. Its
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
            preview_written=False, files_due=None, zones=[], stop_reason=None, finding=threading.Lock(),
            found_frame=None,  # the lit frame the mites to add were last found on (live_find_mites())
        )
        run.analysis = analysis = MotionAnalysis(_live_zone_manager(run))
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
    """Switch both LEDs on, one that is off at its set intensity, and keep them
    on until the run starts (Lights.keep_on()): they are told again even when
    believed on, as the controller may have missed it. True if either was off.
    A failure is only logged: the camera works without its light."""
    if not lights.connected:
        return False
    off = [device for device in LEDS if not lights.on[device]]
    try:
        lights.keep_on({device: getattr(settings, device) if device in off else lights.level[device] for device in LEDS})
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
    # A call corrected after the run's end writes the files again, and nothing else.
    going = write_files and run.session.state != "finished"
    _arrange(run.analysis, run.run_dir, labels, True)
    # The scores are normalised over a whole run, so not while it goes on.
    results = _results(_run_view(run.analysis, _live_frames(run), run.run_dir), run.out_dir, labels, False,
                       corrections=CallCorrections(run.run_dir), normalizer=ScoreNormalizer())
    if write_files:
        if not run.preview_written:  # the first frame, which the pages draw on: it never changes
            _write_preview(run.analysis.first_frame, run.out_dir)
            run.preview_written = True
        _write_live_files_later(run)
    progress = ZoneProgress(results, death_minutes(run.run_dir))
    run.zones = progress.zones()
    if going:
        _follow_live(run, progress, len(results["times"]))
        _write_run_info(run)
    return results


def _follow_live(run, progress, recordings):
    """After a recording of a running live run: the mites that count as dead are
    no longer followed from the next on, and once every zone is done the run
    stops (classes/live/progress.py)."""
    dead = set(progress.dead_ids())
    run.analysis.stop([mite for mite in run.analysis.mites if mite.text in dead], recordings)
    if progress.all_done(run.zones) and run.session.state in ("running", "paused") and run.stop_reason is None:
        run.stop_reason = "Every mite of every zone is dead."
        _logger.info("Stopping the test run %s: %s", run.run_dir.name, run.stop_reason)
        run.session.stop()


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
            "stop_reason": run.stop_reason,
        }
        write_json(run.run_dir / RUN_INFO_NAME, info, indent=2)
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
    run.source.settings.check_death_time()
    run.analysis.follow = run.source.settings.follow_px or None
    if labels is not None:
        save_labels(run.run_dir, labels)
    (run.run_dir / SETTINGS_FILENAME).write_text(run.source.settings_text, encoding="utf-8")
    if run.save_frames:
        RoiVideo.check_codec(run.run_dir)
    run.session.recorder = Recorder(run.run_dir) if run.save_frames else None
    run.started_at = datetime.now().isoformat(timespec="seconds")
    _write_run_info(run)
    run.lights.all_off()  # the LEDs, and the fan if it was switched on to check it: the test run's from here on
    try:
        run.session.start()
    except Exception:
        if run.session.recorder is not None:
            run.session.recorder.close()
            run.session.recorder = None
        if run.session.state == "ready":  # not started: still setting up, so lit
            _leds_on(run.lights, run.source.settings)
        raise
    return live_status(live_id)


def live_status(live_id):
    run = _get_live(live_id)
    status = {
        **run.session.status(),
        "live_id": live_id,
        "run_name": run.run_dir.name,
        "run_dir": str(run.run_dir),
        "out_dir": str(run.out_dir),
        "save_frames": run.save_frames,
        "zones_per_plate": run.layout.zones_per_plate,
        "stop_reason": run.stop_reason,  # why the run stopped by itself, if it did
        "pending_mites": len(run.analysis._pending),  # mites to add when the next recording begins
    }
    # the zones' circles over the live result pages
    return {**status, "progress": RunProgress(status, run.zones).describe()}


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
    ground truth's changes not saved yet stay (TruthDraft.grow()). The mites
    are described again too: the run may have added some, or counted some dead
    and stopped following them (calibration.followed()). Returns the
    session as open_live_calibration() does. A session showing another dataset
    by now, e.g. one a pooled report opened, is left as it is."""
    run = _get_live(live_id)
    stored = _read_calibration_session(out_dir)
    names = list(run.session.recordings)
    if Path(stored["data_dir"]) == run.run_dir.resolve() and len(names) > len(stored["recordings"]):
        described, _first_frame = _describe_calibration(run.run_dir, run.coords_file, names)
        stored.update({key: described[key] for key in ("times", "recordings", "mites")})
        stored["previews"] = _added_previews(run.run_dir, out_dir, len(stored["times"]))
        _write_calibration_session(out_dir, stored)
        draft = _draft(out_dir)
        with _drafts_lock:
            draft.grow(len(stored["times"]))
            draft.set_mites(stored["mites"])
    return {**_calibration_view(stored, _saved_truth(stored)), "truth_view": truth_view(out_dir)}


def _write_live_files(run):
    """The workbook and the figures of a live run, as its recordings and
    corrections are now. The lock is held only to read the run, not while the
    files are written."""
    run.files_due = None  # a recording from now on is in the next write
    with run.session.lock:
        view = _run_view(run.analysis, _live_frames(run), run.run_dir)
        mite_data, _changes = _mite_table(view, CallCorrections(run.run_dir), ScoreNormalizer())
        annotated = _annotated(view)
    _write_files(annotated, run.out_dir, mite_data)


def live_find_mites(live_id):
    """Light the plates during a run, between two recordings, and detect the
    mites on the camera's frame that are not followed yet, to add some
    (live_add_mites()). The run is held meanwhile: a recording due waits for
    the LEDs to go off again. The frame is written to the results folder as
    ADD_PREVIEW_NAME. Returns what the label page shows, as live_preview() does:
    {preview, image, zones, mites}, the zones with their labels and the number
    of mites `followed` in each (those to add with the next recording
    included), and the mites found [{id, zone_id, x, y, r, x1, y1, x2, y2,
    rejected}], each numbered after the mites of its zone."""
    run = _adding_to(live_id)
    if not run.finding.acquire(blocking=False):
        raise ValueError("Mites are being looked for already.")
    try:
        status = run.source.status()
        if status["recording_name"]:
            raise ValueError("A recording is being captured: try again once it is over.")
        next_seconds = RunProgress(status).next_seconds(status.get("timeline"))
        lit = any(light["on"] for device, light in status["lights"].items() if device in DEVICES)             if status["lights"].get("connected") else False
        if lit or (next_seconds is not None and next_seconds < run.source.settings.cycle_seconds + FIND_MITES_SPARE):
            raise ValueError("The next recording is about to start: try again once it is over.")
        held = run.source.state == "running"
        if held:
            run.session.pause()
        try:
            image = _lit_frame(run)
        finally:
            if held:
                run.session.resume()
        found = _new_mites(run, image)
        zones = _add_zones(run, found)
        run.found_frame = image
    finally:
        run.finding.release()
    write_jpeg(Path(run.out_dir) / ADD_PREVIEW_NAME, image)
    return {"preview": ADD_PREVIEW_NAME, "image": _image_size(image), "zones": zones, "mites": found}


def _adding_to(live_id):
    """The live run `live_id`, refused unless mites can be added to it now."""
    run = _get_live(live_id)
    if run.session.state not in ("running", "paused"):
        raise ValueError("Mites can be added while the test run is going on.")
    if not run.analysis.started:
        raise ValueError("Mites can be added once the first recording has begun.")
    return run


def _add_zones(run, found):
    """The zones as the label page shows them while mites are added: their labels,
    whether they are a negative control, the mites `followed` in each (or to be
    added with the next recording), and `n_mites`, those and the ones `found`.
    Each mite found gets the id it would have, numbered after its zone's."""
    analysis = run.analysis
    with run.session.lock:
        zones = _describe_zones(analysis.zone_manager, load_labels(run.run_dir))
        followed = {zone.id: len(zone.mites) for zone in analysis.zone_manager.zones if zone.id is not None}
        for box in analysis._pending:
            zone = analysis.zone_manager.zone_of(box)
            if zone is not None:
                followed[zone.id] += 1
    controls = set(load_controls(run.run_dir))
    numbered = dict(followed)
    # the ids they will have (MotionAnalysis._add_all())
    boxes = [Rect(mite["x1"], mite["y1"], mite["x2"], mite["y2"], found=mite) for mite in found]
    for zone_id in dict.fromkeys(mite["zone_id"] for mite in found):
        here = [box for box in boxes if box.found["zone_id"] == zone_id]
        for box, text in mite_ids(here, zone_id, numbered[zone_id]):
            box.found["id"] = text
        numbered[zone_id] += len(here)
    for zone in zones:
        zone["control"] = zone["id"] in controls
        zone["followed"] = followed.get(zone["id"], 0)
        zone["n_mites"] = numbered.get(zone["id"], 0)
    return zones


def _lit_frame(run):
    """A frame of the plates with both LEDs on, which are switched off again after."""
    lights, settings = run.lights, run.source.settings
    count, _image = run.source.latest.get()
    try:
        if lights.connected:
            for device in LEDS:
                lights.switch(device, True, getattr(settings, device))
            time.sleep(FIND_MITES_SETTLE)
            count, _image = run.source.latest.get()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:  # a frame taken with the LEDs on
            newer, image = run.source.latest.get()
            if newer > count and image is not None:
                return image
            time.sleep(0.05)
        raise ValueError("No frame came from the camera.")
    finally:
        if lights.connected:
            for device in LEDS:
                lights.switch_off(device)


def _new_mites(run, image):
    """The mites the detector finds on `image` that are not followed already:
    none within FOUND_MITE_REACH of where a mite was last placed, or is to be
    added; only in a zone."""
    analysis = run.analysis
    with run.session.lock:
        last = analysis.placed[-1] if analysis.placed else {}
        known = [last.get(mite, tuple(mite)) for mite in analysis.mites] + list(analysis._pending)
        masked = analysis.zone_manager.mask_image_to_valid_rois(image)
    with DETECTION_LOCK:  # a Mite counts the ids on
        detected = analysis.analyzer.detect(masked)
    found = []
    for mite in detected:
        x, y = mite.home
        if any(x1 - FOUND_MITE_REACH <= x <= x2 + FOUND_MITE_REACH and y1 - FOUND_MITE_REACH <= y <= y2 + FOUND_MITE_REACH
               for x1, y1, x2, y2 in known):
            continue
        zone = analysis.zone_manager.zone_of(mite)
        if zone is not None:
            found.append(_mite_view(mite, zone.id, x1=mite.x1, y1=mite.y1, x2=mite.x2, y2=mite.y2, rejected=False))
    return found


def live_add_mites(live_id, boxes):
    """Follow the mites of `boxes` ([x1, y1, x2, y2] each, as live_find_mites()
    found them) from the next recording on, numbered after those of their zone.
    The frame they were found on is kept with the run's recordings
    (ADDED_FRAMES_DIRNAME), so the calibration pages show the plate with them
    from that recording on (_added_previews())."""
    run = _adding_to(live_id)
    checked = []
    for box in boxes:
        if len(box) != 4:
            raise ValueError("A mite is given as [x1, y1, x2, y2].")
        checked.append(tuple(int(value) for value in box))
    with run.session.lock:
        run.analysis.add_mites(checked)
        start = len(run.analysis.placed)  # the recording they are added in: the next to begin
    if checked and run.save_frames and run.found_frame is not None:
        try:  # several additions before one recording: the last frame shows them all
            (run.run_dir / ADDED_FRAMES_DIRNAME).mkdir(parents=True, exist_ok=True)
            write_jpeg(run.run_dir / ADDED_FRAMES_DIRNAME / f"from_{start}.jpg", run.found_frame, quality=90)
        except Exception:
            _logger.exception("Could not keep the frame the mites were added on")
    return live_status(live_id)


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

    run = try_json(data_dir / RUN_INFO_NAME)
    if not isinstance(run, dict):
        run = None
    labels = try_json(_layout_file(data_dir, LABELS_FILENAME), {})
    groups = [str(group).strip() for group in labels.values() if str(group).strip()] if isinstance(labels, dict) else []
    truth = [entry.get("truth") for entry in load_ground_truth(data_dir) if isinstance(entry, dict)]
    rejected = sum(calibration.is_rejected(value) for value in truth)
    labelled = sum(1 for value in truth
                   if not calibration.is_rejected(value) and any(calibration.per_recording(value, len(recordings))))
    workbook = results_dir(data_dir, results_root) / reporting.EXCEL_NAME
    started = DataLoader.parse_start_time(first)
    # as the Discobox app saved them; None for a folder without .settings.txt
    # the zones per plate are the analysis's, told apart below
    settings = {name: loader.settings[name] for name in ("recording_count", *SETTING_RANGES, *FIXED_SETTINGS)
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


def remove_empty_pooled_reports(results_root=RESULTS_ROOT):
    """Remove the folders of pooled calibration reports that made no report: a
    pooled report's folder is only of use for its report. Run when the app starts."""
    pooled = Path(results_root) / POOLED_DIRNAME
    for folder in sorted(pooled.iterdir()) if pooled.is_dir() else []:
        if folder.is_dir() and not any(folder.glob("*.xlsx")):
            remove_tree(folder, ignore_errors=True)
