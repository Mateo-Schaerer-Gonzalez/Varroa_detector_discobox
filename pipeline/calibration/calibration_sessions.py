"""A calibration session is a recording in which the user marks, mite by mite and
recording by recording, whether each mite moves. open_calibration() detects the
mites and keeps them in out_dir; the clips supply the frames to judge movement
from; calibration_report.evaluate_calibration() scores the labelled mites with
the metric in use and compares the scores with the labels. Only the ground truth
is saved, never the scores, so old recordings can be used to judge new metrics.
"""

from pathlib import Path

from classes.app_config import get_default_config
from classes.roi_recordings import open_recordings
from pipeline import clips, paths, preview_images, refusals
from pipeline.calibration import dataset_library, session_file, truth_entry


def calibration_view(stored, truth):
    """What the ground-truth page needs about a calibration session."""
    return {
        "data_dir": stored["data_dir"],
        "dataset_id": paths.dataset_id(stored["data_dir"]),
        "recordings_available": Path(stored["data_dir"]).is_dir(),
        "preview": paths.PREVIEW_NAME,
        # the picture to draw each recording's mites on (preview_images.added_previews()); the first frame
        # throughout for a session written before it had them
        "previews": stored.get("previews") or [paths.PREVIEW_NAME] * len(stored["times"]),
        "image": stored["image"],
        "n_recordings": len(stored["times"]),
        "times": stored["times"],
        "recordings": [recording["name"] for recording in stored["recordings"]],
        "zones": stored["zones"],
        "mites": stored["mites"],
        "truth": truth,
        "threshold": float(get_default_config().mite.motion_threshold),
    }


def opened_calibration(stored, out_dir):
    """The ground-truth page's view of a calibration session just opened in
    `out_dir`, whose ground truth is entered from scratch: no changes yet."""
    truth = truth_entry.saved_truth(stored)
    draft = truth_entry.new_draft(out_dir, stored, truth)
    with truth_entry.drafts_lock:
        return {**calibration_view(stored, truth), "truth_view": truth_entry.draft_view(draft)}


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
    stored = calibration_session(data_dir, coords_file, out_dir)
    return opened_calibration(stored, out_dir)


def calibration_session(data_dir, coords_file, out_dir, names=None):
    """Detect the mites of a calibration session, on the first frame, write its
    preview to `out_dir`, and keep there what it is (calibration_session.json).
    With `names`, only the recordings of those names make the session."""
    stored, first_frame = session_file.describe_calibration(data_dir, coords_file, names)
    preview_images.write_preview(first_frame, out_dir)
    stored["previews"] = preview_images.added_previews(data_dir, out_dir, len(stored["times"]))
    session_file.write_calibration_session(out_dir, stored)
    return stored


def calibration_clip(out_dir, recording, zone_id):
    """Frames of one zone during one recording, so the user can see which mites move.

    Writes up to CLIP_MAX_FRAMES JPEG crops to `out_dir` (once; later calls reuse
    them) and returns their filenames, where the crop sits in the full image, and
    the delay between frames that plays them back in real time.
    """
    stored = session_file.read_calibration_session(out_dir)
    refusals.check_recording(recording, len(stored["recordings"]))
    zone = next((zone for zone in stored["zones"] if zone["id"] == zone_id), None)
    if zone is None:
        raise ValueError(f"No zone {zone_id} in this session.")

    # One session can switch between datasets, so clips are named after theirs.
    name = f"clip_{clips.clip_key(paths.dataset_id(stored['data_dir']))}_r{recording}_z{zone_id}"
    source = stored["recordings"][recording]
    margin = clips.CLIP_MARGIN
    box = (zone["x1"] - margin, zone["y1"] - margin, zone["x2"] + margin, zone["y2"] + margin)
    # the recordings are only needed for a clip not kept yet
    return clips.write_clip(lambda: open_recordings(refusals.recordings_dir(stored, "there is no clip to play")),
                            source["name"], source["fps"], box, out_dir, name)


def calibration_mite_clip(out_dir, recording, mite_id):
    """Frames of one mite during one recording of a calibration session, cut
    close around it, for the ground-truth page (see clips.mite_clip())."""
    stored = session_file.read_calibration_session(out_dir)
    refusals.check_recording(recording, len(stored["recordings"]))
    mite = refusals.find(stored["mites"], mite_id, "this session")
    recordings_dir = refusals.recordings_dir(stored, "there is no clip to play")
    return clips.mite_clip(recordings_dir, stored["recordings"][recording], mite, out_dir,
                           f"mite_{clips.clip_key(paths.dataset_id(stored['data_dir']))}_r{recording}")


def open_saved_calibration(dataset, out_dir, recordings_root=paths.RECORDINGS_ROOT):
    """Reopen a dataset to go on labelling it: open_calibration() of its folder.
    `out_dir` may already hold another dataset -- a pooled report jumping to
    one of its mites -- which this one then replaces; the files of earlier
    evaluations stay."""
    return open_calibration(dataset_library.dataset_dir(dataset, recordings_root), out_dir)
