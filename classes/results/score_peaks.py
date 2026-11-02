"""The recordings below the threshold that stand out of the mite's own still
level, to check by eye beside the band's close calls (classes/results/review_band.py).

A weak last movement often scores below the threshold, and below the band too,
but on the mite's scores graph it is a peak: higher than the recordings either
side and well above where the mite's score sits once it is still. Only those
after the mite's last movement can move its death, so only they are asked for.

The still level is the median of the log scores after the last movement (when
there are at least BASELINE_MIN of them; else of all the recordings called still),
its spread 1.4826 times their median absolute deviation. A peak is asked for when
it is SPREADS spreads or more above that level and scores at least FLOOR times the
threshold: on the labelled datasets (2026-11-02, threshold 0.135) these took the
deaths put early from 0.10 to 0.025 recordings per mite for 0.04 checks per mite,
and asked about 16 of the long run's 60 mites (23 recordings). The scores are
the detector's, so a mite whose legs keep its score high when still has a high
still level of its own and is not asked about for it.
"""

import numpy as np
from scipy.signal import find_peaks

SPREADS = 2.0
FLOOR = 0.5
BASELINE_MIN = 5
# the fewest recordings a still level is taken from; with fewer, no peak is asked for
LEVEL_MIN = 3
# scores of 0 are taken as this for the log
TINY = 1e-4


class ScorePeaks:
    def __init__(self, threshold):
        self.threshold = float(threshold)

    def to_check(self, scores, moving, checked=None, censored=None):
        """The recordings of one mite to check by eye for being peaks, the latest
        first. Per recording: its `scores`, its calls (`moving`, the corrections
        by hand in them), whether the user set the call (`checked`) and whether
        the mite is gone (`censored`)."""
        scores = np.asarray(scores, dtype=float)
        moving = np.asarray(moving, dtype=bool)
        checked = np.zeros(len(scores), dtype=bool) if checked is None else np.asarray(checked, dtype=bool)
        there = np.ones(len(scores), dtype=bool) if censored is None else ~np.asarray(censored, dtype=bool)
        there &= ~np.isnan(scores)
        present = np.flatnonzero(there)
        if not len(present):
            return []
        moved = np.flatnonzero(moving & there)
        last = moved[-1] if len(moved) else -1
        log = np.log(np.maximum(scores[present], TINY))
        after = present > last
        level_of = log[after] if after.sum() >= BASELINE_MIN else log[~moving[present]]
        if len(level_of) < LEVEL_MIN:
            return []
        level = np.median(level_of)
        spread = 1.4826 * np.median(np.abs(level_of - level))
        peaks = present[find_peaks(np.concatenate([[-np.inf], log, [-np.inf]]))[0] - 1]
        high = np.log(np.maximum(scores[peaks], TINY)) - level >= SPREADS * spread
        asked = peaks[high & (peaks > last) & (scores[peaks] >= FLOOR * self.threshold) & ~checked[peaks]]
        return [int(recording) for recording in asked[::-1]]
