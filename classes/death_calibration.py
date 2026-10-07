"""The movement threshold, and a band around it to check by eye, chosen by where
they put each mite's death.

A mite dies at the recording after its last movement (classes/survival.py), so
in a long run one still recording called moving, hours after the death, moves
the death there. The threshold that best tells moving from still recording by
recording (calibration.best_threshold()) allows a few of those in a hundred and
so puts many deaths late; the one here, which the calibration report suggests,
is the one with the smallest mean distance, in recordings, between the death by
the detector and the death by the labels.

The scores close to the threshold are the ones it gets wrong. With a band
around it, a score at or above the band is moving, one below it still, and one
inside it is checked by eye. Only the checks that can move a death are counted:
those after the mite's last score above the band, from the last one back to the
first that shows the mite moving.

A LabelledRun holds one dataset: scores, labels and which of them are labelled,
each as (mites, recordings). The functions take a list of them, as the mites of
several datasets are pooled.
"""

from dataclasses import dataclass

import numpy as np

# Thresholds tried at a time: (thresholds, mites, recordings) calls are held at once.
_CHUNK = 256


@dataclass
class LabelledRun:
    scores: np.ndarray    # (mites, recordings)
    moving: np.ndarray    # by the labels; False where not labelled
    labelled: np.ndarray  # labelled moving or still

    def __post_init__(self):
        self.scores = np.asarray(self.scores, dtype=float)
        self.labelled = np.asarray(self.labelled, dtype=bool)
        self.moving = np.asarray(self.moving, dtype=bool) & self.labelled

    @property
    def n_mites(self):
        return len(self.scores)

    def of_mites(self, mites):
        """The run of some of its mites (`mites`: a mask or indices)."""
        return LabelledRun(self.scores[mites], self.moving[mites], self.labelled[mites])

    def with_scores(self, scores):
        return LabelledRun(scores, self.moving, self.labelled)

    def deaths(self, calls):
        """Per mite, where it dies by `calls` (..., mites, recordings), counted
        in its labelled recordings as calibration.death_recording() counts: the
        one after its last movement, 0 for a mite that never moved."""
        calls = np.asarray(calls, dtype=bool) & self.labelled
        n_recordings = calls.shape[-1]
        last = n_recordings - 1 - np.argmax(calls[..., ::-1], axis=-1)
        seen = np.broadcast_to(np.cumsum(self.labelled, axis=1), calls.shape)
        after_last = np.take_along_axis(seen, last[..., None], axis=-1)[..., 0]
        return np.where(calls.any(axis=-1), after_last, 0)

    def death_errors(self, calls):
        """Per mite, the death by `calls` minus the death by the labels, in
        recordings: positive when the calls have it die later."""
        return self.deaths(calls) - self.deaths(self.moving)

    def reviewed(self, low, high):
        """The calls with a band from `low` to `high` checked by eye: moving at
        or above `high`, still below `low`, the label in between."""
        in_band = (self.scores >= low) & (self.scores < high)
        return np.where(in_band, self.moving, self.scores >= high) & self.labelled

    def checks(self, low, high):
        """Per mite, the recordings to look at for its death with that band:
        those in the band after its last score at or above `high`, from the last
        one back to the first in which it moves."""
        counts = np.zeros(self.n_mites, dtype=int)
        clear = (self.scores >= high) & self.labelled
        in_band = (self.scores >= low) & (self.scores < high) & self.labelled
        for mite in range(self.n_mites):
            above = np.flatnonzero(clear[mite])
            after = np.flatnonzero(in_band[mite])
            after = after[after > (above[-1] if len(above) else -1)][::-1]
            moved = np.flatnonzero(self.moving[mite, after])
            counts[mite] = moved[0] + 1 if len(moved) else len(after)
        return counts


def runs_of_rows(rows):
    """The observations of a calibration report ([{dataset, mite_id, recording,
    score, movement}, ...], one per labelled mite-recording) as one LabelledRun
    per dataset."""
    runs = []
    for dataset in dict.fromkeys(row["dataset"] for row in rows):
        here = [row for row in rows if row["dataset"] == dataset]
        mites = {mite_id: index for index, mite_id in enumerate(dict.fromkeys(row["mite_id"] for row in here))}
        shape = (len(mites), max(row["recording"] for row in here) + 1)
        scores, moving, labelled = np.zeros(shape), np.zeros(shape, dtype=bool), np.zeros(shape, dtype=bool)
        for row in here:
            at = mites[row["mite_id"]], row["recording"]
            scores[at], moving[at], labelled[at] = row["score"], row["movement"] == "moving", True
        runs.append(LabelledRun(scores, moving, labelled))
    return runs


def candidate_thresholds(runs):
    """Every threshold that calls the labelled recordings differently: halfway
    between each two neighbouring scores, and one above them all."""
    scores = np.unique(np.concatenate([run.scores[run.labelled] for run in runs]))
    if not len(scores):
        return np.array([])
    return np.append((scores[:-1] + scores[1:]) / 2, scores[-1] + 1.0)


def death_mae(runs, thresholds):
    """Per threshold, the mean distance in recordings between the death by the
    detector and the death by the labels, over the mites of every run."""
    thresholds = np.atleast_1d(np.asarray(thresholds, dtype=float))
    total = np.zeros(len(thresholds))
    for run in runs:
        for start in range(0, len(thresholds), _CHUNK):
            part = thresholds[start:start + _CHUNK]
            calls = run.scores[None] >= part[:, None, None]
            total[start:start + _CHUNK] += np.abs(run.death_errors(calls)).sum(axis=-1)
    return total / max(1, sum(run.n_mites for run in runs))


def best_threshold(runs):
    """(threshold, its death_mae()): the threshold with the smallest mean death
    error. Many do as well as each other; the one returned is the middle of the
    widest stretch of them, the furthest from where the error grows."""
    thresholds = candidate_thresholds(runs)
    if not len(thresholds):
        raise ValueError("No labelled recordings to choose a threshold from.")
    errors = death_mae(runs, thresholds)
    best = np.isclose(errors, errors.min())
    edges = np.flatnonzero(np.diff(np.concatenate([[0], best.astype(int), [0]])))
    stretches = [(thresholds[first], thresholds[end - 1]) for first, end in zip(edges[::2], edges[1::2])]
    low, high = max(stretches, key=lambda stretch: stretch[1] - stretch[0])
    return float((low + high) / 2), float(errors.min())


def band_outcome(runs, low, high):
    """What a band checked by eye leaves: {mae: the mean death error after the
    checks, checks_per_mite, exact: the share of mites whose death is right}."""
    errors = np.concatenate([run.death_errors(run.reviewed(low, high)) for run in runs])
    checks = np.concatenate([run.checks(low, high) for run in runs])
    return {"mae": float(np.abs(errors).mean()), "checks_per_mite": float(checks.mean()),
            "exact": float((errors == 0).mean())}


def best_band(runs, threshold, checks_per_mite, steps=30):
    """(low, high): the band around `threshold` with the smallest mean death
    error among those asking for at most `checks_per_mite` checks per mite, and
    the fewest checks among the equally good. `steps` edges are tried on each
    side, from the middle still score up to the highest still one."""
    still = np.concatenate([run.scores[run.labelled & ~run.moving] for run in runs])
    if not len(still):
        return threshold, threshold
    lows = np.linspace(min(np.median(still), threshold), threshold, steps)
    highs = np.linspace(threshold, max(still.max() + 1e-6, threshold), steps)
    best, best_key = (threshold, threshold), None
    for low in lows:
        for high in highs:
            outcome = band_outcome(runs, low, high)
            if outcome["checks_per_mite"] > checks_per_mite:
                continue
            key = (round(outcome["mae"], 9), outcome["checks_per_mite"], high - low)
            if best_key is None or key < best_key:
                best, best_key = (float(low), float(high)), key
    return best
