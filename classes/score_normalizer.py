"""Puts the motion scores of a finished run on one scale for every mite.

A still mite does not score 0: the camera's noise gives it a floor, and that
floor differs from mite to mite, mostly with how bright its patch is. One
threshold for all then sits inside the noise of the mites with a high floor,
which get called moving while still. Both corrections here are worked out from
the whole run, so they are for a finished one (the Analysis window), and both
keep the scores on about the scale they had. Which of them a folder's analysis
uses is in config.yaml (mite.normalize_brightness, mite.normalize_floor), saved
there with the threshold from the calibration report, which puts each dataset's
scores through the same.

    brightness   each score is scaled to the run's typical brightness: times the
                 median brightness of all patches, over the brightness of its
                 own. Camera noise grows with the light, and the variance of a
                 still patch in proportion to it (measured on the labelled
                 recordings with the variability scores: brightness to the
                 power 0.96); other kinds of score were not checked.

    floor        each mite's floor, the median of its scores over the run, is
                 moved to the median floor of all mites: its own is subtracted
                 and the common one added. The median is the floor only of a
                 mite still in most recordings; one moving in more than half of
                 them gets too high a floor, and its weaker movements are lost.

Brightness comes first, so the floors are those left after it. The recordings in
which a mite was marked gone (classes/call_corrections.py) count in neither.
"""

import numpy as np
import pandas as pd


class ScoreNormalizer:
    def __init__(self, floor=False, brightness=False):
        self.floor = bool(floor)
        self.brightness = bool(brightness)

    @property
    def active(self):
        return self.floor or self.brightness

    def describe(self):
        return {"floor": self.floor, "brightness": self.brightness}

    def scores(self, mite_data):
        """The normalised score of every row of the mite score table
        (ZoneManager.get_mite_scores(), with the corrections applied or not)."""
        scores = mite_data["motion_score"].astype(float)
        seen = ~mite_data["censored"].astype(bool) if "censored" in mite_data else np.ones(len(mite_data), dtype=bool)
        if self.brightness:
            brightness = mite_data["brightness"].astype(float)
            measured = brightness > 0  # False where it is missing
            if (measured & seen).any():
                typical = brightness[measured & seen].median()
                scores = scores.where(~measured, scores * typical / brightness)
        if self.floor:
            floors = scores[seen].groupby(mite_data["mite_ID"][seen]).median()
            if len(floors):
                common = floors.median()
                # a mite gone in every recording has no floor: its scores stay
                scores = scores - mite_data["mite_ID"].map(floors).fillna(common) + common
        return scores

    def by_mite(self, scores, brightness=None):
        """The normalised scores of mites given as {mite id: one score per
        recording}, with their `brightness` the same way: a calibration's
        datasets, put through what a folder's analysis puts its table through."""
        rows = [{"mite_ID": mite_id, "time": recording, "motion_score": value,
                 "brightness": None if brightness is None else brightness[mite_id][recording]}
                for mite_id, values in scores.items() for recording, value in enumerate(values)]
        if not rows:
            return {}
        table = pd.DataFrame(rows)
        table["motion_score"] = self.scores(table)
        return {mite_id: [float(value) for value in table.loc[table["mite_ID"] == mite_id, "motion_score"]]
                for mite_id in scores}

    def apply(self, mite_data, threshold):
        """The table with the normalised scores as `motion_score`, the scores as
        they were as `raw_score`, and `moving` following the normalised ones:
        at or above `threshold`, except where the call is the user's or the mite
        is gone. The table itself when nothing is switched on."""
        if not self.active or mite_data.empty:
            return mite_data
        data = mite_data.copy()
        data["raw_score"] = data["motion_score"]
        data["motion_score"] = self.scores(mite_data)
        users = np.zeros(len(data), dtype=bool)
        for column in ("corrected", "censored"):
            if column in data:
                users |= data[column].to_numpy(dtype=bool)
        data["moving"] = np.where(users, data["moving"].to_numpy(dtype=bool), self.calls(data, threshold))
        return data

    @staticmethod
    def calls(data, threshold):
        """The detector's call in every row of a normalised table."""
        return data["motion_score"].to_numpy(dtype=float) >= threshold
