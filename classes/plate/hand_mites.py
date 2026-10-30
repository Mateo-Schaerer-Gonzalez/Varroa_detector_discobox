"""Mites placed by hand where the detector missed them.

They are kept next to the recordings as points, {x, y, size}: the mite's centre
and the side of its box, in image pixels (pipeline/hand_mites.py). Wherever the
mites are found on whole frames, ZoneManager.assign_mites() puts them with the
detector's (missing()), so the label page, a folder's analysis, its shrinking to
ROIs and a live run all have the same mites. A point within positions.TOLERANCE
of a detection is that detection (the detector finds it after all, e.g. with
other settings) and counts once.
"""

import cv2
import numpy as np

from classes.plate import positions
from classes.plate.mite import Mite

# Pixels round a click in which the mite's centre is looked for (centre_near()):
# the click is made on the plate scaled down to the screen, a few pixels off.
SNAP_REACH = 8
# The mite's body, round the darkest spot near a click: the pixels darker than
# this share of the way from the darkest to the median there (centre_near()).
BODY_SHARE = 0.25


def box_at(x, y, size):
    """(x1, y1, x2, y2): a square box centred on the pixel (x, y), its side
    `size` rounded up to an even number."""
    x, y, half = int(round(x)), int(round(y)), int(size / 2 + 0.5)
    return (x - half, y - half, x + half, y + half)


def box_size(mites, radius):
    """The side of a box placed by hand: the median of the detector's boxes
    `mites`, so it is scored as they are; twice `radius` (the config's
    mite.radius) when there are none."""
    sides = [mite.x2 - mite.x1 for mite in mites]
    return int(round(float(np.median(sides)))) if sides else 2 * int(radius)


def centre_near(image, x, y, reach=SNAP_REACH, dark=True):
    """(x, y): the centre of the mite clicked at (x, y) on the (H, W) grey
    `image`: of the pixels within `reach` px, smoothed, those darker than
    BODY_SHARE of the way from the darkest to their median (brighter, if not
    `dark`), rounded to a pixel. (x, y) itself where they are all alike."""
    height, width = image.shape[:2]
    x, y = int(round(x)), int(round(y))
    x1, y1 = max(0, x - reach - 2), max(0, y - reach - 2)
    x2, y2 = min(width, x + reach + 3), min(height, y + reach + 3)
    if x2 <= x1 or y2 <= y1:
        return x, y
    patch = cv2.GaussianBlur(np.ascontiguousarray(image[y1:y2, x1:x2]), (5, 5), 0).astype(float)
    if not dark:
        patch = -patch
    yy, xx = np.mgrid[y1:y2, x1:x2]
    near = np.hypot(xx - x, yy - y) <= reach
    darkest, median = patch[near].min(), np.median(patch[near])
    if darkest == median:
        return x, y
    body = near & (patch <= darkest + BODY_SHARE * (median - darkest))
    return int(round(float(xx[body].mean()))), int(round(float(yy[body].mean())))


def missing(points, mites):
    """Mites for the `points` ({x, y, size}) not within positions.TOLERANCE of
    one of `mites` (the detector's), each marked `by_hand`."""
    found = [{"x": x, "y": y} for x, y in (mite.home for mite in mites)]
    made = []
    for point in points:
        if positions.away_from_all(point, found):
            mite = Mite(*box_at(point["x"], point["y"], point["size"]))
            mite.by_hand = True
            made.append(mite)
    return made
