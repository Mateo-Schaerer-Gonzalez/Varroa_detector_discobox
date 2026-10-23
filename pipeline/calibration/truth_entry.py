"""The ground truth entered on the ground-truth page.

The changes made on the page wait here, one draft per calibration session (keyed
by its folder), until they are saved: the page saves them as soon as they are
made, and a click need not wait for the disk. What the page shows is always what
saving them will store (see classes/ground_truth/truth_draft.py). Every view carries a
version, higher for every view made, so the page can tell which reply is the
latest.
"""

import itertools
import threading

from classes.ground_truth import calibration
from classes.plate import positions
from classes.ground_truth.truth_draft import TruthDraft
from pipeline import ground_truth, paths, refusals
from pipeline.calibration import session_file


# The drafts, one per calibration session by its folder (paths.folder_key()), the
# lock for them all, and the views' versions.
_drafts = {}
drafts_lock = threading.Lock()
_truth_versions = itertools.count(1)


def save_ground_truth(out_dir, truth):
    """Store the ground truth next to the recordings, by mite position.

    `truth` maps mite id to a list with one status per recording: "moving",
    "still", "not_a_mite" or None for unlabelled. Positions rather than ids are
    stored, so the file still applies after a change of detector settings
    renumbers the mites.
    """
    return len(_write_ground_truth(session_file.read_calibration_session(out_dir), truth))


def update_ground_truth(out_dir, changes):
    """Save the changes made on screen on top of what is saved, which another
    window (marking a detection "not a mite" before a run, say) may have changed
    since this session opened. `changes` maps mite id to the statuses that
    changed, by recording index, or to a list of every recording's (see
    calibration.apply_changes()); only those recordings change, so a page that
    has not caught up with a change made elsewhere cannot undo it. Returns the
    whole ground truth by mite id, as save_ground_truth() takes it."""
    stored = session_file.read_calibration_session(out_dir)
    truth = saved_truth(stored)
    for mite_id, changed in changes.items():
        truth[mite_id] = calibration.apply_changes(truth.get(mite_id), changed, len(stored["times"]))
    return _write_ground_truth(stored, truth)


def new_draft(out_dir, stored, truth):
    draft = TruthDraft(stored["mites"], stored["zones"], len(stored["times"]), truth)
    with drafts_lock:
        _drafts[paths.folder_key(out_dir)] = draft
    return draft


def draft_of(out_dir):
    with drafts_lock:
        draft = _drafts.get(paths.folder_key(out_dir))
    if draft is None:  # e.g. the server restarted: start again from what is saved
        stored = session_file.read_calibration_session(out_dir)
        draft = new_draft(out_dir, stored, saved_truth(stored))
    return draft


def draft_view(draft, changed=False):
    """The draft's view (TruthDraft.view()), its version, and whether what is shown
    changed. Called holding drafts_lock."""
    return {**draft.view(), "version": next(_truth_versions), "changed": changed}


def truth_view(out_dir):
    """The ground truth of a calibration session as saved now, which another
    window or the analysis (marking a detection "not a mite") may have changed,
    with the changes not saved yet on top."""
    draft = draft_of(out_dir)
    with drafts_lock:
        saves = draft.saves
    saved = load_calibration_truth(out_dir)
    with drafts_lock:
        # A save that landed while this was read already brought newer truth.
        changed = draft.load(saved) if draft.saves == saves else False
        return draft_view(draft, changed)


def edit_truth(out_dir, action, mite=None, zone=None, recording=0, backwards=False, kind=None, state=None):
    """A change on the ground-truth page, not saved yet: "set" a `mite`'s status
    in `recording` to `state` ("moving", "still", "not_a_mite" or None for
    unlabelled), mark it "dead" from `recording` on (TruthDraft.dead_from()),
    "cycle" it to its next status there (its previous one with `backwards`), or
    "fill" the unlabelled mites of a `zone` in `recording` by `kind` (see
    TruthDraft.fill)."""
    draft = draft_of(out_dir)
    with drafts_lock:
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
        return draft_view(draft, changed=True)


def save_truth(out_dir):
    """Save the changes made on the ground-truth page on top of what is saved
    (update_ground_truth()); changes made while saving wait for the next save."""
    draft = draft_of(out_dir)
    with drafts_lock:
        sent = draft.unsaved_now()
    changed = False
    if sent:
        saved = update_ground_truth(out_dir, sent)
        with drafts_lock:
            changed = draft.saved_as(sent, saved)
    with drafts_lock:
        return draft_view(draft, changed)


def load_calibration_truth(out_dir):
    """The ground truth saved for a calibration session's mites, by mite id."""
    return saved_truth(session_file.read_calibration_session(out_dir))


def saved_truth(stored):
    """The saved ground truth of a calibration session's mites, by mite id."""
    saved = ground_truth.load_ground_truth(stored["data_dir"])
    return calibration.match_ground_truth(stored["mites"], saved, len(stored["times"]))


def _write_ground_truth(stored, truth, tolerance=positions.TOLERANCE):
    """Write the ground truth of a calibration session's mites (`truth`, by
    mite id) next to its recordings, by position; returns the mites labelled."""
    n_recordings = len(stored["times"])
    labelled = {}
    for mite in stored["mites"]:
        states = calibration.per_recording(truth.get(mite["id"]), n_recordings)
        if any(states):
            labelled[mite["id"]] = states

    recordings_dir = refusals.recordings_dir(stored, "the ground truth cannot be saved with them")
    if True:
        entries = [{"x": mite["x"], "y": mite["y"], "truth": labelled[mite["id"]]}
                   for mite in stored["mites"] if mite["id"] in labelled]
        # Entries away from every mite of this session, e.g. detections marked
        # "not a mite" under other detector settings, are not this session's to drop.
        entries += [entry for entry in ground_truth.load_ground_truth(recordings_dir)
                    if positions.away_from_all(entry, stored["mites"], tolerance)]
        ground_truth.write_truth(recordings_dir, entries)
    return labelled
