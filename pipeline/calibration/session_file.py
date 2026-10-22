"""What a calibration session is: the mites found on the first frame of a
recording folder, its zones and its recordings, worked out from the folder
(describe_calibration()) and kept in calibration_session.json in the session's
folder.
"""

from pathlib import Path

from classes.files import read_json, write_json
from classes.frame_source import open_source
from classes.mite import Mite
from pipeline import paths, plate_labels, plate_zones, preview_images, scoring


def read_calibration_session(out_dir):
    stored = read_json(Path(out_dir) / paths.CALIBRATION_SESSION_NAME)
    if stored is None:
        raise FileNotFoundError("This calibration session has no mites. Open the folder again.")
    return stored


def describe_calibration(data_dir, coords_file=None, names=None):
    """(stored, first frame): what a calibration session of `data_dir` is -- its
    recordings and their times, the image's size, the zones with their labels
    and the mites found on the first frame -- and that frame."""
    labels = plate_labels.load_labels(data_dir)
    run = scoring.detect_and_score(data_dir, coords_file, labels, reject=False, score=False, names=names)

    # with the recordings a live run followed each in (calibration.followed()): from the
    # one it was added in (0 but for one added later), up to the one it counted dead from
    mites = [plate_zones.mite_view(mite, zone.id, start=mite.start, stop=mite.stopped)
             for zone in run.zone_manager.zones for mite in zone.mites]
    if not mites:
        raise ValueError("No mites were detected, so there is nothing to calibrate.")
    mites.sort(key=lambda mite: Mite.id_order(mite["id"]))

    stored = {
        "data_dir": str(Path(data_dir).resolve()),
        **_calibration_recordings(data_dir, names),
        "image": preview_images.image_size(run.first_frame),
        "zones": plate_zones.describe_zones(run.zone_manager, labels),
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


def write_calibration_session(out_dir, stored):
    """Written whole before it takes the name: a live run's session grows while
    its pages read it."""
    write_json(Path(out_dir) / paths.CALIBRATION_SESSION_NAME, stored)
