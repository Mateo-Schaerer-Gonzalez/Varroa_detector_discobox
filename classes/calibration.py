"""Compares the motion scores against movement the user saw with their own eyes.

For each mite and each recording the user labels what the camera can show:
whether the mite moves ("moving") or not ("still"). The detector calls a mite
moving in a recording when that recording's score reaches the threshold. Every
comparison here is between those two, one (mite, recording) at a time; moving is
the positive class.
"""

import numpy as np

MOVING = "moving"
STILL = "still"
NOT_A_MITE = "not_a_mite"  # a detection the user rejected: debris, a shadow, ...
TRUTH_STATES = (MOVING, STILL, NOT_A_MITE)

# The first labels were saved as "alive" / "dead"; they meant moving / still.
_OLDER_STATES = {"alive": MOVING, "dead": STILL}


def per_recording(truth, n_recordings):
    """A saved status as a list with one entry per recording.

    A single string (the format before truth was entered per recording) applies
    to every recording; a list of the wrong length is cut or padded with None.
    """
    if isinstance(truth, str):
        truth = [truth] * n_recordings
    if not isinstance(truth, list):
        return [None] * n_recordings
    truth = [_OLDER_STATES.get(state, state) for state in truth[:n_recordings]]
    truth = [state if state in TRUTH_STATES else None for state in truth]
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
    recording]}, where a status is "moving", "still", "not_a_mite" or None.
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


def has_both_classes(moving):
    moving = np.asarray(moving, dtype=bool)
    return bool(moving.any() and not moving.all())


def roc_curve(scores, moving):
    """False and true positive rates at every distinct threshold, highest first.

    Returns (fpr, tpr, thresholds). The first point is (0, 0) at an infinite
    threshold, the last (1, 1) at the lowest score.
    """
    scores = np.asarray(scores, dtype=float)
    moving = np.asarray(moving, dtype=bool)
    if not has_both_classes(moving):
        raise ValueError("A ROC curve needs both moving and still labels.")

    thresholds = np.unique(scores)[::-1]
    tpr = np.array([(scores[moving] >= t).sum() for t in thresholds]) / moving.sum()
    fpr = np.array([(scores[~moving] >= t).sum() for t in thresholds]) / (~moving).sum()
    return (
        np.concatenate([[0.0], fpr]),
        np.concatenate([[0.0], tpr]),
        np.concatenate([[np.inf], thresholds]),
    )


def auc(scores, moving):
    """Area under the ROC curve: the chance that a random moving observation
    scores higher than a random still one, ties counting half."""
    scores = np.asarray(scores, dtype=float)
    moving = np.asarray(moving, dtype=bool)
    if not has_both_classes(moving):
        raise ValueError("AUC needs both moving and still labels.")
    pos, neg = scores[moving][:, None], scores[~moving][None, :]
    return float(((pos > neg) + 0.5 * (pos == neg)).mean())


def best_threshold(scores, moving):
    """The threshold that maximises sensitivity + specificity (Youden's J).

    Any value between the lowest score called moving and the next score below it
    gives the same calls, so the threshold is placed halfway into that gap, as
    far as possible from the observations on either side.
    """
    scores = np.asarray(scores, dtype=float)
    fpr, tpr, thresholds = roc_curve(scores, moving)
    best = int(np.argmax(tpr[1:] - fpr[1:])) + 1  # skip the infinite threshold
    lowest_moving = thresholds[best]
    below = scores[scores < lowest_moving]
    return float((lowest_moving + below.max()) / 2) if below.size else float(lowest_moving)


def outcome(is_moving, score, threshold):
    """Name of the outcome of one observation, e.g. "still_called_moving"."""
    truth = MOVING if is_moving else STILL
    called = MOVING if score >= threshold else STILL
    return f"{truth}_called_{called}"


def confusion(scores, moving, threshold):
    """Counts of the four outcomes at one threshold, plus accuracy, sensitivity
    (moving called moving) and specificity (still called still)."""
    scores = np.asarray(scores, dtype=float)
    moving = np.asarray(moving, dtype=bool)
    called = scores >= threshold

    counts = {
        "moving_called_moving": int((moving & called).sum()),
        "moving_called_still": int((moving & ~called).sum()),
        "still_called_moving": int((~moving & called).sum()),
        "still_called_still": int((~moving & ~called).sum()),
    }
    n_moving, n_still = int(moving.sum()), int((~moving).sum())

    def ratio(a, b):
        return None if b == 0 else a / b

    return {
        "threshold": float(threshold),
        **counts,
        "n_moving": n_moving,
        "n_still": n_still,
        "n_wrong": counts["moving_called_still"] + counts["still_called_moving"],
        "accuracy": ratio(counts["moving_called_moving"] + counts["still_called_still"], n_moving + n_still),
        "sensitivity": ratio(counts["moving_called_moving"], n_moving),
        "specificity": ratio(counts["still_called_still"], n_still),
    }


def moving_over_time(rows, n_recordings, thresholds):
    """Fraction of the labelled mites moving in each recording, by the labels and
    as called by the detector at each of `thresholds` ({name: value}).

    `rows` have "recording", "movement" (the label) and "score". The detector is
    judged on exactly the same rows, so the curves compare point by point. A
    recording without rows gives None.
    """
    result = {"n": [], "truth": [], **{name: [] for name in thresholds}}
    for recording in range(n_recordings):
        here = [row for row in rows if row["recording"] == recording]
        result["n"].append(len(here))
        if not here:
            for key in ["truth", *thresholds]:
                result[key].append(None)
            continue
        result["truth"].append(sum(row["movement"] == MOVING for row in here) / len(here))
        for name, threshold in thresholds.items():
            result[name].append(sum(row["score"] >= threshold for row in here) / len(here))
    return result
