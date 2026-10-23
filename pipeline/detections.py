""""Not a mite" marks made from the label page, kept in the ground truth."""

from pathlib import Path

from classes.ground_truth import calibration
from classes.plate import positions
from pipeline import ground_truth, paths, refusals


# What a "not a mite" mark made from the label page replaced, by folder and
# position, so taking the mark back puts the labels back.
_replaced = {}


def set_rejected(data_dir, x, y, rejected, restore=None, tolerance=positions.TOLERANCE):
    """Mark the detection at (x, y) as not a mite, or take that mark back.

    The mark goes into the session's ground truth, where an analysis run and a
    calibration both read it. Marking replaces any movement labels a calibration
    gave the detection and returns them (None if it had none). Taking the mark
    back puts back the labels passed as `restore`, so a detection marked by
    mistake and unmarked keeps its labels; without them it is left unlabelled.
    """
    data_dir = Path(data_dir)
    saved = ground_truth.load_ground_truth(data_dir)
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

    ground_truth.write_truth(data_dir, saved)
    return replaced


def mark_detection(data_dir, mites, mite_id, rejected):
    """Mark the detection `mite_id` of the label page's `mites` ([{id, zone_id, x,
    y}], as open_session() or live_preview() listed them) as not a mite, or take
    the mark back, as set_rejected() does. What a mark replaced is remembered and
    put back when the mark is taken back, so a click by mistake loses nothing.
    Returns the marks now: {mites: {id: rejected}, zones: {zone id: mites left}}."""
    mite = refusals.find(mites, mite_id, "this session", what="detection")
    key = (paths.folder_key(data_dir), mite["x"], mite["y"])
    restore = None if rejected else _replaced.pop(key, None)
    replaced = set_rejected(data_dir, mite["x"], mite["y"], rejected, restore)
    if rejected:
        _replaced[key] = replaced
    return detection_marks(data_dir, mites)


def detection_marks(data_dir, mites):
    """Which of the label page's `mites` are marked "not a mite" in the ground
    truth saved for `data_dir`, and how many mites each zone has left."""
    saved = ground_truth.load_ground_truth(data_dir)
    rejected = [entry for entry in saved if calibration.is_rejected(entry.get("truth"))]
    positions = [{"id": m["id"], "x": m["x"], "y": m["y"]} for m in mites]
    matched = calibration.match_ground_truth(positions, rejected, n_recordings=1) if rejected else {}
    marks = {m["id"]: m["id"] in matched for m in mites}
    zones = {}
    for m in mites:
        zones[m["zone_id"]] = zones.get(m["zone_id"], 0) + (not marks[m["id"]])
    return {"mites": marks, "zones": zones}
