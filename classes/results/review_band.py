"""The calls to check by eye: those too close to the threshold to trust, on which
a mite's time of death depends.

A mite dies at the recording after its last movement (classes/results/survival.py), so
one wrong call can move its death by hours: a still recording called moving
long after it, or a weak last movement called still. The scores close to the
threshold are the ones the detector gets wrong. With a band around the
threshold, a score at or above the band is a clear movement, one below it
clearly still, and one inside it is a close call.

The band is not set by hand: the user says how many mites to check by eye, and
the band is the narrowest around the threshold that asks about that many
(fitted()). It keeps the shape of the band in config.yaml
(mite.metric_review_bands, saved from the calibration report): as far below
the threshold against above it as that one; without one, as far either way.

Not every close call matters: only those after the mite's last settled movement
can move its death. A movement is settled when its score is at or above the
band, or when the user set the call by hand (classes/results/call_corrections.py). The
close calls after it are to check, the latest first: once one is seen to be a
movement, the earlier ones no longer matter and are asked for no more.

The detector's call stays what the threshold makes it until the user sets it,
so the band changes no number by itself; it only says where to look.
"""

import numpy as np


class ReviewBand:
    def __init__(self, low, high):
        self.low, self.high = float(low), float(high)

    @classmethod
    def fitted(cls, mite_data, threshold, n_mites, shape=None):
        """The narrowest band around `threshold` that asks about `n_mites` mites of
        the mite score table (as describe() takes it), or as many as it can
        without asking about more; None when it asks about none. Neither edge is
        further from the threshold than the threshold itself: a score of 0 or of
        twice the threshold is no close call. `shape` (low,
        high), a band holding the threshold, says how far below the threshold the
        band reaches against above it; without it, as far either way.

        A mite is asked about while the band has close calls of it that its death
        depends on, whatever was answered since, so answering a call does not
        move the band (a correction of a clear call can)."""
        threshold = float(threshold)
        below, above = 0.5, 0.5
        if shape is not None and shape[0] < shape[1]:
            below, above = threshold - shape[0], shape[1] - threshold
            below, above = below / (below + above), above / (below + above)
        scores, moving, there = cls._table(mite_data)

        def band(scale):
            return threshold - scale * below, threshold + scale * above

        def asked(scale):
            low, high = band(scale)
            n_recordings = scores.shape[1]
            clear = moving & there & (scores >= high)
            last = np.where(clear.any(axis=1), n_recordings - 1 - np.argmax(clear[:, ::-1], axis=1), -1)
            close = there & (scores >= low) & (scores < high)
            return int((close & (np.arange(n_recordings) > last[:, None])).any(axis=1).sum())

        # the scale at which each score comes into the band; between two of them the band asks the same
        present = scores[there]
        with np.errstate(divide="ignore", invalid="ignore"):
            enters = np.where(present < threshold, (threshold - present) / below, (present - threshold) / above)
        # no further from the threshold than the threshold itself: from 0 up to twice it at most
        widest = threshold / max(below, above)
        enters = np.unique(enters[np.isfinite(enters) & (enters <= widest)])
        if n_mites <= 0 or not len(enters):
            return None
        scales = enters * (1 + 1e-9) + 1e-12  # just past each: a score at the upper edge is not in the band

        def first(at_least):  # the first scale asking about at least `at_least` mites; len(scales) with none
            lo, hi = 0, len(scales)
            while lo < hi:
                mid = (lo + hi) // 2
                if asked(scales[mid]) >= at_least:
                    hi = mid
                else:
                    lo = mid + 1
            return lo

        enough = first(n_mites + 1) - 1  # the widest asking about no more than n_mites
        if enough < 0 or not asked(scales[enough]):
            return None
        return cls(*band(scales[first(asked(scales[enough]))]))

    @staticmethod
    def _table(mite_data):
        """The mite score table as (mites, recordings) arrays: the scores (NaN
        where a mite has none), the calls, and whether the mite is there."""
        mites, row = np.unique(mite_data["mite_ID"].astype(str).to_numpy(), return_inverse=True)
        times, column = np.unique(mite_data["time"].to_numpy(), return_inverse=True)
        scores = np.full((len(mites), len(times)), np.nan)
        moving = np.zeros(scores.shape, dtype=bool)
        there = np.zeros(scores.shape, dtype=bool)
        scores[row, column] = mite_data["motion_score"].to_numpy(dtype=float)
        moving[row, column] = mite_data["moving"].to_numpy(dtype=bool)
        there[row, column] = ~mite_data["censored"].to_numpy(dtype=bool) if "censored" in mite_data else True
        return scores, moving, there & ~np.isnan(scores)

    def to_check(self, scores, moving, checked=None, censored=None):
        """The recordings of one mite to check by eye, the latest first. Per
        recording: its `scores`, its calls (`moving`), whether the user set the
        call (`checked`) and whether the mite is gone (`censored`)."""
        scores = np.asarray(scores, dtype=float)
        moving = np.asarray(moving, dtype=bool)
        checked = np.zeros(len(scores), dtype=bool) if checked is None else np.asarray(checked, dtype=bool)
        there = np.ones(len(scores), dtype=bool) if censored is None else ~np.asarray(censored, dtype=bool)
        settled = np.flatnonzero(moving & there & ((scores >= self.high) | checked))
        last = settled[-1] if len(settled) else -1
        close = (scores >= self.low) & (scores < self.high) & there & ~checked
        return [int(recording) for recording in np.flatnonzero(close)[::-1] if recording > last]

    def describe(self, mite_data, changes=None):
        """For the result pages, from the mite score table (the calls corrected by
        hand in it) and what the corrections changed (CallCorrections.apply()):

            {low, high, to_check: {mite id: [recording, ...] the latest first},
             n_recordings, n_mites, n_asked, n_done}

        n_asked is how many mites the band asks about at all, with nothing set
        by hand yet, and n_done how many of them have nothing left to check: how
        far the checking has got.
        """
        changes = changes or {}
        to_check = {}
        n_asked = 0
        for mite_id, rows in mite_data.groupby("mite_ID"):
            times = rows["time"].to_numpy()
            if not (times[1:] > times[:-1]).all():  # in the order of their times already, most often
                rows = rows.sort_values("time")
            set_by_hand = set(changes.get("corrections", {}).get(str(mite_id), [])) | set(
                changes.get("checked", {}).get(str(mite_id), []))
            censored = rows["censored"] if "censored" in rows else None
            recordings = self.to_check(
                rows["motion_score"], rows["moving"],
                checked=[recording in set_by_hand for recording in range(len(rows))], censored=censored)
            if recordings:
                to_check[str(mite_id)] = recordings
            n_asked += bool(recordings or (set_by_hand and self.to_check(rows["motion_score"], rows["moving"],
                                                                         censored=censored)))
        return {"low": self.low, "high": self.high, "to_check": to_check,
                "n_recordings": sum(len(recordings) for recordings in to_check.values()), "n_mites": len(to_check),
                "n_asked": n_asked, "n_done": n_asked - len(to_check)}
