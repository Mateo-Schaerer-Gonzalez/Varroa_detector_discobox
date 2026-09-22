"""Compares the motion scores against ground truth the user entered by hand.

The ground truth is one status per mite per recording. The detector calls a mite
alive at a recording when it moves at that recording or at any later one -- the
rule of `Mite.survival` -- which is the same as asking whether the highest score
from that recording onwards reaches the threshold (see `forward_max`). Every
threshold question below is therefore asked of that forward maximum, so a
threshold tuned here means the same thing in a normal analysis.

"alive" is the positive class throughout: the true positive rate is the fraction
of truly alive observations called alive, the false positive rate the fraction
of truly dead observations called alive.
"""

import numpy as np

ALIVE = "alive"
DEAD = "dead"
NOT_A_MITE = "not_a_mite"  # a detection the user rejected: debris, a shadow, ...
TRUTH_STATES = (ALIVE, DEAD, NOT_A_MITE)

# Outcome of one labelled mite at a given threshold.
OUTCOMES = {
    (True, True): "alive_ok",      # alive, called alive
    (False, False): "dead_ok",     # dead, called dead
    (True, False): "alive_missed",  # alive, called dead
    (False, True): "dead_missed",   # dead, called alive
}


def per_recording(truth, n_recordings):
    """A saved status as a list with one entry per recording.

    A single string (the format before truth was entered per recording) applies
    to every recording; a list of the wrong length is cut or padded with None.
    """
    if isinstance(truth, str):
        truth = [truth] * n_recordings
    if not isinstance(truth, list):
        return [None] * n_recordings
    truth = [state if state in TRUTH_STATES else None for state in truth[:n_recordings]]
    return truth + [None] * (n_recordings - len(truth))


def is_rejected(states):
    """True when the user marked this detection as not being a mite.

    Accepts a list of per-recording states or a single saved status.
    """
    return states == NOT_A_MITE or (isinstance(states, list) and NOT_A_MITE in states)


def match_ground_truth(mites, saved, n_recordings, tolerance=10.0):
    """Give each detected mite the saved statuses of the nearest saved position.

    Ground truth is stored by position, not by mite id, so it survives a change in
    the detector settings that renumbers the mites. `mites` and `saved` are lists
    of dicts with "x" and "y"; each saved entry is used at most once, by the
    closest mite within `tolerance` pixels. Returns {mite id: [status per
    recording]}, where a status is "alive", "dead", "not_a_mite" or None.
    """
    pairs = []
    for mite in mites:
        for index, entry in enumerate(saved):
            distance = np.hypot(mite["x"] - entry["x"], mite["y"] - entry["y"])
            if distance <= tolerance:
                pairs.append((distance, mite["id"], index))

    truth, used_mites, used_saved = {}, set(), set()
    for _distance, mite_id, index in sorted(pairs):
        if mite_id in used_mites or index in used_saved:
            continue
        states = per_recording(saved[index].get("truth"), n_recordings)
        if any(states):
            truth[mite_id] = states
        used_mites.add(mite_id)
        used_saved.add(index)
    return truth


def roc_curve(scores, is_alive):
    """False and true positive rates at every distinct threshold, highest first.

    Returns (fpr, tpr, thresholds). The first point is (0, 0) at an infinite
    threshold, the last (1, 1) at the lowest score.
    """
    scores = np.asarray(scores, dtype=float)
    is_alive = np.asarray(is_alive, dtype=bool)
    n_alive, n_dead = is_alive.sum(), (~is_alive).sum()
    if n_alive == 0 or n_dead == 0:
        raise ValueError("The ground truth needs at least one alive and one dead mite.")

    thresholds = np.unique(scores)[::-1]
    tpr = np.array([(scores[is_alive] >= t).sum() for t in thresholds]) / n_alive
    fpr = np.array([(scores[~is_alive] >= t).sum() for t in thresholds]) / n_dead
    return (
        np.concatenate([[0.0], fpr]),
        np.concatenate([[0.0], tpr]),
        np.concatenate([[np.inf], thresholds]),
    )


def auc(scores, is_alive):
    """Area under the ROC curve: the chance that a random alive mite scores higher
    than a random dead one, ties counting half."""
    scores = np.asarray(scores, dtype=float)
    is_alive = np.asarray(is_alive, dtype=bool)
    alive, dead = scores[is_alive][:, None], scores[~is_alive][None, :]
    if alive.size == 0 or dead.size == 0:
        raise ValueError("The ground truth needs at least one alive and one dead mite.")
    return float(((alive > dead) + 0.5 * (alive == dead)).mean())


def best_threshold(scores, is_alive):
    """The threshold that maximises sensitivity + specificity (Youden's J).

    Any value between the lowest score called alive and the next score below it
    gives the same predictions, so the threshold is placed halfway into that gap,
    as far as possible from the mites on either side.
    """
    scores = np.asarray(scores, dtype=float)
    fpr, tpr, thresholds = roc_curve(scores, is_alive)
    best = int(np.argmax(tpr[1:] - fpr[1:])) + 1  # skip the infinite threshold
    lowest_alive = thresholds[best]
    below = scores[scores < lowest_alive]
    return float((lowest_alive + below.max()) / 2) if below.size else float(lowest_alive)


def confusion(scores, is_alive, threshold):
    """Counts and rates of the four outcomes at one threshold."""
    scores = np.asarray(scores, dtype=float)
    is_alive = np.asarray(is_alive, dtype=bool)
    called_alive = scores >= threshold

    counts = {
        name: int(((is_alive == truth) & (called_alive == called)).sum())
        for (truth, called), name in OUTCOMES.items()
    }
    n_alive = counts["alive_ok"] + counts["alive_missed"]
    n_dead = counts["dead_ok"] + counts["dead_missed"]
    total = n_alive + n_dead

    def ratio(a, b):
        return None if b == 0 else a / b

    return {
        "threshold": float(threshold),
        **counts,
        "accuracy": ratio(counts["alive_ok"] + counts["dead_ok"], total),
        "sensitivity": ratio(counts["alive_ok"], n_alive),  # alive mites called alive
        "specificity": ratio(counts["dead_ok"], n_dead),    # dead mites called dead
    }


def outcome(truth, score, threshold):
    """The outcome name for one mite, or None if it is not labelled alive or dead."""
    if truth not in (ALIVE, DEAD):
        return None
    return OUTCOMES[(truth == ALIVE, score >= threshold)]


def forward_max(scores):
    """For each recording, the highest score from that recording onwards.

    A mite is called alive at a recording when this reaches the threshold.
    """
    return [float(value) for value in np.maximum.accumulate(np.asarray(scores, dtype=float)[::-1])[::-1]]


def has_both_classes(is_alive):
    is_alive = np.asarray(is_alive, dtype=bool)
    return bool(is_alive.any() and not is_alive.all())


def survival(observations, n_recordings, thresholds):
    """Fraction of mites alive at each recording, by the ground truth and as called
    by the detector at each of `thresholds` ({name: value}).

    Only observations with a ground truth count, and the detector is judged on
    exactly the same ones, so the curves can be compared point by point. A
    recording with no labelled mite gives None.
    """
    result = {"n": [], "truth": [], **{name: [] for name in thresholds}}
    for recording in range(n_recordings):
        rows = [row for row in observations if row["recording"] == recording]
        result["n"].append(len(rows))
        if not rows:
            for key in ["truth", *thresholds]:
                result[key].append(None)
            continue
        result["truth"].append(sum(row["truth"] == ALIVE for row in rows) / len(rows))
        for name, threshold in thresholds.items():
            result[name].append(sum(row["score"] >= threshold for row in rows) / len(rows))
    return result
