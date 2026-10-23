"""Which saved entry belongs to which mite.

Ground truth, poke tests, call corrections and "not a mite" marks are saved by
position ({x, y} in image pixels), not by mite id, so they still apply after a
change of detector settings renumbers the mites. A saved position belongs to a
mite within TOLERANCE pixels of it.
"""

import numpy as np

TOLERANCE = 10.0  # pixels between a mite and a saved position that is its


def distance(a, b):
    """Pixels between two positions, each with "x" and "y"."""
    return float(np.hypot(a["x"] - b["x"], a["y"] - b["y"]))


def closest_pairs(mites, entries, tolerance=TOLERANCE):
    """{mite id: index in `entries`}: each entry to the mite closest to it within
    `tolerance` pixels, the closest pairs first, a mite and an entry used once.
    `mites` have "id", "x" and "y"; `entries` "x" and "y". In the order the
    pairs were made."""
    candidates = sorted((distance(mite, entry), mite["id"], index)
                        for mite in mites for index, entry in enumerate(entries))
    paired, used = {}, set()
    for gap, mite_id, index in candidates:
        if gap > tolerance:
            break
        if mite_id not in paired and index not in used:
            paired[mite_id] = index
            used.add(index)
    return paired


def within(entries, x, y, tolerance=TOLERANCE):
    """The entries within `tolerance` pixels of (x, y), in their order."""
    at = {"x": x, "y": y}
    return [entry for entry in entries if distance(entry, at) <= tolerance]


def nearest(entries, x, y, tolerance=TOLERANCE):
    """The entry nearest (x, y) within `tolerance` pixels (the first of those
    as near), or None."""
    at = {"x": x, "y": y}
    return min(within(entries, x, y, tolerance), key=lambda entry: distance(entry, at), default=None)


def away_from_all(entry, others, tolerance=TOLERANCE):
    """Whether `entry` is further than `tolerance` pixels from every one of `others`."""
    return all(distance(entry, other) > tolerance for other in others)
