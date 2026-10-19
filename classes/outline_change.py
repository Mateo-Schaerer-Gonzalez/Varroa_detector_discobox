"""How much a mite's outline changes from one recording to the next, wherever
the mite lies: a change between recordings that opening the box to poke the
mites does not fake (notebooks/moved_mite_change.ipynb).

A mite's outline in a recording is read from the mean of its frames: from the
centre of its body a ray goes out at each of ANGLES angles, and the darkness
along it is summed, so a leg makes the rays that cross it longer. Its size and a
shift of the whole mite are taken out (shape_only()), and two outlines are
compared at the turn of the later one that fits best, so a mite pushed a few
pixels or turned changes nothing; one that moved a leg does.

Two things keep it to the mite. Its darkness is read against the plate in a
ring around it, as the light falls off across a plate and a pushed mite lies on
brighter or darker plate. And its body is the dark piece nearest the middle of
its patch, its outline only what lies within BODY_REACH of it: a neighbour at
the patch's edge is not in it.

A pair of recordings changed when the change passes LIMIT, what 99% of the pairs
of the long run's mites long dead stay under (the notebook). A mite moved in a
recording when the pairs on both sides of the one before changed, two in a row,
as a single pair over LIMIT comes once in about a hundred by chance.
"""

import cv2
import numpy as np

RIM = 6              # the outermost pixels of a patch: the plate, never the mite
RING = (6, 10)       # px from the body the plate's light around it is measured in
ANGLES, REACH, RAY_STEP = 64, 13.0, 0.25
BODY_REACH = 6       # px from the body the outline reads: the legs (classes/leg_tracker.py: 4 past its edge)
PAD = 16             # px around a mite's box its patch needs: REACH from the centre, RING past the body
RAYS = 4             # the largest differences of two outlines a change is the mean of
LIMIT = 0.064        # px: a change of a pair of recordings above this is one


def darkness(image):
    """(darkness, plate): how much of the plate's light each pixel takes away,
    0 to 1. The plate is the median of a ring around the mite (found against
    the patch's rim first): the light falls off across a plate, and a mite
    pushed elsewhere lies on brighter or darker plate than before."""
    image = np.asarray(image, dtype=np.float32)
    rim = np.ones(image.shape, dtype=bool)
    rim[RIM:-RIM, RIM:-RIM] = False
    plate = float(np.median(image[rim]))
    if plate <= 0:
        return np.zeros(image.shape, dtype=np.float32), plate
    # the body: half as dark as its darkest, which no estimate of the plate moves (a faint
    # shadow beside a mite is in or out of a fixed limit as the plate's estimate goes)
    dark = 1 - image / plate
    mite = (dark > 0.5 * dark.max()).astype(np.uint8)
    grow = np.ones((3, 3), np.uint8)
    ring = cv2.dilate(mite, grow, iterations=RING[1]).astype(bool) & ~cv2.dilate(mite, grow, iterations=RING[0]).astype(bool)
    if ring.sum() >= 20:
        plate = float(np.median(image[ring]))
    return np.clip(1 - image / plate, 0, None).astype(np.float32), plate


def body(dark):
    """The mite's body: of the pieces at least half as dark as the darkest,
    the one nearest the patch's centre (of those a fifth the size of the
    largest or more). A neighbour at the patch's edge is another piece."""
    count, labels, stats, centres = cv2.connectedComponentsWithStats((dark > 0.5 * dark.max()).astype(np.uint8))
    if count < 2:
        return labels > 0
    areas = stats[1:, cv2.CC_STAT_AREA]
    middle = (np.array(dark.shape[::-1]) - 1) / 2
    distance = np.where(areas >= 0.2 * areas.max(), np.hypot(*(centres[1:] - middle).T), np.inf)
    return labels == 1 + int(np.argmin(distance))


def centre(dark):
    """(x, y) of the mite's body()."""
    weight = dark * body(dark)
    yy, xx = np.mgrid[:dark.shape[0], :dark.shape[1]]
    return np.array([(weight * xx).sum(), (weight * yy).sum()]) / max(float(weight.sum()), 1e-9)


def outline(image):
    """The mite's outline unrolled, (ANGLES,): from its centre a ray at each
    angle, the darkness along it summed (the pixels it would cover if black),
    within BODY_REACH of its body(): a neighbour further off is not in it."""
    dark, _plate = darkness(image)
    if not dark.any():
        return np.zeros(ANGLES)
    x, y = centre(dark)
    near = cv2.dilate(body(dark).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=BODY_REACH).astype(bool)
    dark = np.where(near, dark, 0).astype(np.float32)
    angle = np.arange(ANGLES) * 2 * np.pi / ANGLES
    along = np.arange(0, REACH, RAY_STEP)
    map_x = (x + np.outer(np.cos(angle), along)).astype(np.float32)
    map_y = (y + np.outer(np.sin(angle), along)).astype(np.float32)
    return cv2.remap(dark, map_x, map_y, cv2.INTER_LINEAR).sum(axis=1) * RAY_STEP


def shape_only(profile):
    """An outline without its size and without a shift of the whole mite: its
    first two harmonics in the angle taken out."""
    harmonics = np.fft.rfft(profile, axis=-1)
    harmonics[..., :2] = 0
    return np.fft.irfft(harmonics, n=profile.shape[-1], axis=-1)


def outline_change(earlier, later, rays=RAYS):
    """How far the outline's shape moved, in pixels (the mean of the `rays`
    largest differences), at the turn of the later outline that fits best."""
    a, b = shape_only(np.asarray(earlier, dtype=float)), shape_only(np.asarray(later, dtype=float))
    turned = np.stack([np.roll(b, shift) for shift in range(ANGLES)])
    return float(np.sort(np.abs(a - turned), axis=1)[:, -rays:].mean(axis=1).min())


class OutlineChange:
    """The outline change of a mite between recordings, and what it says of
    whether the mite moved. `limit`: the change from which a pair of recordings
    changed (LIMIT unless given)."""

    def __init__(self, limit=LIMIT):
        self.limit = float(limit)

    @staticmethod
    def outline_of(frames):
        """The outline of one recording of a mite: its frames (frames, height,
        width), grey, its box with PAD pixels around it."""
        frames = np.asarray(frames, dtype=np.float32)
        return outline(frames.reshape(frames.shape[:3]).mean(axis=0))

    @staticmethod
    def changes(outlines):
        """Per recording the change from the one before, in px: None for the
        first. `outlines`: one per recording (outline_of())."""
        return [None] + [outline_change(earlier, later) for earlier, later in zip(outlines, outlines[1:])]

    def calls(self, changes):
        """Whether the mite moved in each recording, by `changes` (changes()):
        when the change into it and the one into the recording before both
        passed the limit. Never in the first two recordings."""
        changed = [change is not None and change > self.limit for change in changes]
        return [False] + [changed[at] and changed[at - 1] for at in range(1, len(changed))] if changes else []

    def raster(self, mites):
        """The figure of every mite's outline change. `mites`: [{dataset,
        dataset_name, mite_id, zone_id, moving (its labels per recording: True,
        False or None), changes, calls}]. Returns {limit, scale, mites}: `scale`
        the changes the figure colours from low to high (half the limit, about a
        still mite's, to eight times it, a mite moving its legs); `mites` those labelled
        moving at least once (one never seen moving may have been dead from the
        start), in the order the labels have them die, each without its labels
        and calls but with its death by them ("death") and by the outline change
        ("outline_death", None when it never called the mite moving): the
        recording after the last movement."""
        rows = []
        for mite in mites:
            moved = [at for at, value in enumerate(mite["moving"]) if value]
            if not moved:
                continue
            called = [at for at, value in enumerate(mite["calls"]) if value]
            rows.append({**{key: mite[key] for key in ("dataset", "dataset_name", "mite_id", "zone_id", "changes")},
                         "death": moved[-1] + 1, "outline_death": called[-1] + 1 if called else None})
        rows.sort(key=lambda row: row["death"])
        return {"limit": self.limit, "scale": [self.limit / 2, self.limit * 8], "mites": rows}
