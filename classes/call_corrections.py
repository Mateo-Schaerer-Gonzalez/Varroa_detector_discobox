"""The detector's calls the user corrected by hand on the result pages.

The detector calls a mite moving in a recording when its score there reaches the
threshold. Where the user sees it got one wrong, they change that one call on
the mite's page, and every number of the results follows: the correction
replaces the detector's call in the mite score table, before anything is worked
out from it.

A mite can also be marked gone, e.g. one that fell off the plate: in one
recording, or from a recording on. In a recording in which it is gone the mite
is censored: it counts neither as moving nor as still, and a mite gone from a
recording on leaves the survival numbers there, alive as far as is known
(classes/survival.py).

The corrections are kept next to the recordings, in corrections.json, so they
survive a restart and another run. Like the ground truth they go by the mite's
position, not its id, so they still apply after a change of detector settings
renumbers the mites. They are kept per pool size, as a recording's index means
another stretch of frames with another one:

    {"recording": [{"x": 412.5, "y": 230.0, "moving": {"3": true}, "gone": [1], "gone_from": 5}], "30": [...]}

A call the user looked at and set, the detector's or not, can be kept as checked
("checked": [recording, ...]), so the result pages do not ask for it again
(classes/review_band.py).
"""

import json
from pathlib import Path

import numpy as np

MOVING = "moving"
STILL = "still"
GONE = "gone"            # gone in one recording
GONE_FROM = "gone_from"  # gone from a recording on
# A click on the mite steps through these.
CYCLE = (MOVING, STILL, GONE, GONE_FROM)


class CallCorrections:
    FILENAME = "corrections.json"
    WHOLE_RECORDINGS = "recording"  # the key of the corrections made without a pool size

    def __init__(self, data_dir, pool_size=None, tolerance=10.0):
        self.path = Path(data_dir) / self.FILENAME
        self.key = self.WHOLE_RECORDINGS if pool_size is None else str(int(pool_size))
        self.tolerance = tolerance

    # --- the file

    def _read(self):
        """Everything saved, by pool size; nothing from a missing or damaged file."""
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return saved if isinstance(saved, dict) else {}

    def entries(self):
        """The corrections of this pool size, one entry per mite:
        [{x, y, moving: {recording: call}, gone: [recording, ...], gone_from: recording or None,
        checked: [recording, ...]}]."""
        saved = self._read().get(self.key, [])
        entries = []
        for entry in saved if isinstance(saved, list) else []:
            if not isinstance(entry, dict) or "x" not in entry or "y" not in entry:
                continue
            moving, gone, since = entry.get("moving"), entry.get("gone"), entry.get("gone_from")
            checked = entry.get("checked")
            entries.append({
                "x": entry["x"], "y": entry["y"],
                "moving": moving if isinstance(moving, dict) else {},
                "gone": sorted({r for r in gone if isinstance(r, int)}) if isinstance(gone, list) else [],
                "gone_from": since if isinstance(since, int) else None,
                "checked": sorted({r for r in checked if isinstance(r, int)}) if isinstance(checked, list) else [],
            })
        return entries

    def _write(self, entries):
        saved = self._read()
        saved[self.key] = [{key: value for key, value in entry.items() if key != "checked" or value} for entry in entries
                           if entry["moving"] or entry["gone"] or entry["gone_from"] is not None or entry["checked"]]
        if not saved[self.key]:
            del saved[self.key]
        self.path.write_text(json.dumps(saved), encoding="utf-8")

    def _nearest(self, entries, x, y):
        """The entry of the mite at (x, y): the nearest within the tolerance, or None."""
        near = [(np.hypot(entry["x"] - x, entry["y"] - y), index) for index, entry in enumerate(entries)]
        near = [(distance, index) for distance, index in near if distance <= self.tolerance]
        return entries[min(near)[1]] if near else None

    # --- changes

    @staticmethod
    def _state(entry, recording, detected):
        """What an entry's mite is in `recording`, one of CYCLE."""
        since = entry["gone_from"]
        if since == recording:
            return GONE_FROM
        if recording in entry["gone"] or (since is not None and recording > since):
            return GONE
        return MOVING if entry["moving"].get(str(recording), detected) else STILL

    def change(self, x, y, recording, detected, state=None, checked=False):
        """Make the mite at (x, y) `state` in `recording`: "moving" or "still" (its
        call), "gone" (in this recording) or "gone_from" (from this recording on);
        without `state`, the one after what it is now in CYCLE. `detected` is the
        detector's call there: a call changed back to it is no correction any more.

        A mite gone from an earlier recording on that is given another state here
        is seen again from here on: the recordings in between stay gone, one by one.
        With `checked`, a call ("moving" or "still") is kept as checked by eye,
        also when it is the detector's. Returns the state now."""
        entries = self.entries()
        entry = self._nearest(entries, x, y)
        if entry is None:
            entry = {"x": float(x), "y": float(y), "moving": {}, "gone": [], "gone_from": None, "checked": []}
            entries.append(entry)
        if state is None:
            state = CYCLE[(CYCLE.index(self._state(entry, recording, detected)) + 1) % len(CYCLE)]
        if state not in CYCLE:
            raise ValueError(f"Unknown state {state!r}.")

        gone, since = set(entry["gone"]), entry["gone_from"]
        if since is not None and recording >= since and state != GONE_FROM:
            gone.update(range(since, recording))
            since = None
        if state == GONE_FROM:
            since = recording
            gone = {r for r in gone if r < recording}
        elif state == GONE:
            gone.add(recording)
        else:
            gone.discard(recording)
            if (state == MOVING) == bool(detected):
                entry["moving"].pop(str(recording), None)
            else:
                entry["moving"][str(recording)] = state == MOVING
        entry["gone"], entry["gone_from"] = sorted(gone), since
        if checked and state in (MOVING, STILL):
            entry["checked"] = sorted({*entry["checked"], recording})
        self._write(entries)
        return state

    # --- for the results

    def apply(self, mite_data):
        """The mite score table (ZoneManager.get_mite_scores()) with the corrected
        calls in place of the detector's, and what was changed in it, to add to
        the results (nothing without changes):

            corrections   {mite id: [recording, ...]}: the calls that are the user's
            censored      {mite id: [recording, ...]}: the recordings in which the mite is gone
            gone_from     {mite id: recording}: the mites gone from a recording on
            checked       {mite id: [recording, ...]}: the calls kept as checked by eye

        With corrections the table has a `corrected` column, with mites gone a
        `censored` one, true in those rows; a censored row is not moving."""
        entries = self.entries()
        if not entries or mite_data.empty:
            return mite_data, {}
        data = mite_data.copy()
        times = sorted(data["time"].unique())
        recording = data["time"].map({time: index for index, time in enumerate(times)}).to_numpy()
        ids = data["mite_ID"].to_numpy()
        moving = data["moving"].to_numpy(dtype=bool).copy()
        corrected = np.zeros(len(data), dtype=bool)
        censored = np.zeros(len(data), dtype=bool)
        changes = {"corrections": {}, "censored": {}, "gone_from": {}, "checked": {}}
        for mite in data.drop_duplicates("mite_ID").itertuples():
            entry = self._nearest(entries, mite.x, mite.y)
            if entry is None:
                continue
            mite_id = str(mite.mite_ID)
            since = entry["gone_from"]
            gone = {r for r in entry["gone"] if r < len(times)} | set(range(since, len(times)) if since is not None else ())
            calls = {int(r): bool(call) for r, call in entry["moving"].items() if int(r) not in gone and 0 <= int(r) < len(times)}
            mine = np.flatnonzero(ids == mite.mite_ID)  # the mite's rows, looked for once however many calls it has
            at = recording[mine]
            for index, call in calls.items():
                rows = mine[at == index]
                moving[rows] = call
                corrected[rows] = True
            rows = mine[np.isin(at, sorted(gone))]
            moving[rows] = False
            censored[rows] = True
            if calls:
                changes["corrections"][mite_id] = sorted(calls)
            if gone:
                changes["censored"][mite_id] = sorted(gone)
            if since is not None and since < len(times):
                changes["gone_from"][mite_id] = since
            looked = sorted(r for r in entry["checked"] if r not in gone and 0 <= r < len(times))
            if looked:
                changes["checked"][mite_id] = looked
        changes = {key: value for key, value in changes.items() if value}
        if not changes:
            return mite_data, {}
        data["moving"] = moving
        if "corrections" in changes:
            data["corrected"] = corrected
        if "censored" in changes:
            data["censored"] = censored
        return data, changes
