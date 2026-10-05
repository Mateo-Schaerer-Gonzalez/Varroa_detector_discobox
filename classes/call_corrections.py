"""The detector's calls the user corrected by hand on the result pages.

The detector calls a mite moving in a recording when its score there reaches the
threshold. Where the user sees it got one wrong, a click on the mite changes that
one call, and every number of the results follows: the correction replaces the
detector's call in the mite score table, before anything is worked out from it.

The corrections are kept next to the recordings, in corrections.json, so they
survive a restart and another run. Like the ground truth they go by the mite's
position, not its id, so they still apply after a change of detector settings
renumbers the mites. They are kept per pool size, as a recording's index means
another stretch of frames with another one:

    {"recording": [{"x": 412.5, "y": 230.0, "moving": {"3": true}}], "30": [...]}
"""

import json
from pathlib import Path

import numpy as np


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
        """The corrections of this pool size: [{x, y, moving: {recording: call}}]."""
        entries = self._read().get(self.key, [])
        return [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("moving"), dict)
                and "x" in entry and "y" in entry] if isinstance(entries, list) else []

    def _write(self, entries):
        saved = self._read()
        saved[self.key] = [entry for entry in entries if entry["moving"]]
        if not saved[self.key]:
            del saved[self.key]
        self.path.write_text(json.dumps(saved), encoding="utf-8")

    def _nearest(self, entries, x, y):
        """The entry of the mite at (x, y): the nearest within the tolerance, or None."""
        near = [(np.hypot(entry["x"] - x, entry["y"] - y), index) for index, entry in enumerate(entries)]
        near = [(distance, index) for distance, index in near if distance <= self.tolerance]
        return entries[min(near)[1]] if near else None

    # --- changes

    def toggle(self, x, y, recording, detected):
        """Change the call of the mite at (x, y) in `recording` to the other one:
        moving to still, still to moving. `detected` is the detector's call there;
        a change back to it takes the correction away. Returns the call now."""
        entries = self.entries()
        entry = self._nearest(entries, x, y)
        if entry is None:
            entry = {"x": float(x), "y": float(y), "moving": {}}
            entries.append(entry)
        shown = bool(entry["moving"].get(str(recording), detected))
        if shown == bool(detected):
            entry["moving"][str(recording)] = not shown
        else:
            entry["moving"].pop(str(recording), None)
        self._write(entries)
        return not shown

    # --- for the results

    def apply(self, mite_data):
        """The mite score table (ZoneManager.get_mite_scores()) with the corrected
        calls in place of the detector's, and the corrections that apply to it:
        {mite id: [recording, ...]}. With any, the table has a `corrected` column
        too, true in the rows whose call is the user's."""
        entries = self.entries()
        if not entries or mite_data.empty:
            return mite_data, {}
        data = mite_data.copy()
        times = sorted(data["time"].unique())
        recording = data["time"].map({time: index for index, time in enumerate(times)})
        corrected = np.zeros(len(data), dtype=bool)
        moving = data["moving"].to_numpy(dtype=bool).copy()
        corrections = {}
        for mite in data.drop_duplicates("mite_ID").itertuples():
            entry = self._nearest(entries, mite.x, mite.y)
            if entry is None:
                continue
            for index, call in entry["moving"].items():
                rows = ((data["mite_ID"] == mite.mite_ID) & (recording == int(index))).to_numpy()
                if rows.any():
                    moving[rows] = bool(call)
                    corrected[rows] = True
                    corrections.setdefault(str(mite.mite_ID), []).append(int(index))
        if not corrections:
            return mite_data, {}
        data["moving"] = moving
        data["corrected"] = corrected
        return data, {mite_id: sorted(indices) for mite_id, indices in corrections.items()}
