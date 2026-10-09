"""Where the scores of the recordings labelled moving and of those labelled still
overlap: the mite-recordings to look at again when checking the ground truth.

TEMPORARY, for the page web/static/overlap.html (see pipeline.truth_overlap()).

A score separates the two labels except in a stretch of scores where both occur.
A label there is either a movement too small for the score, or a mistake, and
only the eye can tell which. The stretch is found from the labels themselves
(suggested_band()), and the page may set another one.

Beyond it lie the recordings on the wrong side altogether: labelled moving and
scoring below it, among the still ones, or labelled still and scoring above it.
They are the least likely to be right, so they are listed with the rest unless
the page asks for the stretch alone.
"""

import math

import numpy as np

from classes.calibration import MOVING

IN, BELOW, ABOVE = "in", "below", "above"


class TruthOverlap:
    NEIGHBOURS = 40       # the recordings scoring closest to one, half of them below it and half above
    SHARE = 0.1           # of them, the share each label needs for the two to overlap there
    LOWEST = 0.01         # the histogram's first edge; lower scores are in its first bin
    BINS_PER_DECADE = 8

    def __init__(self, rows):
        """`rows`: one per mite-recording labelled moving or still, each with its
        "score" and its "movement" (pipeline._observations())."""
        self.rows = sorted(rows, key=lambda row: row["score"])
        self.scores = np.array([row["score"] for row in self.rows], dtype=float)
        self.moving = np.array([row["movement"] == MOVING for row in self.rows], dtype=bool)

    def suggested_band(self):
        """(low, high): the scores between which the two labels clearly overlap,
        or None when they do not.

        A recording is in the overlap when both labels are common among the
        NEIGHBOURS recordings scoring closest to it: each has at least SHARE
        of them. The band runs from the lowest such recording labelled moving
        to the highest labelled still. A stray label far inside the other's
        scores has no such neighbours, so it does not stretch the band."""
        n = len(self.scores)
        half = self.NEIGHBOURS // 2
        needed = max(1, math.ceil(self.SHARE * min(self.NEIGHBOURS, n)))
        moving_before = np.concatenate([[0], np.cumsum(self.moving)])
        first = np.maximum(np.arange(n) - half, 0)
        end = np.minimum(np.arange(n) + half, n)
        n_moving = moving_before[end] - moving_before[first]
        mixed = (n_moving >= needed) & (end - first - n_moving >= needed)
        lowest = np.flatnonzero(mixed & self.moving)
        highest = np.flatnonzero(mixed & ~self.moving)
        if not len(lowest) or not len(highest):
            return None
        low, high = float(self.scores[lowest[0]]), float(self.scores[highest[-1]])
        return (low, high) if low < high else None

    def histogram(self):
        """How many recordings of each label have each score, in bins as wide
        on a logarithmic axis: {edges, moving, still}. Scores under the first
        edge are counted in the first bin."""
        top = max(float(self.scores.max()) if len(self.scores) else 0.0, self.LOWEST * 10)
        n_bins = math.ceil(math.log10(top / self.LOWEST) * self.BINS_PER_DECADE - 1e-9)
        edges = self.LOWEST * 10 ** (np.arange(n_bins + 1) / self.BINS_PER_DECADE)
        edges[-1] = max(edges[-1], top)  # the highest score is in the last bin, whatever the rounding
        clipped = np.clip(self.scores, edges[0], edges[-1])
        return {
            "edges": [round(float(edge), 5) for edge in edges],
            "moving": np.histogram(clipped[self.moving], edges)[0].tolist(),
            "still": np.histogram(clipped[~self.moving], edges)[0].tolist(),
        }

    def where(self, low, high):
        """Per row, in the order of `rows`: IN the band, BELOW it and labelled
        moving, ABOVE it and labelled still, or None: nothing to check."""
        inside = (self.scores >= low) & (self.scores <= high)
        below = self.moving & (self.scores < low)
        above = ~self.moving & (self.scores > high)
        return [IN if i else BELOW if b else ABOVE if a else None for i, b, a in zip(inside, below, above)]

    def describe(self, low=None, high=None, beyond=True):
        """What the page shows:

            suggested    {low, high} of suggested_band(), or None
            band         {low, high} in use: `low` and `high`, each the suggested
                         one when not given; None without either
            histogram    histogram()
            counts       moving, still: the recordings of each label in the band;
                         moving_below, still_above: those beyond it on the wrong
                         side; n_moving, n_still: every recording of each label
            datapoints   the rows to check, each with "where" (see where()):
                         those in the band and, with `beyond`, those beyond it
        """
        suggested = self.suggested_band()
        if low is None and suggested:
            low = suggested[0]
        if high is None and suggested:
            high = suggested[1]
        counts = {"n_moving": int(self.moving.sum()), "n_still": int((~self.moving).sum()),
                  "moving": 0, "still": 0, "moving_below": 0, "still_above": 0}
        datapoints = []
        band = None
        if low is not None and high is not None:
            low, high = float(low), float(high)
            if not low <= high:
                raise ValueError("The overlap must start at a lower score than it ends at.")
            band = {"low": low, "high": high}
            for row, where, moving in zip(self.rows, self.where(low, high), self.moving):
                if where is None:
                    continue
                key = ("moving" if moving else "still") if where == IN else "moving_below" if where == BELOW else "still_above"
                counts[key] += 1
                if where == IN or beyond:
                    datapoints.append({**row, "where": where})
        return {
            "suggested": None if suggested is None else {"low": suggested[0], "high": suggested[1]},
            "band": band,
            "histogram": self.histogram(),
            "counts": counts,
            "datapoints": datapoints,
        }
