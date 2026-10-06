"""The threshold a mite's motion scores are compared with, and the search for it.

A mite under a noisier light scores higher when it is still, so one threshold
for every mite is too low for some and too high for others. With a window, each
mite gets its own: the moving median of its scores over `window` recordings
(what it scores when nothing happens, as long as it is still in most of them)
plus an offset. Without one (window 0) the offset is the threshold itself, the
same for every mite.

ThresholdSearch tries the windows against the saved ground truth, for the
calibration report.
"""

import random

import numpy as np

from classes import calibration


class MiteThreshold:
    def __init__(self, offset, window=0, centred=True):
        self.offset = float(offset)
        self.window = int(window or 0)
        self.centred = bool(centred)

    @classmethod
    def from_config(cls, mite_config):
        """The threshold of the metric in use in config.yaml."""
        window, centred = mite_config.window_for(mite_config.metric)
        return cls(mite_config.motion_threshold, window, centred)

    def describe(self):
        return {"offset": self.offset, "window": self.window, "centred": self.centred}

    def baselines(self, scores):
        """Per recording, what the offset is added to: the moving median of the
        mite's scores, or 0 without a window."""
        if not self.window:
            return np.zeros(len(scores))
        return calibration.moving_median(scores, self.window, self.centred)

    def thresholds(self, scores):
        """The mite's threshold in each recording, given all its scores in order."""
        return [float(value) for value in self.baselines(scores) + self.offset]

    def moving(self, scores):
        """Per recording: does the mite's score reach its threshold there?"""
        return [bool(score >= threshold) for score, threshold in zip(scores, self.thresholds(scores))]


class ThresholdSearch:
    """Finds the window and offset that best give the labels.

    `series` maps each mite to all its scores, in recording order; every
    `observations` entry is (mite, recording, labelled moving). A mite's median
    is taken over all its recordings, labelled or not, as an analysis would."""

    MAX_WINDOWS = 12      # window sizes tried, spread from 2 to the longest series
    SHARES = [(0.0, "never"), (0.25, "up to 25%"), (0.5, "up to 50%"), (0.75, "up to 75%"), (1.0, "up to 100%")]

    def __init__(self, series, observations):
        self.series = {mite: np.asarray(scores, dtype=float) for mite, scores in series.items()}
        self.mites = [mite for mite, _recording, _moving in observations]
        self.recordings = np.array([recording for _mite, recording, _moving in observations], dtype=int)
        self.is_moving = np.array([moving for _mite, _recording, moving in observations], dtype=bool)
        self.scores = np.array([self.series[mite][recording] for mite, recording, _moving in observations])
        self._margins = {}

    def windows(self):
        longest = max(len(scores) for scores in self.series.values())
        return sorted({int(window) for window in np.linspace(2, max(2, longest), self.MAX_WINDOWS).round()})

    def choices(self):
        """Every (window, centred) tried; (0, True) is one threshold for all."""
        return [(0, True)] + [(window, centred) for window in self.windows() for centred in (True, False)]

    def above(self, window, centred):
        """Each observation's score above its mite's moving median (above 0
        without a window): what the offset is compared with."""
        key = (window, centred)
        if key not in self._margins:
            threshold = MiteThreshold(0, window, centred)
            baselines = {mite: threshold.baselines(scores) for mite, scores in self.series.items()}
            self._margins[key] = self.scores - np.array(
                [baselines[mite][recording] for mite, recording in zip(self.mites, self.recordings)])
        return self._margins[key]

    def calls(self, threshold):
        """Per observation: called moving by a MiteThreshold?"""
        return self.above(threshold.window, threshold.centred) >= threshold.offset

    def confusion(self, threshold, subset=None):
        subset = slice(None) if subset is None else subset
        return calibration.calls_confusion(self.calls(threshold)[subset], self.is_moving[subset])

    @staticmethod
    def balance(confusion):
        """Mean of moving called moving and still called still: what a fit maximises."""
        return (confusion["sensitivity"] + confusion["specificity"]) / 2

    def fit(self, window, centred, subset=None):
        """The MiteThreshold with the offset best for this window on the
        observations of `subset` (all of them when None), as
        calibration.best_threshold() chooses it."""
        subset = slice(None) if subset is None else subset
        offset = calibration.best_threshold(self.above(window, centred)[subset], self.is_moving[subset])
        return MiteThreshold(offset, window, centred)

    def best(self, subset=None, own_only=True):
        """The best fit of all windows; with `own_only`, one threshold for every
        mite is not among them. The first of equally good ones wins: the
        shortest window, centred before trailing."""
        fits = [self.fit(window, centred, subset) for window, centred in self.choices() if window or not own_only]
        return max(fits, key=lambda fit: round(self.balance(self.confusion(fit, subset)), 12))

    def table(self):
        """Every choice with its best offset and how well it then calls all the
        observations, the single threshold first."""
        rows = []
        for window, centred in self.choices():
            fit = self.fit(window, centred)
            confusion = self.confusion(fit)
            rows.append({**fit.describe(), "balance": self.balance(confusion),
                         **{key: confusion[key] for key in ("accuracy", "sensitivity", "specificity", "f1",
                                                            "moving_called_still", "still_called_moving")}})
        return rows

    def roc(self, window, centred):
        """The ROC curve over every offset of one window: (fpr, tpr, offsets)."""
        return calibration.roc_curve(self.above(window, centred), self.is_moving)

    def auc(self, window, centred):
        return calibration.auc(self.above(window, centred), self.is_moving)

    def held_out(self, repeats=20, seed=0):
        """How well a window and offset chosen on half of the mites call the
        other half, against a single threshold chosen the same way: the mean
        accuracy over `repeats` random halves. Choosing on all the labels and
        judging on the same ones looks better than it will be. Split by mite,
        so one mite's recordings never sit on both sides. None when no split
        has both labels on the half chosen on."""
        keys = sorted(self.series, key=str)
        own, single = [], []
        for repeat in range(repeats):
            shuffled = list(keys)
            random.Random(seed + repeat).shuffle(shuffled)
            half = set(shuffled[::2])
            train = np.array([mite in half for mite in self.mites])
            if not calibration.has_both_classes(self.is_moving[train]) or train.all():
                continue
            own.append(self.confusion(self.best(train), ~train)["accuracy"])
            single.append(self.confusion(self.fit(0, True, train), ~train)["accuracy"])
        if not own:
            return None
        return {"repeats": len(own), "own": float(np.mean(own)), "single": float(np.mean(single))}

    def by_share_moving(self, threshold):
        """The wrong calls of a MiteThreshold by the share of its labelled
        recordings the mite moved in. A mite's median is its noise only while
        the mite is still in most of the window, so the errors of a mite's own
        threshold gather on the mites that move most."""
        wrong = self.calls(threshold) != self.is_moving
        by_mite = {}
        for index, mite in enumerate(self.mites):
            by_mite.setdefault(mite, []).append(index)
        rows = [{"share": label, "n_mites": 0, "n": 0, "n_wrong": 0} for _limit, label in self.SHARES]
        for indices in by_mite.values():
            share = self.is_moving[indices].mean()
            row = next(row for (limit, _label), row in zip(self.SHARES, rows) if share <= limit)
            row["n_mites"] += 1
            row["n"] += len(indices)
            row["n_wrong"] += int(wrong[indices].sum())
        return rows
