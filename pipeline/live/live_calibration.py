"""A calibration session on a live run's recordings, to enter their ground
truth and poke test while the run goes on.
"""

from pathlib import Path

from pipeline import preview_images
from pipeline.calibration import calibration_sessions, session_file, truth_entry
from pipeline.live import live_runs


def open_live_calibration(live_id, out_dir):
    """A calibration session on a live run's recordings, to enter their ground
    truth and poke test while the run goes on: open_calibration() of the run's
    folder, but of the recordings analysed so far alone, the one being captured
    left out. grow_live_calibration() adds the recordings that come after. The
    ground truth is judged on the recordings' clips and kept with them, so the
    run must save its recordings."""
    run = live_runs.get_live(live_id)
    if not run.save_frames:
        raise ValueError("This test run does not save its recordings, so there is no clip to enter a ground truth "
                         "on and no folder to keep it in.")
    names = list(run.session.recordings)
    if not names:
        raise ValueError("The ground truth and the poke test can be entered once the first recording is analysed.")
    stored = calibration_sessions.calibration_session(run.run_dir, run.coords_file, out_dir, names)
    return calibration_sessions.opened_calibration(stored, out_dir)


def grow_live_calibration(out_dir, live_id):
    """Bring a calibration session made by open_live_calibration() up to the
    recordings its live run has analysed since: they come unlabelled, and the
    ground truth's changes not saved yet stay (TruthDraft.grow()). The mites
    are described again too: the run may have added some, or counted some dead
    and stopped following them (calibration.followed()). Returns the
    session as open_live_calibration() does. A session showing another dataset
    by now, e.g. one a pooled report opened, is left as it is."""
    run = live_runs.get_live(live_id)
    stored = session_file.read_calibration_session(out_dir)
    names = list(run.session.recordings)
    if Path(stored["data_dir"]) == run.run_dir.resolve() and len(names) > len(stored["recordings"]):
        described, _first_frame = session_file.describe_calibration(run.run_dir, run.coords_file, names)
        stored.update({key: described[key] for key in ("times", "recordings", "mites")})
        stored["previews"] = preview_images.added_previews(run.run_dir, out_dir, len(stored["times"]))
        session_file.write_calibration_session(out_dir, stored)
        draft = truth_entry.draft_of(out_dir)
        with truth_entry.drafts_lock:
            draft.grow(len(stored["times"]))
            draft.set_mites(stored["mites"])
    return {**calibration_sessions.calibration_view(stored, truth_entry.saved_truth(stored)),
            "truth_view": truth_entry.truth_view(out_dir)}
