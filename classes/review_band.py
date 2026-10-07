"""The calls to check by eye: those too close to the threshold to trust, on which
a mite's time of death depends.

A mite dies at the recording after its last movement (classes/survival.py), so
one wrong call can move its death by hours: a still recording called moving
long after it, or a weak last movement called still. The scores close to the
threshold are the ones the detector gets wrong. With a band around the
threshold (config.yaml: mite.metric_review_bands), a score at or above the band
is a clear movement, one below it clearly still, and one inside it is a close
call.

Not every close call matters: only those after the mite's last settled movement
can move its death. A movement is settled when its score is at or above the
band, or when the user set the call by hand (classes/call_corrections.py). The
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
    def of(cls, mite_config, metric=None):
        """The band config.yaml has for `metric` (by default the one in use), or
        None without one."""
        band = mite_config.review_band_for(metric or mite_config.metric)
        return cls(*band) if band else None

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
             n_recordings, n_mites}
        """
        changes = changes or {}
        to_check = {}
        for mite_id, rows in mite_data.groupby("mite_ID"):
            rows = rows.sort_values("time")
            set_by_hand = set(changes.get("corrections", {}).get(str(mite_id), [])) | set(
                changes.get("checked", {}).get(str(mite_id), []))
            recordings = self.to_check(
                rows["motion_score"], rows["moving"],
                checked=[recording in set_by_hand for recording in range(len(rows))],
                censored=rows["censored"] if "censored" in rows else None)
            if recordings:
                to_check[str(mite_id)] = recordings
        return {"low": self.low, "high": self.high, "to_check": to_check,
                "n_recordings": sum(len(recordings) for recordings in to_check.values()), "n_mites": len(to_check)}
