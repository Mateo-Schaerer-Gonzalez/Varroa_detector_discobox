"""The threshold a mite's motion scores are compared with, and the search for it.

A mite under a noisier light scores higher when it is still, so one threshold
for every mite is too low for some and too high for others. With a window, each
mite gets its own: the moving median of its scores over `window` recordings
(what it scores when nothing happens, as long as it is still in most of them)
plus an offset. With a scale, the threshold also rises with the mite's noise:
by `scale` times the median absolute deviation (MAD) of its scores over the
same window. Without a window (window 0) the offset is the threshold itself,
the same for every mite.

ThresholdSearch tries the windows and scales against the saved ground truth,
for the calibration report. What it minimises is the error in the time each
mite died, which is what a survival curve is made of.
"""

import random

import numpy as np

from classes import calibration


class MiteThreshold:
    def __init__(self, offset, window=0, centred=True, scale=0.0):
        self.offset = float(offset)
        self.window = int(window or 0)
        self.centred = bool(centred)
        # a mite's noise is measured over its window: without one there is none
        self.scale = float(scale or 0) if self.window else 0.0

    @classmethod
    def from_config(cls, mite_config):
        """The threshold of the metric in use in config.yaml."""
        window, centred = mite_config.window_for(mite_config.metric)
        return cls(mite_config.motion_threshold, window, centred, mite_config.scale_for(mite_config.metric))

    def describe(self):
        return {"offset": self.offset, "window": self.window, "centred": self.centred, "scale": self.scale}

    def baselines(self, scores):
        """Per recording, what the offset is added to: the moving median of the
        mite's scores, plus `scale` times their moving MAD; 0 without a window."""
        if not self.window:
            return np.zeros(len(scores))
        baselines = calibration.moving_median(scores, self.window, self.centred)
        if self.scale:
            baselines = baselines + self.scale * calibration.moving_mad(scores, self.window, self.centred)
        return baselines

    def thresholds(self, scores):
        """The mite's threshold in each recording, given all its scores in order."""
        return [float(value) for value in self.baselines(scores) + self.offset]

    def moving(self, scores):
        """Per recording: does the mite's score reach its threshold there?"""
        return [bool(score >= threshold) for score, threshold in zip(scores, self.thresholds(scores))]


class ThresholdSearch:
    """Finds the window, scale and offset whose calls best give the time each
    mite died.

    `series` maps each mite to all its scores, in recording order; every
    `observations` entry is (mite, recording, labelled moving); `times` are the
    recordings' times, in minutes (their numbers when left out). A mite's median
    and MAD are taken over all its recordings, labelled or not, as an analysis
    would.

    A mite's death time, by the labels or by a threshold's calls, is that of the
    survival curves (calibration.mite_survival()): the first labelled recording
    after the last one it moved in. Here every labelled mite has one, so that
    every wrong call can cost something: a mite never moving died at its first
    labelled recording, and one moving in its last died one recording later, the
    earliest it can have. The error of a threshold is the mean distance, over
    the mites, between the two death times (the MAE, in minutes)."""

    MAX_WINDOWS = 12      # window sizes tried, spread from 2 to the longest series
    SCALES = (0, 1, 2, 3, 4, 6, 8)   # MADs above the median tried; 0: the median and the offset alone
    SHARES = [(0.0, "never"), (0.25, "up to 25%"), (0.5, "up to 50%"), (0.75, "up to 75%"), (1.0, "up to 100%")]

    def __init__(self, series, observations, times=None):
        self.series = {mite: np.asarray(scores, dtype=float) for mite, scores in series.items()}
        self.mites = [mite for mite, _recording, _moving in observations]
        self.recordings = np.array([recording for _mite, recording, _moving in observations], dtype=int)
        self.is_moving = np.array([moving for _mite, _recording, moving in observations], dtype=bool)
        self.scores = np.array([self.series[mite][recording] for mite, recording, _moving in observations])

        longest = max(len(scores) for scores in self.series.values())
        self.times = np.arange(longest, dtype=float) if times is None else np.asarray(times, dtype=float)
        # the time of the recording after each one; after the last, as far on as the last was from the one before
        step = self.times[-1] - self.times[-2] if len(self.times) > 1 else 1.0
        self.after = np.append(self.times[1:], self.times[-1] + step)

        # each labelled mite's observations, in recording order
        by_mite = {}
        for index, mite in enumerate(self.mites):
            by_mite.setdefault(mite, []).append(index)
        self.by_mite = {mite: np.array(sorted(indices, key=lambda index: self.recordings[index]))
                        for mite, indices in by_mite.items()}
        self.truth_death = self.death_times(self.is_moving)
        self._spread = {}
        self._steps_of = {}

    # --- the choices and how each calls the observations

    def windows(self):
        longest = max(len(scores) for scores in self.series.values())
        return sorted({int(window) for window in np.linspace(2, max(2, longest), self.MAX_WINDOWS).round()})

    def choices(self):
        """Every (window, centred, scale) tried, the simplest first; (0, True, 0)
        is one threshold for all."""
        return [(0, True, 0)] + [(window, centred, scale) for window in self.windows()
                                 for centred in (True, False) for scale in self.SCALES]

    def above(self, window, centred, scale=0):
        """Each observation's score above its mite's moving median plus `scale`
        MADs (above 0 without a window): what the offset is compared with."""
        if not window:
            return self.scores
        key = (window, centred)
        if key not in self._spread:
            medians = {mite: calibration.moving_median(scores, window, centred) for mite, scores in self.series.items()}
            mads = {mite: calibration.moving_mad(scores, window, centred) for mite, scores in self.series.items()}
            self._spread[key] = tuple(
                np.array([values[mite][recording] for mite, recording in zip(self.mites, self.recordings)])
                for values in (medians, mads))
        median, mad = self._spread[key]
        return self.scores - median - scale * mad

    def calls(self, threshold):
        """Per observation: called moving by a MiteThreshold?"""
        return self.above(threshold.window, threshold.centred, threshold.scale) >= threshold.offset

    def confusion(self, threshold, subset=None):
        subset = slice(None) if subset is None else subset
        return calibration.calls_confusion(self.calls(threshold)[subset], self.is_moving[subset])

    @staticmethod
    def balance(confusion):
        """Mean of moving called moving and still called still: what decides
        between thresholds with the same death-time error."""
        return ((confusion["sensitivity"] or 0) + (confusion["specificity"] or 0)) / 2

    # --- the death time of each mite

    def death_times(self, calls):
        """Each labelled mite's death time, in minutes, when `calls` (one per
        observation, True: moving) say where it moved; in the order of by_mite."""
        calls = np.asarray(calls, dtype=bool)
        return np.array([self._deaths(indices)[self._last_moving(calls[indices])] for indices in self.by_mite.values()])

    @staticmethod
    def _last_moving(moving):
        """The last of a mite's labelled recordings it moved in; -1 when in none."""
        moved = np.flatnonzero(moving)
        return int(moved[-1]) if moved.size else -1

    def _deaths(self, indices):
        """A mite's death time by the last of its labelled recordings it moved
        in: the time of the next one, or of the recording after the last. The
        last entry is for a mite that never moved: its first labelled recording."""
        recordings = self.recordings[indices]
        return np.concatenate([self.times[recordings[1:]], [self.after[recordings[-1]]], [self.times[recordings[0]]]])

    def _mites_in(self, subset):
        """Per labelled mite: are its observations in `subset` (a mask of the
        observations that never splits a mite)?"""
        if subset is None:
            return np.ones(len(self.by_mite), dtype=bool)
        return np.array([bool(subset[indices[0]]) for indices in self.by_mite.values()])

    def death_error(self, calls, subset=None):
        """How far the death times by `calls` are from those by the labels, over
        the mites of `subset`: the mean distance ("mae") and the mean difference
        ("bias", positive when the calls have the mites die later), in minutes,
        and how many of the "n_mites" get exactly the labels' time ("n_exact")."""
        errors = (self.death_times(calls) - self.truth_death)[self._mites_in(subset)]
        return {"mae": float(np.abs(errors).mean()), "bias": float(errors.mean()),
                "n_mites": int(errors.size), "n_exact": int((errors == 0).sum())}

    def mae(self, threshold, subset=None):
        """The death-time error of a MiteThreshold: what a fit minimises."""
        return self.death_error(self.calls(threshold), subset)["mae"]

    # --- the fit

    def _steps(self, window, centred, scale):
        """How the mites' death-time errors change as the offset rises, for one
        choice. A mite's death time only depends on the last recording still
        called moving, and that only changes when the offset passes a score
        higher than all the mite's later ones. Returns (start, at, change, mite):
        each mite's error with every recording called moving, and for every such
        score, in rising order, the offset it stops being called at (the score's
        margin, see above()), by how much the error of its mite changes then,
        and which mite that is."""
        key = (window, centred, scale)
        if key not in self._steps_of:
            margins = self.above(window, centred, scale)
            start, at, change, owner = [], [], [], []
            for number, indices in enumerate(self.by_mite.values()):
                margin = margins[indices]
                errors = np.abs(self._deaths(indices) - self.truth_death[number])
                later = np.append(np.maximum.accumulate(margin[::-1])[::-1][1:], -np.inf)
                last = np.flatnonzero(margin > later)[::-1]  # from the last recording back: rising margins
                then = np.append(last[1:], len(margin))      # the last one called moving once this one is not
                start.append(errors[last[0]])
                at.append(margin[last])
                change.append(errors[then] - errors[last])
                owner.append(np.full(len(last), number))
            at, change, owner = np.concatenate(at), np.concatenate(change), np.concatenate(owner)
            order = np.argsort(at, kind="stable")
            self._steps_of[key] = np.array(start), at[order], change[order], owner[order]
        return self._steps_of[key]

    def mae_curve(self, window, centred, scale=0, subset=None):
        """The death-time error at every offset that gives different calls:
        (offsets, maes), the offsets rising. Any offset between two neighbouring
        scores gives the same calls, so each sits halfway into its gap, as far as
        possible from the observations on either side; the lowest calls every
        observation moving. An offset above every score, calling no mite moving
        in any recording, is not among them."""
        start, at, change, owner = self._steps(window, centred, scale)
        mites = self._mites_in(subset)
        here = mites[owner]
        edges, first = np.unique(at[here], return_index=True)
        passed = np.add.reduceat(change[here], first).cumsum()
        totals = start[mites].sum() + np.concatenate([[0.0], passed[:-1]])
        offsets = np.concatenate([edges[:1], (edges[:-1] + edges[1:]) / 2])
        return offsets, totals / mites.sum()

    def _fitted(self, window, centred, scale, subset=None):
        """(mae, balance, MiteThreshold) of the offset best for one choice on the
        observations of `subset`: the lowest death-time error and, among the
        offsets with it, the best balance of moving called moving and still
        called still."""
        offsets, maes = self.mae_curve(window, centred, scale, subset)
        best = np.flatnonzero(np.isclose(maes, maes.min()))
        subset = slice(None) if subset is None else subset
        margins, moving = self.above(window, centred, scale)[subset], self.is_moving[subset]
        called_moving = np.sort(margins[moving])
        called_still = np.sort(margins[~moving])
        sensitivity = 1 - np.searchsorted(called_moving, offsets[best], side="left") / max(len(called_moving), 1)
        specificity = np.searchsorted(called_still, offsets[best], side="left") / max(len(called_still), 1)
        balances = (sensitivity + specificity) / 2
        pick = int(np.argmax(balances))
        return (float(maes[best[pick]]), float(balances[pick]),
                MiteThreshold(offsets[best[pick]], window, centred, scale))

    def fit(self, window, centred, scale=0, subset=None):
        """The MiteThreshold with the offset best for this window and scale on
        the observations of `subset` (all of them when None)."""
        return self._fitted(window, centred, scale, subset)[2]

    @staticmethod
    def _best_of(fitted):
        """The best of several _fitted(): the lowest death-time error, then the
        best balance; of equally good ones the first, which is the simplest."""
        return min(fitted, key=lambda fit: (round(fit[0], 9), -round(fit[1], 9)))

    def best(self, subset=None, own_only=True, scaled=True):
        """The best fit of all windows and scales; with `own_only`, one threshold
        for every mite is not among them, and without `scaled`, neither are the
        thresholds that rise with the mite's MAD."""
        return self._best_of([self._fitted(*choice, subset) for choice in self.choices()
                              if (choice[0] or not own_only) and (scaled or not choice[2])])[2]

    def table(self):
        """Every choice with its best offset, its death-time error and how it
        then calls all the observations, the single threshold first.
        "best_of_window" marks the best scale of each window."""
        rows = []
        for choice in self.choices():
            mae, balance, fit = self._fitted(*choice)
            confusion = self.confusion(fit)
            rows.append({**fit.describe(), "mae": mae, "balance": balance,
                         **{key: confusion[key] for key in ("accuracy", "sensitivity", "specificity", "f1",
                                                            "moving_called_still", "still_called_moving")}})
        for row in rows:
            same_window = [other for other in rows if (other["window"], other["centred"]) == (row["window"], row["centred"])]
            row["best_of_window"] = row is min(same_window, key=lambda other: (round(other["mae"], 9), -round(other["balance"], 9)))
        return rows

    def roc(self, window, centred, scale=0):
        """The ROC curve over every offset of one choice: (fpr, tpr, offsets)."""
        return calibration.roc_curve(self.above(window, centred, scale), self.is_moving)

    def auc(self, window, centred, scale=0):
        return calibration.auc(self.above(window, centred, scale), self.is_moving)

    def held_out(self, repeats=20, seed=0):
        """The death-time error, in minutes, of thresholds chosen on half of the
        mites, on the other half: the mean over `repeats` random halves, for one
        threshold for every mite ("single"), the mite's median plus an offset
        ("own") and the median plus MADs plus an offset ("scaled"), each with
        its best window, scale and offset on the half chosen on. Choosing on all
        the labels and judging on the same ones looks better than it will be.
        Split by mite, so one mite's recordings never sit on both sides. None
        with fewer than two mites."""
        keys = sorted(self.series, key=str)
        kinds = {
            "single": lambda window, _centred, _scale: not window,
            "own": lambda window, _centred, scale: window and not scale,
            "scaled": lambda window, _centred, scale: window and scale,
        }
        errors = {kind: [] for kind in kinds}
        for repeat in range(repeats):
            shuffled = list(keys)
            random.Random(seed + repeat).shuffle(shuffled)
            half = set(shuffled[::2])
            train = np.array([mite in half for mite in self.mites])
            if train.all() or not train.any():
                continue
            fitted = {choice: self._fitted(*choice, train) for choice in self.choices()}
            for kind, belongs in kinds.items():
                chosen = self._best_of([fit for choice, fit in fitted.items() if belongs(*choice)])[2]
                errors[kind].append(self.mae(chosen, ~train))
        if not errors["single"]:
            return None
        return {"repeats": len(errors["single"]), **{kind: float(np.mean(values)) for kind, values in errors.items()}}

    def by_share_moving(self, threshold):
        """The wrong calls of a MiteThreshold by the share of its labelled
        recordings the mite moved in. A mite's median is its noise only while
        the mite is still in most of the window, so the errors of a mite's own
        threshold gather on the mites that move most."""
        wrong = self.calls(threshold) != self.is_moving
        rows = [{"share": label, "n_mites": 0, "n": 0, "n_wrong": 0} for _limit, label in self.SHARES]
        for indices in self.by_mite.values():
            share = self.is_moving[indices].mean()
            row = next(row for (limit, _label), row in zip(self.SHARES, rows) if share <= limit)
            row["n_mites"] += 1
            row["n"] += len(indices)
            row["n_wrong"] += int(wrong[indices].sum())
        return rows
