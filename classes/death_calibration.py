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
        n_recordings = self.scores.shape[1]
        recording = np.arange(n_recordings)

        def last(marked):  # per mite, its last recording marked; -1 without one
            return np.where(marked.any(axis=1), n_recordings - 1 - np.argmax(marked[:, ::-1], axis=1), -1)

        clear = (self.scores >= high) & self.labelled
        in_band = (self.scores >= low) & (self.scores < high) & self.labelled
        after = in_band & (recording > last(clear)[:, None])
        # from the last one back to the last in which the mite moves; all of them when it moves in none
        return (after & (recording >= last(after & self.moving)[:, None])).sum(axis=1)


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


def death_curve(runs, around, points=160, worse=3.0):
    """The death error by threshold, for a chart around the thresholds `around`
    (e.g. the one in use and the suggested one):

        {thresholds, mae (the mean distance in recordings between the death by
         the detector and by the labels), n_early, n_late (the mites the
         detector has die earlier, later than the labels), n_exact, n_mites}

    `points` thresholds are tried, evenly from the middle score to nearly the
    highest, and those of `around` among the scores. The chart is cut where
    the error passes `worse` times the worst of `around`: further out it only
    grows, and would flatten the part that matters."""
    scores = np.concatenate([run.scores[run.labelled] for run in runs])
    if not len(scores):
        raise ValueError("No labelled recordings to draw a death error from.")
    around = sorted({float(value) for value in around if scores.min() <= value <= scores.max()}) or [best_threshold(runs)[0]]
    low, high = np.quantile(scores, [0.5, 0.995])
    thresholds = np.unique(np.concatenate([np.linspace(min(low, around[0]), max(high, around[-1]), points), around]))
    errors = np.concatenate([run.death_errors(run.scores[None] >= thresholds[:, None, None]) for run in runs], axis=-1)
    mae = np.abs(errors).mean(axis=-1)

    marks = np.searchsorted(thresholds, around)
    limit = max(worse * mae[marks].max(), 1.0)
    first, last = marks[0], marks[-1]
    while first > 0 and mae[first - 1] <= limit:
        first -= 1
    while last < len(thresholds) - 1 and mae[last + 1] <= limit:
        last += 1
    kept = slice(first, last + 1)
    return {"thresholds": [round(float(value), 4) for value in thresholds[kept]],
            "mae": [round(float(value), 3) for value in mae[kept]],
            "n_early": [int(n) for n in (errors < 0).sum(axis=-1)[kept]],
            "n_late": [int(n) for n in (errors > 0).sum(axis=-1)[kept]],
            "n_exact": [int(n) for n in (errors == 0).sum(axis=-1)[kept]],
            "n_mites": int(errors.shape[-1])}


def band_outcome(runs, low, high):
    """What a band checked by eye leaves: {mae: the mean death error after the
    checks, checks_per_mite, exact: the share of mites whose death is right}."""
    errors = np.concatenate([run.death_errors(run.reviewed(low, high)) for run in runs])
    checks = np.concatenate([run.checks(low, high) for run in runs])
    return {"mae": float(np.abs(errors).mean()), "checks_per_mite": float(checks.mean()),
            "exact": float((errors == 0).mean())}


def band_grid(runs, threshold, steps=30):
    """Every band tried around `threshold`, each with its band_outcome():
    [{low, high, mae, checks_per_mite, exact}, ...]. `steps` edges are tried on
    each side: the lower one from the middle still score up to the threshold,
    the upper one from the threshold up to the highest still score, above which
    no still recording is called moving. The first is the threshold alone."""
    still = np.concatenate([run.scores[run.labelled & ~run.moving] for run in runs])
    lows = highs = [threshold]
    if len(still):
        lows = np.linspace(min(np.median(still), threshold), threshold, steps)[::-1]
        highs = np.linspace(threshold, max(still.max() + 1e-6, threshold), steps)
    return [{"low": float(low), "high": float(high), **band_outcome(runs, low, high)} for low in lows for high in highs]


def best_band(runs, threshold, checks_per_mite, steps=30, grid=None):
    """(low, high): the band around `threshold` with the smallest mean death
    error among those asking for at most `checks_per_mite` checks per mite, and
    the fewest checks among the equally good; the threshold alone, (threshold,
    threshold), when no band does better within them. The bands tried are
    band_grid()'s, or `grid` when it is at hand."""
    best, best_key = (threshold, threshold), None
    for band in grid or band_grid(runs, threshold, steps):
        if band["checks_per_mite"] > checks_per_mite:
            continue
        key = (round(band["mae"], 9), band["checks_per_mite"], band["high"] - band["low"])
        if best_key is None or key < best_key:
            best, best_key = (band["low"], band["high"]), key
    return best


def checks_frontier(grid):
    """What the checks buy: of the bands of band_grid(), those worth having, by
    the checks they ask for. Each has a smaller death error than every band
    asking for fewer or as many: the first is the threshold alone, the last the
    best a band can do."""
    frontier = []
    for band in sorted(grid, key=lambda band: (band["checks_per_mite"], band["mae"], band["high"] - band["low"])):
        if not frontier or band["mae"] < frontier[-1]["mae"] - 1e-9:
            frontier.append(band)
    return frontier
