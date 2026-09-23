"""The analysis, as a handful of functions.

This is the only module the user interface is allowed to call, and it knows nothing
about HTTP, sessions or browsers. Everything crossing this boundary is a plain dict,
list, string or number -- never a Zone, Mite, DataFrame or image array -- so the UI
can never reach into the analysis internals.

    open_session(...)          cheap: the zones to label and a preview image
    run_analysis(...)          the full pipeline, writing Excel and figures to out_dir
    analysis_clip(...)         frames of one recording, of one zone or the whole plate

    open_calibration(...)      detect and score the mites of a calibration session
    calibration_clip(...)      frames of one zone in one recording, to judge by eye
    save_ground_truth(...)     store which mites the user saw moving in each recording
    list_calibration_datasets(...)   the ground truth saved so far, one dataset per folder
    open_saved_calibration(...)      reopen a saved dataset without decoding anything
    delete_calibration_dataset(...)  forget a saved dataset
    dataset_preview(...)             the first frame of a saved dataset
    movement_scores()          the metrics a calibration can score with, and their parameters
    evaluate_calibration(...)  score the saved mites with a metric (the one in config.yaml
                               unless another is given), then confusion matrix, ROC, best
                               threshold against the labels, pooled over any saved datasets
    save_threshold(...)        write a new movement threshold into config.yaml
    save_movement_score(...)   write a metric, its parameters and its threshold into config.yaml
"""

import hashlib
import inspect
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

import reporting
from classes import calibration
from classes.analyzer import Analyzer
from classes import app_config
from classes.app_config import get_default_config, save_motion_threshold
from classes.data_loader import DataLoader
from classes.mite import Mite
from classes.zones import UNLABELED, ZoneManager

# Zone type ids as they appear in the coordinates file.
ZONE_TYPES = {"0": "label", "1": "mite"}
EXCLUDED_TYPES = ["label"]

DEFAULT_COORDS_FILE = "coords_pixel.txt"
LABELS_FILENAME = "labels.json"
GROUND_TRUTH_FILENAME = "ground_truth.json"
PREVIEW_NAME = "preview.jpg"
CALIBRATION_SESSION_NAME = "calibration_session.json"
# The ground truth of every labelled calibration recording is also kept here, so it
# can be reopened, pooled with others, or scored with a new metric later.
CALIBRATION_LIBRARY = Path(__file__).resolve().parent / "calibration_data"
DATASET_NAME = "dataset.json"
SCORES_DIRNAME = "scores"
RECORDINGS_DIRNAME = "recordings"


def _build_zone_manager(coords_file):
    return ZoneManager.from_coords_file(
        filepath=coords_file,
        zone_types=ZONE_TYPES,
        excluded_types=EXCLUDED_TYPES,
    )


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
    path = Path(data_dir) / LABELS_FILENAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_labels(data_dir, labels):
    """Store zone labels next to the recordings so they survive a restart."""
    path = Path(data_dir) / LABELS_FILENAME
    path.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    return str(path)


def open_session(data_dir, out_dir, coords_file=DEFAULT_COORDS_FILE):
    """Describe a recording session so its zones can be labelled.

    Decodes a single frame, writes it to `out_dir` as a JPEG, and returns the zone
    rectangles in image pixel coordinates, each with the number of mites detected
    in it -- detection only needs that first frame, so the UI can offer only the
    zones with mites for labelling. Drawing is left to the caller: the UI gets
    numbers, not a picture with boxes burnt into it.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    loader = DataLoader(data_dir, grayscale=False)
    n_recordings = loader.count_recordings()
    if n_recordings == 0:
        raise FileNotFoundError(f"No recordings found in {data_dir}")

    frame = loader.load_preview_frame()
    cv2.imwrite(str(out_dir / PREVIEW_NAME), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

    zone_manager = _build_zone_manager(coords_file)
    # The same detection as an analysis run, on the same first frame.
    Mite.reset_ids()
    zone_manager.assign_mites(Analyzer().detect(zone_manager.mask_image_to_valid_rois(frame)))
    zone_manager.remove_mites(_rejected_detections(zone_manager, load_ground_truth(data_dir)))
    n_mites = {zone.id: len(zone.mites) for zone in zone_manager.zones}

    zones = _describe_zones(zone_manager, load_labels(data_dir))
    for zone in zones:
        zone["n_mites"] = n_mites.get(zone["id"], 0)
    return {
        "data_dir": str(data_dir),
        "preview": PREVIEW_NAME,
        "image": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
        "n_recordings": n_recordings,
        "zones": zones,
    }


def _detect_and_score(data_dir, coords_file, labels=None, reject=True, score=True):
    """Decode every recording, find the mites and, with `score`, score their motion.

    The expensive part shared by an analysis run and a calibration. With `reject`,
    detections marked "not a mite" in the session's ground truth are dropped
    before scoring, so they appear nowhere in the results.
    """
    # The mite id counter is shared process-wide; restart it so each run numbers
    # its mites from zero.
    Mite.reset_ids()

    loader = DataLoader(data_dir, grayscale=False)
    zone_manager = _build_zone_manager(coords_file)
    zone_manager.apply_labels(labels)
    analyzer = Analyzer()

    recording_bursts = loader.load_bursts()
    first_frame = loader.get_first_frame()

    masked = zone_manager.mask_image_to_valid_rois(first_frame)
    mites = analyzer.detect(masked)
    valid_mites = zone_manager.assign_mites(mites)
    if reject:
        rejected = _rejected_detections(zone_manager, load_ground_truth(data_dir))
        valid_mites = zone_manager.remove_mites(rejected)
    if score:
        analyzer.classify_motility(valid_mites, recording_bursts)

    # One timestamp per burst, in minutes from the start of the session.
    burst_minutes = np.array([times[0] for _frames, times in recording_bursts]) / 60

    return SimpleNamespace(
        zone_manager=zone_manager,
        analyzer=analyzer,
        first_frame=first_frame,
        masked=masked,
        n_recordings=len(recording_bursts),
        burst_minutes=burst_minutes,
    )


def _image_size(frame):
    return {"width": int(frame.shape[1]), "height": int(frame.shape[0])}


def _write_preview(frame, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / PREVIEW_NAME), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])


def run_analysis(data_dir, out_dir, labels=None, coords_file=DEFAULT_COORDS_FILE):
    """Run the whole pipeline and write its results to `out_dir`.

    `labels` maps zone id (as a string) to the group name the user typed, e.g.
    {"0": "venom 2x", "1": "control"}. Returns the output filenames, a summary, and
    the per-zone and per-mite results the UI browses.
    """
    run = _detect_and_score(data_dir, coords_file, labels)
    burst_minutes = run.burst_minutes
    mite_data = run.zone_manager.get_mite_scores(burst_minutes)

    _write_preview(run.first_frame, out_dir)
    annotated = run.zone_manager.draw(run.masked)
    results = reporting.write_outputs(mite_data, annotated, out_dir)

    results.update(
        {
            "n_recordings": run.n_recordings,
            "times": [round(float(minute), 2) for minute in burst_minutes],
            "threshold": float(run.analyzer.config.mite.motion_threshold),
            "preview": PREVIEW_NAME,
            "image": _image_size(run.first_frame),
            "zones": reporting.describe_zones(mite_data, _describe_zones(run.zone_manager, labels), burst_minutes),
            "mites": reporting.describe_mites(mite_data),
            "groups": reporting.describe_groups(mite_data, burst_minutes),
        }
    )
    return results


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


def _calibration_view(stored, truth, library_dir):
    """What the ground-truth page needs about a calibration session."""
    return {
        "data_dir": stored["data_dir"],
        "dataset_id": dataset_id(stored["data_dir"]),
        "recordings_available": _recordings_dir(stored["data_dir"], library_dir).is_dir(),
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


def open_calibration(data_dir, out_dir, coords_file=DEFAULT_COORDS_FILE, library_dir=CALIBRATION_LIBRARY):
    """Detect the mites of a calibration session and keep them in `out_dir`.

    Slow: every frame is decoded. Nothing is scored here, so the page cannot show
    scores while the user enters the ground truth and bias it. Detections already
    marked "not a mite" are kept here, so that the mark can be undone.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")

    labels = load_labels(data_dir)
    run = _detect_and_score(data_dir, coords_file, labels, reject=False, score=False)
    _write_preview(run.first_frame, out_dir)

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
    mites.sort(key=lambda mite: int(mite["id"]))

    loader = DataLoader(data_dir, grayscale=False)
    stored = {
        # absolute, so the library can tell later whether the recordings are still there
        "data_dir": str(data_dir.resolve()),
        "times": [round(float(minute), 2) for minute in run.burst_minutes],
        "recordings": [{"name": d.name, "fps": loader.get_fps(d.name)} for d in loader.recording_dirs],
        "image": _image_size(run.first_frame),
        "zones": _describe_zones(run.zone_manager, labels),
        "mites": mites,
    }
    (Path(out_dir) / CALIBRATION_SESSION_NAME).write_text(json.dumps(stored), encoding="utf-8")

    # The file next to the recordings comes first; the library's copy covers a
    # folder that was copied somewhere without it.
    saved = load_ground_truth(data_dir) or _library_positions(data_dir, library_dir)
    return _calibration_view(stored, calibration.match_ground_truth(mites, saved, run.n_recordings), library_dir)


def calibration_clip(out_dir, recording, zone_id, library_dir=CALIBRATION_LIBRARY):
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
    name = f"clip_{dataset_id(stored['data_dir'])}_r{recording}_z{zone_id}"
    if (Path(out_dir) / f"{name}.json").is_file():
        return json.loads((Path(out_dir) / f"{name}.json").read_text(encoding="utf-8"))
    recordings_dir = _recordings_dir(stored["data_dir"], library_dir)
    if not recordings_dir.is_dir():
        raise FileNotFoundError(
            f"The recordings are no longer at {stored['data_dir']} and the library has no copy, "
            "so there is no clip to play. The ground truth can still be edited."
        )

    source = stored["recordings"][recording]
    box = (zone["x1"] - CLIP_MARGIN, zone["y1"] - CLIP_MARGIN, zone["x2"] + CLIP_MARGIN, zone["y2"] + CLIP_MARGIN)
    return _write_clip(DataLoader(recordings_dir, grayscale=False), source["name"], source["fps"], box, out_dir, name)


def _write_clip(loader, recording_name, fps, box, out_dir, name, max_width=None):
    """Write up to CLIP_MAX_FRAMES JPEGs of the region `box` = (x1, y1, x2, y2) of
    one recording, and a manifest `name`.json that later calls reuse.

    Returns the frame filenames, where the region sits in the full image (in full
    image pixels, even when `max_width` scales the frames down), and the delay
    between frames that plays them back in real time.
    """
    manifest = Path(out_dir) / f"{name}.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))

    step = max(1, int(np.ceil(loader.count_frames(recording_name) / CLIP_MAX_FRAMES)))
    x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
    frames = loader.load_recording_region(recording_name, x1, y1, int(box[2]), int(box[3]), step=step)
    height, width = frames.shape[1:3]
    scale = min(1.0, max_width / width) if max_width else 1.0

    names = []
    for index, frame in enumerate(frames):
        if scale < 1:
            frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        names.append(f"{name}_{index:02d}.jpg")
        cv2.imwrite(str(Path(out_dir) / names[-1]), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
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


def analysis_clip(data_dir, out_dir, recording, zone_id=None, coords_file=DEFAULT_COORDS_FILE):
    """Frames of one recording of an analysis session: of one zone, or with no
    `zone_id` of the whole plate, scaled down. Like calibration_clip(), written
    to `out_dir` once and reused after."""
    loader = DataLoader(data_dir, grayscale=False)
    recordings = loader.recording_dirs
    if not 0 <= recording < len(recordings):
        raise ValueError(f"No recording {recording} in this session.")
    source = recordings[recording].name

    if zone_id is None:
        box, name, max_width = (0, 0, 10**6, 10**6), f"clip_r{recording}_plate", PLATE_CLIP_WIDTH
    else:
        zone = next((z for z in _build_zone_manager(coords_file).labelled_zones if z.id == zone_id), None)
        if zone is None:
            raise ValueError(f"No zone {zone_id} in this session.")
        box = (zone.x1 - CLIP_MARGIN, zone.y1 - CLIP_MARGIN, zone.x2 + CLIP_MARGIN, zone.y2 + CLIP_MARGIN)
        name, max_width = f"clip_r{recording}_z{zone_id}", None
    return _write_clip(loader, source, loader.get_fps(source), box, out_dir, name, max_width)


def save_ground_truth(out_dir, truth, library_dir=CALIBRATION_LIBRARY):
    """Store the ground truth next to the recordings, by mite position, and in the
    calibration library by mite id.

    `truth` maps mite id to a list with one status per recording: "moving",
    "still", "not_a_mite" or None for unlabelled. Positions rather than ids are
    stored next to the recordings, so the file still applies after a change of
    detector settings renumbers the mites. The library keeps the mites, their
    labels and a copy of the recording folder, so the dataset can be pooled with
    others and scored with any metric later, wherever the original went.
    """
    stored = _read_calibration_session(out_dir)
    n_recordings = len(stored["times"])
    labelled = {}
    for mite in stored["mites"]:
        states = calibration.per_recording(truth.get(mite["id"]), n_recordings)
        if any(states):
            labelled[mite["id"]] = states

    # Next to the original recordings, or next to the library's copy once they are gone.
    recordings_dir = _recordings_dir(stored["data_dir"], library_dir)
    if recordings_dir.is_dir():
        entries = [{"x": mite["x"], "y": mite["y"], "truth": labelled[mite["id"]]}
                   for mite in stored["mites"] if mite["id"] in labelled]
        (recordings_dir / GROUND_TRUTH_FILENAME).write_text(json.dumps(entries), encoding="utf-8")
    _save_to_library(stored, labelled, out_dir, library_dir)
    return len(labelled)


# --- the calibration library ----------------------------------------------------------
#
# One dataset per recording folder, in library_dir/<dataset id>/: dataset.json
# holds what open_calibration() stored (zones, mite positions) plus the ground
# truth by mite id, and preview.jpg the first frame. recordings/ is a copy of the
# recording folder as an upload would hold it (recordings, settings, labels,
# ground truth), so the dataset still works once the original is moved or deleted.
# Saving the same folder again replaces its dataset and brings the copy up to date.
# scores/ caches the scores evaluate_calibration() computed, one file per version
# of the metric; it can be deleted at any time.


def dataset_id(data_dir):
    """A stable, filename-safe id for the dataset of one recording folder."""
    path = Path(data_dir).resolve()
    digest = hashlib.sha1(os.path.normcase(str(path)).encode("utf-8")).hexdigest()[:8]
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", path.name).strip("_") or "recording"
    return f"{name}-{digest}"


def _dataset_dir(dataset, library_dir):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(dataset)):
        raise ValueError(f"Bad dataset id: {dataset}")
    return Path(library_dir) / dataset


def _read_dataset(dataset, library_dir):
    path = _dataset_dir(dataset, library_dir) / DATASET_NAME
    if not path.is_file():
        raise FileNotFoundError(f"No saved ground truth called {dataset}.")
    saved = json.loads(path.read_text(encoding="utf-8"))
    # Datasets saved before scores were left out still carry them; ignore them,
    # they belong to whatever metric was in use back then.
    saved.pop("metric", None)
    saved["mites"] = _mite_positions(saved["mites"])
    return saved


def _recordings_dir(data_dir, library_dir):
    """Where a dataset's frames are read from: the original folder while it is
    there, else the library's copy of it."""
    if Path(data_dir).is_dir():
        return Path(data_dir)
    return _dataset_dir(dataset_id(data_dir), library_dir) / RECORDINGS_DIRNAME


def _copy_recordings(data_dir, target):
    """Bring the library's copy of a recording folder up to date: its own files
    (settings, labels, ground truth) and every recording in it. A file already
    copied, with the same size and time, is skipped, so saving again is quick."""
    data_dir = Path(data_dir)
    files = [path for path in data_dir.iterdir() if path.is_file()]
    for recording in DataLoader(data_dir).recording_dirs:
        files += [path for path in recording.rglob("*") if path.is_file()]
    for source in files:
        copy = target / source.relative_to(data_dir)
        stat = source.stat()
        if copy.is_file() and copy.stat().st_size == stat.st_size and copy.stat().st_mtime == stat.st_mtime:
            continue
        copy.parent.mkdir(parents=True, exist_ok=True)
        partial = copy.with_name(copy.name + ".part")
        shutil.copy2(source, partial)
        partial.replace(copy)  # only a complete file ever has the real name


def _save_to_library(stored, truth, out_dir, library_dir):
    """Keep this session's mites, ground truth and recordings in the library; a
    session with nothing labelled has no dataset."""
    folder = _dataset_dir(dataset_id(stored["data_dir"]), library_dir)
    if not truth:
        shutil.rmtree(folder, ignore_errors=True)
        return
    folder.mkdir(parents=True, exist_ok=True)
    preview = Path(out_dir) / PREVIEW_NAME
    if preview.is_file():
        shutil.copyfile(preview, folder / PREVIEW_NAME)
    dataset = {
        **stored,
        "name": Path(stored["data_dir"]).name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "truth": truth,
    }
    (folder / DATASET_NAME).write_text(json.dumps(dataset), encoding="utf-8")
    if Path(stored["data_dir"]).is_dir():
        _copy_recordings(stored["data_dir"], folder / RECORDINGS_DIRNAME)


def _library_positions(data_dir, library_dir):
    """A saved dataset's ground truth by position, as load_ground_truth() gives it."""
    try:
        dataset = _read_dataset(dataset_id(data_dir), library_dir)
    except FileNotFoundError:
        return []
    return [{"x": mite["x"], "y": mite["y"], "truth": dataset["truth"][mite["id"]]}
            for mite in dataset["mites"] if mite["id"] in dataset["truth"]]


def _label_counts(dataset):
    """Mites with a movement label, and moving and still labels, in a dataset."""
    n_recordings = len(dataset["times"])
    states = [calibration.per_recording(value, n_recordings) for value in dataset["truth"].values()]
    states = [s for s in states if not calibration.is_rejected(s)]
    return {
        "n_mites": sum(any(s) for s in states),
        "n_moving": sum(s.count(calibration.MOVING) for s in states),
        "n_still": sum(s.count(calibration.STILL) for s in states),
    }


def list_calibration_datasets(library_dir=CALIBRATION_LIBRARY):
    """Every saved dataset, the most recently saved first."""
    datasets = []
    for path in Path(library_dir).glob(f"*/{DATASET_NAME}"):
        try:
            dataset = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        datasets.append(
            {
                "id": path.parent.name,
                "name": dataset["name"],
                "data_dir": dataset["data_dir"],
                "saved_at": dataset["saved_at"],
                "n_recordings": len(dataset["times"]),
                "recordings_available": _recordings_dir(dataset["data_dir"], library_dir).is_dir(),
                **_label_counts(dataset),
            }
        )
    return sorted(datasets, key=lambda d: d["saved_at"], reverse=True)


def open_saved_calibration(dataset, out_dir, library_dir=CALIBRATION_LIBRARY):
    """Reopen a saved dataset to go on labelling it, without decoding anything.

    Clips play from the original recordings, or from the library's copy once
    those are gone. `out_dir` may already hold another dataset -- a pooled report
    jumping to one of its mites -- which this one then replaces; the files of
    earlier evaluations stay.
    """
    saved = _read_dataset(dataset, library_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    preview = _dataset_dir(dataset, library_dir) / PREVIEW_NAME
    if preview.is_file():
        shutil.copyfile(preview, out_dir / PREVIEW_NAME)
    stored = {key: saved[key] for key in ("data_dir", "times", "recordings", "image", "zones", "mites")}
    (out_dir / CALIBRATION_SESSION_NAME).write_text(json.dumps(stored), encoding="utf-8")

    n_recordings = len(stored["times"])
    truth = {mite_id: calibration.per_recording(states, n_recordings) for mite_id, states in saved["truth"].items()}
    return _calibration_view(stored, truth, library_dir)


def dataset_preview(dataset, library_dir=CALIBRATION_LIBRARY):
    """Path of a saved dataset's first frame."""
    path = _dataset_dir(dataset, library_dir) / PREVIEW_NAME
    if not path.is_file():
        raise FileNotFoundError(f"{dataset} has no preview.")
    return str(path)


def delete_calibration_dataset(dataset, library_dir=CALIBRATION_LIBRARY):
    """Remove a dataset, and its copy of the recordings, from the library. The
    ground truth file next to the original recordings stays, so reopening that
    folder brings the labels back."""
    folder = _dataset_dir(dataset, library_dir)
    if not (folder / DATASET_NAME).is_file():
        raise FileNotFoundError(f"No saved ground truth called {dataset}.")
    shutil.rmtree(folder)
    return dataset


# --- evaluation -------------------------------------------------------------------------


def _metric_version(metric, params, mites):
    """Changes whenever the scores of these mites could: another metric, other
    parameters, an edit to the scoring code, or other mites."""
    source = inspect.getsource(Analyzer)
    key = json.dumps([metric, params, source, [[m["id"], m["x"], m["y"], m["r"]] for m in mites]], sort_keys=True)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _score_mites(dataset, metric, recordings_dir, params=None):
    """Score every mite of a dataset in every recording with `metric` and its
    `params`: mite id to
    one score per recording. Slow: every frame is decoded, one recording at a
    time, and only the part of the image holding mites is kept."""
    if not Path(recordings_dir).is_dir():
        raise FileNotFoundError(
            f"The recordings of {dataset['name']} are no longer at {dataset['data_dir']} and the "
            f"library has no copy, so its mites cannot be scored with {metric}. "
            "Move them back and save its ground truth again, or leave this dataset out."
        )
    loader = DataLoader(recordings_dir, grayscale=False)
    # The same box around each mite as Mite.get_ROI() uses in an analysis run.
    boxes = {
        m["id"]: (int(round(m["x"] - m["r"])), int(round(m["y"] - m["r"])),
                  int(round(m["x"] + m["r"])), int(round(m["y"] + m["r"])))
        for m in dataset["mites"]
    }
    x0 = max(0, min(box[0] for box in boxes.values()))
    y0 = max(0, min(box[1] for box in boxes.values()))
    x_end = max(box[2] for box in boxes.values())
    y_end = max(box[3] for box in boxes.values())

    scores = {mite_id: [] for mite_id in boxes}
    for recording in dataset["recordings"]:
        frames = loader.load_recording_region(recording["name"], x0, y0, x_end, y_end)
        for mite_id, (x1, y1, x2, y2) in boxes.items():
            roi = frames[:, max(0, y1) - y0:y2 - y0, max(0, x1) - x0:x2 - x0]
            scores[mite_id].append(round(float(Analyzer._motion_score(roi, metric, params)), 3))
    return scores


def _dataset_scores(key, dataset, metric, params, library_dir):
    """The dataset's mites scored with `metric` and `params`, from the cache when
    exactly this metric, with these parameters and this scoring code, has scored
    them before. The cache is only a shortcut: deleting it just means decoding
    the recordings again."""
    version = _metric_version(metric, params, dataset["mites"])
    cache = _dataset_dir(key, library_dir) / SCORES_DIRNAME / f"{version}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))["scores"]
    scores = _score_mites(dataset, metric, _recordings_dir(dataset["data_dir"], library_dir), params)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"metric": metric, "params": params, "scores": scores}), encoding="utf-8")
    return scores


def _observations(dataset, dataset_key, scores):
    """One row per (mite, recording) of a dataset labelled moving or still, and
    the number of mites marked not a mite and of unlabelled mite-recordings."""
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
    description, its default parameters and its parameters after config.yaml's
    -- and the metric, parameters and threshold in use."""
    mite = get_default_config().mite
    return {
        "metrics": [
            {
                "name": name,
                "description": Analyzer.metric_description(name),
                "defaults": Analyzer.metric_defaults(name),
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
    }


def _resolve_metric(metric, params):
    """The metric to score with and all its parameters: the one in config.yaml
    unless `metric` is given; its defaults, then config.yaml's values for it,
    then `params`."""
    mite = get_default_config().mite
    metric = metric or mite.metric
    if metric not in Analyzer.metric_names():
        raise ValueError(f"Unknown movement score {metric!r}; choose one of {', '.join(Analyzer.metric_names())}.")
    return metric, Analyzer.check_metric_params(metric, {**mite.params_for(metric), **(params or {})})


def evaluate_calibration(out_dir, datasets, metric=None, params=None, library_dir=CALIBRATION_LIBRARY):
    """Score the saved mites with a metric and compare the scores with the
    movement the user saw, pooled over the saved datasets whose ids are in
    `datasets`.

    The metric is the one in config.yaml unless `metric` is given, with its
    parameters overridden by `params` (e.g. {"n": 20} for topN_variability), so
    other movement scores can be tried without editing the file. The threshold
    "in use" is always config.yaml's; it only fits these scores when the metric
    and parameters are config.yaml's too, which `threshold_fits` says.

    Each (mite, recording) labelled moving or still is one observation; the
    detector calls it moving when that recording's score reaches the threshold.
    Mites marked "not a mite" are left out entirely. Scoring decodes a dataset's
    recordings the first time it meets a version of the metric; later evaluations
    reuse those scores. Recordings are pooled by their order (first, second, ...)
    for the fraction moving over time.

    Returns the confusion counts at the threshold in use and, when there are
    both moving and still labels, the ROC curve and the suggested threshold with
    its confusion counts; the fraction of mites moving per recording by the
    labels and by the detector; and every observation with its outcome.
    Everything is also written to calibration.xlsx in `out_dir`.
    """
    ids = list(dict.fromkeys(datasets))
    if not ids:
        raise ValueError("Choose at least one dataset.")
    loaded = [_read_dataset(key, library_dir) for key in ids]
    metric, params = _resolve_metric(metric, params)
    in_use = _in_use(get_default_config().mite)
    current = in_use["threshold"]
    times = _pooled_times(loaded)
    n_recordings = len(times)

    rows, n_rejected, n_unlabelled, summaries = [], 0, 0, []
    for key, dataset in zip(ids, loaded):
        scores = _dataset_scores(key, dataset, metric, params, library_dir)
        here, rejected, unlabelled = _observations(dataset, key, scores)
        rows += here
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
            }
        )
    if not rows:
        raise ValueError("Mark at least one mite moving or still first.")

    scores = np.array([row["score"] for row in rows])
    is_moving = np.array([row["movement"] == calibration.MOVING for row in rows], dtype=bool)
    both = calibration.has_both_classes(is_moving)
    suggested = calibration.best_threshold(scores, is_moving) if both else None

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
        "in_use": in_use,
        "threshold_fits": metric == in_use["metric"] and params == in_use["params"],
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
        "moving_over_time": over_time(rows),
        "groups": [
            {
                "group": group,
                "n_mites": _n_mites([row for row in rows if row["group"] == group]),
                **over_time([row for row in rows if row["group"] == group]),
            }
            for group in sorted({row["group"] for row in rows})
        ],
        "observations": rows,
        "zones": _calibration_by_zone(rows),
    }
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    result["excel"] = reporting.write_calibration_excel(result, out_dir)
    return result


def save_threshold(value):
    """Make `value` the movement threshold for every analysis from now on."""
    return save_motion_threshold(value)


def save_movement_score(metric, params, threshold):
    """Make `metric` with `params`, and `threshold` on its scale, the movement
    score of every analysis from now on."""
    metric, params = _resolve_metric(metric, params)
    if not float(threshold) > 0:
        raise ValueError("The threshold must be positive.")
    return app_config.save_movement_score(metric, params, threshold)
