"""From frames to a run: find the mites on the first frame, score every
recording, and the table of their scores and calls.

The analysis core (classes/motion_analysis.py) does the work; folder runs, live
runs and calibrations all go through detect_and_score() or arrange(), so the
same frames and marks give the same results everywhere.
"""

from types import SimpleNamespace

import numpy as np

from classes.analyzer import Analyzer
from classes import plate_stabilizer
from classes.follow_up import FollowUp
from classes.frame_source import RoiSource, open_source
from classes.kept_scores import KeptScores
from classes.motion_analysis import MotionAnalysis
from classes.score_normalizer import ScoreNormalizer
from classes.unusual_activity import UnusualActivity
from pipeline import ground_truth, plate_zones


# Pixels read around the scored patches when the plate is stabilized: a mite's
# shift (followed up to 12 px) and the Lanczos interpolation's reach.
STABILIZE_MARGIN = plate_stabilizer.MARGIN


def detect_and_score(data_dir, coords_file, labels=None, reject=True, score=True,
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
    analysis = MotionAnalysis(plate_zones.zones_of(data_dir, coords_file), score=False,
                              boxes=source.boxes if rois else None, known_blobs=source.blobs() if rois else None,
                              starts=source.starts if rois else None, placements=source.placements if rois else None)
    if rois and score:
        mite = analysis.analyzer.config.mite
        source.loader.check_margin(metric_pad(mite) + (STABILIZE_MARGIN if mite.stabilize_plate else 0))
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
    arrange(analysis, data_dir, labels, reject)
    return run_view(analysis, "rois" if rois else "whole", data_dir)


def arrange(analysis, data_dir, labels, reject):
    """Name the zones by `labels` and, with `reject`, leave out the detections
    marked "not a mite" in the ground truth saved for `data_dir`, and the mites
    that flew off (classes/unusual_activity.py: their activity is worked out
    here, on every detection). Folder and live runs both go through here, so the
    same marks give the same results."""
    truth = ground_truth.load_ground_truth(data_dir) if reject else []

    def left_out(zone_manager):
        rejected = ground_truth.rejected_detections(zone_manager, truth)
        analysis.activity = UnusualActivity.of(analysis, rejected, _activity_reach(analysis.analyzer.config.mite))
        if not reject:
            return rejected
        flown = analysis.activity.fly_off_ids
        return [*rejected, *(mite for mite in analysis.mites if mite.text in flown and mite not in rejected)]

    analysis.arrange(labels, left_out)


def _activity_reach(mite):
    """Pixels from a mite's centre to the edge of its scored patch: a mite walking
    closer disturbs its recording (classes/unusual_activity.py)."""
    return float(mite.radius) + metric_pad(mite)


def metric_pad(mite):
    """Pixels the metric in use (config.yaml's `mite`) reads round a mite's box."""
    return Analyzer.roi_padding(mite.metric, mite.params_for(mite.metric))


def run_view(analysis, frames, data_dir=None):
    """`frames`: what was saved of the recordings, for the pages: "whole"
    frames, or the mites' "rois" alone (classes/roi_recordings.py); `data_dir`
    the recordings' folder, where a live run keeps the frames mites were added
    on (preview_images.added_previews())."""
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


def normalizer_in_use(mite):
    """The normalisations config.yaml puts the scores of a folder's analysis
    through (mite.normalize_brightness and mite.normalize_floor), saved there
    with the threshold from the calibration report."""
    return ScoreNormalizer(floor=mite.normalize_floor, brightness=mite.normalize_brightness)


def mite_table(run, corrections=None, normalizer=None):
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


def detected_calls(run, corrections, normalizer):
    """Mite id to the detector's call per recording on the normalised scores;
    None when they are not normalised, so the calls are the mites' own."""
    if normalizer is None or not normalizer.active:
        return None
    mite_data, _changes = mite_table(run, corrections, normalizer)
    mite_data = mite_data.assign(detected=normalizer.calls(mite_data, run.analyzer.config.mite.motion_threshold))
    return {str(mite_id): list(rows.sort_values("time")["detected"]) for mite_id, rows in mite_data.groupby("mite_ID")}
