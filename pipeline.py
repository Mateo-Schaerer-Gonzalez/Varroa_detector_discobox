"""The analysis, as a handful of functions.

This is the only module the user interface is allowed to call, and it knows nothing
about HTTP, sessions or browsers. Everything crossing this boundary is a plain dict,
list, string or number -- never a Zone, Mite, DataFrame or image array -- so the UI
can never reach into the analysis internals.

    open_session(...)          cheap: the zones to label and a preview image
    run_analysis(...)          the full pipeline, writing Excel and figures to out_dir

    open_calibration(...)      detect and score the mites of a calibration session
    calibration_clip(...)      frames of one zone in one recording, to judge by eye
    save_ground_truth(...)     store which mites the user says are alive or dead
    evaluate_calibration(...)  ROC, best threshold and errors against that truth
    save_threshold(...)        write a new movement threshold into config.yaml
"""

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

import reporting
from classes import calibration
from classes.analyzer import Analyzer
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
CALIBRATION_SCORES_NAME = "calibration_scores.json"


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
    rectangles in image pixel coordinates. Drawing is left to the caller: the UI
    gets numbers, not a picture with boxes burnt into it.
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

    return {
        "data_dir": str(data_dir),
        "preview": PREVIEW_NAME,
        "image": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
        "n_recordings": n_recordings,
        "zones": _describe_zones(zone_manager, load_labels(data_dir)),
    }


def _detect_and_score(data_dir, coords_file, labels=None, reject=True):
    """Decode every recording, find the mites and score their motion.

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
# A calibration session is a recording where the user knows which mites are alive
# at each recording. open_calibration() detects and scores the mites once and keeps
# the scores in out_dir; the user then enters the ground truth mite by mite and
# recording by recording (calibration_clip() supplies the frames to judge from),
# and evaluate_calibration() compares the two without decoding everything again.

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


def _read_calibration_scores(out_dir):
    path = Path(out_dir) / CALIBRATION_SCORES_NAME
    if not path.is_file():
        raise FileNotFoundError("This calibration session has no scores. Open the folder again.")
    return json.loads(path.read_text(encoding="utf-8"))


def open_calibration(data_dir, out_dir, coords_file=DEFAULT_COORDS_FILE):
    """Detect and score the mites of a calibration session.

    Slow: every frame is decoded. The scores are kept in `out_dir` for
    evaluate_calibration() but are *not* returned, so the page cannot show them
    while the user enters the ground truth and bias it. Detections already marked
    "not a mite" are kept here, so that the mark can be undone.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")

    labels = load_labels(data_dir)
    run = _detect_and_score(data_dir, coords_file, labels, reject=False)
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
                    "scores": [round(float(score), 3) for score in mite.motion_scores],
                }
            )
    if not mites:
        raise ValueError("No mites were detected, so there is nothing to calibrate.")
    mites.sort(key=lambda mite: int(mite["id"]))

    loader = DataLoader(data_dir, grayscale=False)
    times = [round(float(minute), 2) for minute in run.burst_minutes]
    zones = _describe_zones(run.zone_manager, labels)
    stored = {
        "data_dir": str(data_dir),
        "metric": run.analyzer.config.mite.metric,
        "times": times,
        "recordings": [{"name": d.name, "fps": loader.get_fps(d.name)} for d in loader.recording_dirs],
        "zones": zones,
        "mites": mites,
    }
    (Path(out_dir) / CALIBRATION_SCORES_NAME).write_text(json.dumps(stored), encoding="utf-8")

    return {
        "data_dir": str(data_dir),
        "preview": PREVIEW_NAME,
        "image": _image_size(run.first_frame),
        "n_recordings": run.n_recordings,
        "times": times,
        "zones": zones,
        "mites": [{key: mite[key] for key in ("id", "zone_id", "x", "y", "r")} for mite in mites],
        "truth": calibration.match_ground_truth(mites, load_ground_truth(data_dir), run.n_recordings),
        "threshold": float(run.analyzer.config.mite.motion_threshold),
    }


def calibration_clip(out_dir, recording, zone_id):
    """Frames of one zone during one recording, so the user can see which mites move.

    Writes up to CLIP_MAX_FRAMES JPEG crops to `out_dir` (once; later calls reuse
    them) and returns their filenames, where the crop sits in the full image, and
    the delay between frames that plays them back in real time.
    """
    stored = _read_calibration_scores(out_dir)
    if not 0 <= recording < len(stored["recordings"]):
        raise ValueError(f"No recording {recording} in this session.")
    zone = next((zone for zone in stored["zones"] if zone["id"] == zone_id), None)
    if zone is None:
        raise ValueError(f"No zone {zone_id} in this session.")

    name = f"clip_r{recording}_z{zone_id}"
    manifest = Path(out_dir) / f"{name}.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))

    loader = DataLoader(stored["data_dir"], grayscale=False)
    source = stored["recordings"][recording]
    step = max(1, int(np.ceil(loader.count_frames(source["name"]) / CLIP_MAX_FRAMES)))
    x1, y1 = max(0, zone["x1"] - CLIP_MARGIN), max(0, zone["y1"] - CLIP_MARGIN)
    frames = loader.load_recording_region(
        source["name"], x1, y1, zone["x2"] + CLIP_MARGIN, zone["y2"] + CLIP_MARGIN, step=step
    )

    names = []
    for index, frame in enumerate(frames):
        names.append(f"{name}_{index:02d}.jpg")
        cv2.imwrite(str(Path(out_dir) / names[-1]), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    clip = {
        "frames": names,
        "x": int(x1),
        "y": int(y1),
        "width": int(frames.shape[2]),
        "height": int(frames.shape[1]),
        "interval_ms": int(round(1000 * step / source["fps"])),
    }
    manifest.write_text(json.dumps(clip), encoding="utf-8")
    return clip


def save_ground_truth(out_dir, truth):
    """Store the ground truth next to the recordings, by mite position.

    `truth` maps mite id to a list with one status per recording: "alive",
    "dead", "not_a_mite" or None for unlabelled. Positions rather than ids are
    stored, so the file still applies after a change of detector settings
    renumbers the mites.
    """
    stored = _read_calibration_scores(out_dir)
    n_recordings = len(stored["times"])
    entries = []
    for mite in stored["mites"]:
        states = calibration.per_recording(truth.get(mite["id"]), n_recordings)
        if any(states):
            entries.append({"x": mite["x"], "y": mite["y"], "truth": states})
    path = Path(stored["data_dir"]) / GROUND_TRUTH_FILENAME
    path.write_text(json.dumps(entries), encoding="utf-8")
    return len(entries)


def _calibration_by_zone(observations):
    """Per zone: labelled mites and observations, and how many were called wrong
    at the threshold in use."""
    zones = []
    for zone_id in sorted({row["zone_id"] for row in observations}):
        rows = [row for row in observations if row["zone_id"] == zone_id]
        zones.append(
            {
                "id": zone_id,
                "n_mites": len({row["mite_id"] for row in rows}),
                "n_observations": len(rows),
                "n_alive": sum(row["truth"] == calibration.ALIVE for row in rows),
                "n_dead": sum(row["truth"] == calibration.DEAD for row in rows),
                "n_errors": sum(row["outcome"].endswith("_missed") for row in rows),
            }
        )
    return zones


def _rounded(values, digits=4):
    return [None if value is None else round(float(value), digits) for value in values]


def evaluate_calibration(out_dir, truth):
    """Compare the stored scores with the ground truth, recording by recording.

    Each (mite, recording) with an alive or dead ground truth is one observation.
    Mites marked "not a mite" are left out entirely. Returns the confusion counts
    and survival curves at the threshold in use and, when both alive and dead
    observations exist, the ROC curve and the best threshold. Everything is also
    written to calibration.xlsx in `out_dir`.
    """
    stored = _read_calibration_scores(out_dir)
    current = float(get_default_config().mite.motion_threshold)
    times = stored["times"]
    n_recordings = len(times)
    groups = {zone["id"]: zone["label"] or UNLABELED for zone in stored["zones"]}

    observations, n_rejected, n_unlabelled = [], 0, 0
    for mite in stored["mites"]:
        states = calibration.per_recording(truth.get(mite["id"]), n_recordings)
        if calibration.is_rejected(states):
            n_rejected += 1
            continue
        called_score = calibration.forward_max(mite["scores"])
        for recording, state in enumerate(states):
            if state not in (calibration.ALIVE, calibration.DEAD):
                n_unlabelled += 1
                continue
            observations.append(
                {
                    "mite_id": mite["id"],
                    "zone_id": mite["zone_id"],
                    "group": groups.get(mite["zone_id"], UNLABELED),
                    "x": mite["x"],
                    "y": mite["y"],
                    "recording": recording,
                    "time": times[recording],
                    "truth": state,
                    "recording_score": mite["scores"][recording],
                    # what the call at this recording depends on: see forward_max
                    "score": round(called_score[recording], 3),
                }
            )
    if not observations:
        raise ValueError("Enter the ground truth of at least one mite first.")

    scores = np.array([row["score"] for row in observations])
    is_alive = np.array([row["truth"] == calibration.ALIVE for row in observations], dtype=bool)
    both = calibration.has_both_classes(is_alive)
    suggested = calibration.best_threshold(scores, is_alive) if both else None

    thresholds = {"current": current}
    if suggested is not None:
        thresholds["suggested"] = suggested
    for row in observations:
        row["outcome"] = calibration.outcome(row["truth"], row["score"], current)
        if suggested is not None:
            row["outcome_suggested"] = calibration.outcome(row["truth"], row["score"], suggested)

    def survival(rows):
        curves = calibration.survival(rows, n_recordings, thresholds)
        return {key: values if key == "n" else _rounded(values) for key, values in curves.items()}

    roc = None
    if both:
        fpr, tpr, roc_thresholds = calibration.roc_curve(scores, is_alive)
        roc = {
            "fpr": _rounded(fpr),
            "tpr": _rounded(tpr),
            # the first point is at an infinite threshold, which JSON cannot hold
            "thresholds": [None if np.isinf(t) else round(float(t), 3) for t in roc_thresholds],
        }

    group_names = sorted({row["group"] for row in observations})
    result = {
        "metric": stored["metric"],
        "times": times,
        "threshold": current,
        "suggested_threshold": None if suggested is None else round(suggested, 3),
        "auc": calibration.auc(scores, is_alive) if both else None,
        "roc": roc,
        "n_mites": len({row["mite_id"] for row in observations}),
        "n_observations": len(observations),
        "n_alive": int(is_alive.sum()),
        "n_dead": int((~is_alive).sum()),
        "n_not_a_mite": n_rejected,
        "n_unlabelled": n_unlabelled,
        "current": calibration.confusion(scores, is_alive, current),
        "best": calibration.confusion(scores, is_alive, suggested) if suggested is not None else None,
        "survival": survival(observations),
        "group_survival": [
            {
                "group": group,
                "n_mites": len({row["mite_id"] for row in observations if row["group"] == group}),
                **survival([row for row in observations if row["group"] == group]),
            }
            for group in group_names
        ],
        "observations": observations,
        "zones": _calibration_by_zone(observations),
    }
    result["excel"] = reporting.write_calibration_excel(result, out_dir)
    return result


def save_threshold(value):
    """Make `value` the movement threshold for every analysis from now on."""
    return save_motion_threshold(value)
