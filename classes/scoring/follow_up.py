"""The recordings in which a live run did not follow a mite (classes/scoring/motion_analysis.py),
as the results show them.

- Before it was added (its `start`), nothing is known of it: those recordings are
  censored, as if it were gone in them (classes/results/call_corrections.py), and its
  survival counts from its start (classes/results/survival.py).
- Once it counted as dead (`stopped`), it is neither scored nor saved: those
  recordings have no score and count as still, so it stays dead.

A folder's mites are followed in every recording: nothing changes.
"""

import numpy as np


class FollowUp:
    def __init__(self, starts, stops):
        """`starts`: {mite id: the recording it was added in}, for those added
        after the first; `stops`: {mite id: the first recording it was not
        followed in, counted dead}."""
        self.starts = {str(key): int(value) for key, value in starts.items() if value}
        self.stops = {str(key): int(value) for key, value in stops.items()}

    @classmethod
    def of(cls, mites):
        """From the Mites of a run."""
        mites = list(mites)
        return cls({mite.text: mite.start for mite in mites},
                   {mite.text: mite.stopped for mite in mites if mite.stopped is not None})

    def censor(self, mite_data, changes):
        """The mite score table with the recordings before each mite was added
        censored (not moving, counting neither way), and those once it stopped
        being followed still; `changes` (CallCorrections.apply()'s) get the
        censored ones under "censored", and "started" and "stopped" the
        recordings each mite was added in and no longer followed from."""
        if mite_data.empty or not (self.starts or self.stops):
            return mite_data, changes
        times = sorted(mite_data["time"].unique())
        recording = mite_data["time"].map({time: index for index, time in enumerate(times)}).to_numpy()
        ids = mite_data["mite_ID"].astype(str).to_numpy()
        start = np.array([self.starts.get(i, 0) for i in ids])
        stop = np.array([self.stops.get(i, len(times)) for i in ids])
        before = recording < start
        after = recording >= stop
        data = mite_data.copy()
        data["moving"] = data["moving"].to_numpy(dtype=bool) & ~before & ~after
        changes = dict(changes)
        if before.any():
            data["censored"] = (data["censored"].to_numpy(dtype=bool) if "censored" in data else np.zeros(len(data), bool)) | before
            censored = {key: set(value) for key, value in changes.get("censored", {}).items()}
            for k in np.flatnonzero(before):
                censored.setdefault(ids[k], set()).add(int(recording[k]))
            changes["censored"] = {key: sorted(value) for key, value in censored.items()}
        present = set(ids)
        started = {key: value for key, value in self.starts.items() if key in present}
        stopped = {key: value for key, value in self.stops.items() if key in present and value < len(times)}
        if started:
            changes["started"] = started
        if stopped:
            changes["stopped"] = stopped
        return data, changes
