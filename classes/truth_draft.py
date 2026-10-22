"""The ground truth being entered on the calibration's ground-truth page: what is
saved, with the changes not saved yet on top.

Each mite has one status per recording: "moving", "still", "not_a_mite" or None
(unlabelled). Movement is judged recording by recording -- a mite still in one
recording may move in the next -- so a click changes one recording. "Not a mite"
is about the detection, not about a recording, so it marks every recording;
leaving it brings back the statuses the mite had before it was marked here, so
clicking through "not a mite" on the way from still to moving loses nothing. A
mite marked elsewhere, or before the dataset was opened, is left unlabelled.

A mite a live run did not follow in a recording (added later, or counted dead:
calibration.followed()) has nothing to label there: those recordings cannot be
labelled, are none of the mite-recordings to do and count as "not_followed".

Only the statuses changed are kept as changes, mite by mite and recording by
recording, and what is shown is always calibration.apply_changes() of them on
the saved statuses: exactly what saving them will store, even when another
window changed what is saved meanwhile.
"""

import copy

from classes.calibration import MOVING, NOT_A_MITE, STILL, apply_changes, followed, is_rejected, per_recording

# A click on a mite steps through these; None is unlabelled.
CYCLE = (None, MOVING, STILL, NOT_A_MITE)
# The fill buttons: label every unlabelled mite of a zone moving or still, as in
# the recording before, or clear the zone's labels in one recording. "dead" labels
# them still from the recording on to the last one: a dead mite does not move again.
FILLS = (MOVING, STILL, "previous", "dead", "clear")
COUNTED = {MOVING: MOVING, STILL: STILL, NOT_A_MITE: NOT_A_MITE, None: "unset"}


class TruthDraft:
    def __init__(self, mites, zones, n_recordings, saved=None):
        """`mites`: [{id, zone_id[, start, stop]}, ...] (start and stop: see
        calibration.followed()); `zones`: [{id}, ...] in page order; `saved`:
        mite id -> statuses, as saved."""
        self.n = n_recordings
        self.zones = list(zones)
        self.set_mites(mites)
        self.saved = {}
        self.unsaved = {}            # mite id -> {recording: status} changed and not saved yet
        self.before_rejection = {}   # mite id -> its statuses before it was marked "not a mite" here
        self.saves = 0               # saves applied, so a reload read before one does not undo it
        self.load(saved or {})

    # --- what is shown

    def states(self, mite_id):
        changes = self.unsaved.get(mite_id)
        return apply_changes(self.saved.get(mite_id), changes, self.n) if changes else per_recording(self.saved.get(mite_id), self.n)

    def shown(self):
        """mite id -> statuses, for the mites with any status."""
        return {mite_id: states for mite_id in self.mite_ids if any(states := self.states(mite_id))}

    def followed(self, mite_id, recording):
        """Whether the mite was followed in the recording, so has a label to give there."""
        return followed(self.span[mite_id], recording)

    def cell_done(self, mite_id, recording):
        """Whether a mite needs nothing more in a recording: labelled, not a mite
        at all, or not followed there."""
        states = self.states(mite_id)
        return is_rejected(states) or states[recording] is not None or not self.followed(mite_id, recording)

    def mites_in(self, zone_id):
        return [mite_id for mite_id in self.mite_ids if self.zone_of[mite_id] == zone_id]

    # --- changes

    def set(self, mite_id, recording, state):
        """Give one mite one status in one recording (see the module's docstring).
        "Not a mite" can be given in a recording the mite was not followed in,
        being about the detection; nothing else can."""
        self._check(mite_id, recording)
        if state != NOT_A_MITE and not self.followed(mite_id, recording):
            raise ValueError(f"Mite {mite_id} was not followed in recording {recording + 1}: "
                             "it was added later, or counted dead before, so there is nothing to label.")
        before = self.states(mite_id)
        rejected = is_rejected(before)
        if state == NOT_A_MITE:
            if not rejected:
                self.before_rejection[mite_id] = before
            states = [NOT_A_MITE] * self.n
        else:
            restored = self.before_rejection.pop(mite_id, None)
            states = list((restored or [None] * self.n) if rejected else before)
            states[recording] = state
        changed = self.unsaved.get(mite_id, {})
        changed.update({r: s for r, s in enumerate(states) if s != before[r]})
        if changed:
            self.unsaved[mite_id] = changed

    def cycle(self, mite_id, recording, backwards=False):
        """The next status in CYCLE (the previous one with `backwards`)."""
        self._check(mite_id, recording)
        index = CYCLE.index(self.states(mite_id)[recording])
        self.set(mite_id, recording, CYCLE[(index + (-1 if backwards else 1)) % len(CYCLE)])

    def fill(self, zone_id, recording, kind):
        """Label every unlabelled mite of a zone in one recording by `kind` (see FILLS);
        "dead" also labels the recordings after it, where the mite is unlabelled."""
        if kind not in FILLS:
            raise ValueError(f"Unknown fill {kind!r}.")
        for mite_id in self.mites_in(zone_id):
            states = self.states(mite_id)
            if kind == "dead":
                if not is_rejected(states):
                    for later in range(recording, self.n):
                        if states[later] is None and self.followed(mite_id, later):
                            self.set(mite_id, later, STILL)
            elif not self.followed(mite_id, recording):
                continue
            elif kind == "clear":
                if not is_rejected(states):
                    self.set(mite_id, recording, None)
            elif not self.cell_done(mite_id, recording):
                state = (states[recording - 1] if recording > 0 else None) if kind == "previous" else kind
                if state:
                    self.set(mite_id, recording, state)

    def dead_from(self, mite_id, recording):
        """One mite is dead from `recording` on: still in it, and in every later
        recording it has no label in yet. A dead mite does not move again, but
        a later label says the eye saw otherwise, so it stays."""
        self._check(mite_id, recording)
        self.set(mite_id, recording, STILL)
        for later in range(recording + 1, self.n):
            if self.states(mite_id)[later] is None and self.followed(mite_id, later):
                self.set(mite_id, later, STILL)

    def _check(self, mite_id, recording):
        if mite_id not in self.zone_of:
            raise ValueError(f"No mite {mite_id} in this dataset.")
        if not 0 <= recording < self.n:
            raise ValueError(f"No recording {recording} in this dataset.")

    def set_mites(self, mites):
        """The dataset's mites, e.g. a live run's again once it added some or
        counted some dead: their statuses and changes stay, by id."""
        self.mite_ids = [mite["id"] for mite in mites]
        self.zone_of = {mite["id"]: mite["zone_id"] for mite in mites}
        self.span = {mite["id"]: {"start": mite.get("start", 0), "stop": mite.get("stop")} for mite in mites}
        self.zone_ids = [zone["id"] for zone in self.zones if any(z == zone["id"] for z in self.zone_of.values())]

    def grow(self, n_recordings):
        """The dataset has more recordings, e.g. a live run's, recorded since: they
        come unlabelled, and the changes not saved yet stay. A mite marked "not a
        mite" is marked in them too."""
        if n_recordings <= self.n:
            return
        self.n = n_recordings
        self.saved = {mite_id: [NOT_A_MITE] * n_recordings if is_rejected(states) else per_recording(states, n_recordings)
                      for mite_id, states in self.saved.items()}
        self.before_rejection = {mite_id: per_recording(states, n_recordings)
                                 for mite_id, states in self.before_rejection.items()}

    # --- saving

    def load(self, saved):
        """Show `saved` as what is saved, with the changes not saved yet on top.
        Returns whether what is shown changed."""
        before = self.shown()
        self.saved = {mite_id: per_recording(states, self.n) for mite_id, states in saved.items()}
        # Statuses to bring back belong to "not a mite" marks still shown.
        self.before_rejection = {mite_id: states for mite_id, states in self.before_rejection.items()
                                 if is_rejected(self.states(mite_id))}
        return self.shown() != before

    def unsaved_now(self):
        """The changes to save, as they are now."""
        return copy.deepcopy(self.unsaved)

    def saved_as(self, sent, saved):
        """The changes `sent` (from unsaved_now()) were saved, and `saved` is now
        what is saved. A status changed again since stays to be saved. Returns
        whether what is shown changed, e.g. by a change saved in another window."""
        for mite_id, changes in sent.items():
            waiting = self.unsaved.get(mite_id, {})
            for recording, state in changes.items():
                if waiting.get(recording, object()) == state:
                    del waiting[recording]
            if not waiting:
                self.unsaved.pop(mite_id, None)
        self.saves += 1
        return self.load(saved)

    # --- for the page

    def view(self):
        """What the ground-truth page shows:

            states            mite id -> statuses, for the mites with any
            unsaved           how many mites have changes not saved yet
            cells, done       mite-recordings to label in all (those the mites were
                              followed in), and those needing nothing more
            followed          mite id -> per recording whether it was followed there,
                              for the mites a live run did not follow in every one
            ready             a mite is labelled moving or still somewhere: a report can be made
            zones_with_mites  the zones to visit, in order
            zones             zone id -> {done (per recording: every mite labelled),
                              n_done, complete, counts (per recording)}
            counts            per recording, how many mites have each status ("unset": none;
                              with mites not followed throughout, "not_followed": not there)
            next              [zone id, recording] of the first zone and recording with a
                              mite still to label; None when every one is done
            next_mite         [mite id, recording] of the first mite, in their order, and
                              its first recording still to label; None when every one is done
            mites_done        mite id -> how many of its recordings to label need nothing more
            mites_cells       mite id -> how many of its recordings there are to label
        """
        recordings = range(self.n)
        states = {mite_id: self.states(mite_id) for mite_id in self.mite_ids}
        follows = {mite_id: [self.followed(mite_id, r) for r in recordings] for mite_id in self.mite_ids}
        done_cell = {mite_id: [is_rejected(s) or s[r] is not None or not follows[mite_id][r] for r in recordings]
                     for mite_id, s in states.items()}

        partly = any(not all(there) for there in follows.values())  # a live run's mites not followed throughout

        def counts(mite_ids, recording):
            counted = {**dict.fromkeys(COUNTED.values(), 0), **({"not_followed": 0} if partly else {})}
            for mite_id in mite_ids:
                counted[COUNTED[states[mite_id][recording]] if follows[mite_id][recording] else "not_followed"] += 1
            return counted

        zones = {}
        upcoming = None
        for zone_id in self.zone_ids:
            mites = self.mites_in(zone_id)
            done = [all(done_cell[m][r] for m in mites) for r in recordings]
            zones[zone_id] = {"done": done, "n_done": sum(done), "complete": all(done),
                              "counts": [counts(mites, r) for r in recordings]}
            if upcoming is None and not all(done):
                upcoming = [zone_id, done.index(False)]
        waiting = next((mite_id for mite_id in self.mite_ids if not all(done_cell[mite_id])), None)
        return {
            "next_mite": None if waiting is None else [waiting, done_cell[waiting].index(False)],
            "mites_done": {mite_id: sum(done and there for done, there in zip(cells, follows[mite_id]))
                           for mite_id, cells in done_cell.items()},
            "mites_cells": {mite_id: sum(there) for mite_id, there in follows.items()},
            "followed": {mite_id: there for mite_id, there in follows.items() if not all(there)},
            "states": {mite_id: s for mite_id, s in states.items() if any(s)},
            "unsaved": len(self.unsaved),
            "cells": sum(sum(there) for there in follows.values()),
            "done": sum(done and there for mite_id, cells in done_cell.items() for done, there in zip(cells, follows[mite_id])),
            "ready": any(not is_rejected(s) and any(state in (MOVING, STILL) for state in s) for s in states.values()),
            "zones_with_mites": self.zone_ids,
            "zones": zones,
            "counts": [counts(self.mite_ids, r) for r in recordings],
            "next": upcoming,
        }
