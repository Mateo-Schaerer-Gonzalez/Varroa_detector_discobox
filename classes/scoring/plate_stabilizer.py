"""Takes a shaking plate out of the frames before the mites are scored.

A shake of half a pixel, too small to see, moves every mite's outline across
its pixels and makes a still mite score like a moving one with any metric. Each
mite's centre is found in every frame (the centre of the darkness of its body),
and its shift is how far that centre moved from the first frame. Its patch is
cut from each frame moved back by that shift, then scored as usual. A glued
mite moves with what it is glued to, so that follows the plate where the mite
is, also where the plates shake apart.

A mite's own shift is not always the plate's: the legs of a moving mite pull
its centre along by about a tenth of a pixel, and another mite walking through
its patch pulls it further. Its own shift is used all the same: on the ground
truth it gives the calls the plate's shift (the median over the mites) gives,
on a plate that shakes as one piece and on one that doesn't, at a twentieth of
the cost of measuring the shift by registration
(notebooks/centre_stabilization.ipynb). A mite that walks off is left out of
the analysis, and a recording another one walked through is set aside
(classes/scoring/unusual_activity.py).
"""

import math
from collections import namedtuple

import cv2
import numpy as np

from classes.scoring.workers import side_by_side

# How far beyond the patch cut() may read for its interpolation, in pixels: Lanczos's
# reach, kept although the cut is bilinear now (which reads 1), so the margins stay as they were.
_LANCZOS_REACH = 4
# The most cut() reads beyond the patch it cuts, in pixels (pipeline.STABILIZE_MARGIN):
# what a saved live run keeps round the scored patch (classes/storage/roi_recordings.py).
MARGIN = 16
# The most a mite's shift is followed, along each axis, so that cut() stays
# within MARGIN. A centre that moves further belongs to a mite that walks.
_REACH = float(MARGIN - _LANCZOS_REACH)
# The constants below, and those of Analyzer._outline_rays(), were chosen by an
# Optuna search on the labelled recordings (trial 228 of
# scripts/pipeline_optuna.py, notebooks/pipeline_optuna.ipynb; the user's choice
# of 2026-10-27). Before: pad 8, rim 6, body 0.3 of the single darkest pixel,
# grown 2 px, Lanczos.
# Pixels round each mite's box in which its centre is found.
PAD = 4
# The outermost pixels of that crop, read for the plate's light: the plate, never the mite.
_RIM = 8
# "The darkest of the mite": the mean of its this many darkest pixels (here and in the score).
DARKEST_N = 8
# The body: darker than this share of the darkest, grown by BODY_GROW pixels.
BODY_SHARE = 0.241
BODY_GROW = 4
# How each frame is moved back by the mite's shift.
INTERPOLATION = cv2.INTER_LINEAR
_ECC_CRITERIA = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)
# How one mite's patch follows the plate in one recording: `shifts` (N, 2), its
# own, what its frames are moved back by; `stray`, the most they strayed from the
# plate's, the median of every mite's (px); `shake`, the most they moved from the
# first frame (px).
Following = namedtuple("Following", "shifts stray shake")


class PlateStabilizer:
    """`pad`: pixels around each mite's box in which its centre is found, so the
    whole outline is in it."""

    def __init__(self, pad=PAD):
        self.pad = pad

    def shifts(self, frames, boxes):
        """(mites, N, 2) array: per mite and frame, how far (dx, dy) it moved
        since the first frame, in pixels. `frames` is a stack or a list of (H, W)
        (or (H, W, C)) frames, `boxes` the mites' (x1, y1, x2, y2) in those
        frames, anywhere in them or partly outside. A mite whose centre can't be
        found in every frame (it walked out of its patch, or there is nothing
        dark to follow) takes the plate's shift, the median of the others'."""
        if not boxes or len(frames) < 2:
            return np.zeros((len(boxes), len(frames), 2))
        # one mite's shifts say nothing of another's: they are measured side by side
        own = side_by_side(lambda box: self._mite_shifts(frames, box), boxes)
        found = [shifts for shifts in own if shifts is not None]
        plate = np.median(found, axis=0) if found else np.zeros((len(frames), 2))
        return np.array([plate if shifts is None else shifts for shifts in own], dtype=float)

    def follow(self, frames, boxes):
        """Per mite, a Following: its own shifts, and how far they strayed from
        the plate's and moved from the first frame."""
        per_mite = self.shifts(frames, boxes)
        if not len(per_mite) or not per_mite.shape[1]:
            return [Following(own, 0.0, 0.0) for own in per_mite]
        plate = np.median(per_mite, axis=0)
        return [Following(own, float(np.hypot(*(own - plate).T).max()), float(np.hypot(*own.T).max()))
                for own in per_mite]

    def _mite_shifts(self, frames, box):
        """Per frame, how far one mite's centre moved since the first frame, at
        most _REACH along each axis; None where it can't be found in every frame."""
        patches = _gray(_patches(frames, box[0] - self.pad, box[1] - self.pad, box[2] + self.pad, box[3] + self.pad))
        centres = _centres(patches)
        if centres is None or not np.isfinite(centres).all():
            return None
        return np.clip(centres - centres[0], -_REACH, _REACH)

    @staticmethod
    def _shift(reference, moved, window=None):
        """How far `moved` is shifted from `reference`: phase correlation for a
        first guess, refined by ECC. Phase correlation alone is off by a few
        tenths of a pixel on a patch this small, ECC by a few hundredths, but
        ECC only finds its way from close by. `window`: the Hanning window of
        patches this size, from whoever measures many of them. (Not used to
        stabilize: classes/scoring/mite_look.py and classes/scoring/recording_change.py register
        a mite's images with it.)"""
        if window is None:
            window = cv2.createHanningWindow(reference.shape[::-1], cv2.CV_32F)
        # Copies: phaseCorrelate multiplies float32 images by the window in
        # place, which would spoil the reference for every later frame.
        (dx, dy), _response = cv2.phaseCorrelate(reference.copy(), moved.copy(), window)
        warp = _move(dx, dy)
        try:
            _, warp = cv2.findTransformECC(reference, moved, warp, cv2.MOTION_TRANSLATION, _ECC_CRITERIA, None, 1)
        except cv2.error:
            pass  # a flat patch: keep the first guess
        return float(warp[0, 2]), float(warp[1, 2])

    @staticmethod
    def cut(frames, box, pad, shifts):
        """(N, h, w, C) float32 stack: the mite's box grown by `pad`, cut off at
        the image's edge as Mite.get_ROI() cuts it, from each frame moved back
        by `shifts`, the mite's shift in it. Where that reads past the image's
        edge, the image is mirrored in; shifts() keeps it within MARGIN of the patch."""
        height, width = frames[0].shape[:2]
        x1, y1 = max(0, box[0] - pad), max(0, box[1] - pad)
        x2, y2 = min(width, box[2] + pad), min(height, box[3] + pad)
        out = None
        for index, (frame, (dx, dy)) in enumerate(zip(frames, np.asarray(shifts, dtype=float).tolist())):
            m = math.ceil(max(abs(dx), abs(dy))) + _LANCZOS_REACH
            patch = _patch(frame, x1 - m, y1 - m, x2 + m, y2 + m).astype(np.float32)
            patch = cv2.warpAffine(patch, _move(-dx, -dy), patch.shape[1::-1], flags=INTERPOLATION,
                                   borderMode=cv2.BORDER_REFLECT101)
            patch = patch[m:patch.shape[0] - m, m:patch.shape[1] - m].reshape(y2 - y1, x2 - x1, -1)
            if out is None:
                out = np.empty((min(len(frames), len(shifts)), *patch.shape), dtype=np.float32)
            out[index] = patch
        return np.stack([]) if out is None else out


_STILL = np.float32([[1, 0, 0], [0, 1, 0]])


def _move(dx, dy):
    """The 2 x 3 float32 matrix of a shift by (dx, dy)."""
    move = _STILL.copy()
    move[0, 2] = dx
    move[1, 2] = dy
    return move


def _patch(frame, x1, y1, x2, y2):
    """frame[y1:y2, x1:x2], with the image mirrored in where the box reaches past its edge."""
    if 0 <= x1 <= x2 <= frame.shape[1] and 0 <= y1 <= y2 <= frame.shape[0]:
        return frame[y1:y2, x1:x2]  # all of it in the image, as nearly every patch is: nothing to mirror
    rows = _mirror(np.arange(y1, y2), frame.shape[0])
    cols = _mirror(np.arange(x1, x2), frame.shape[1])
    return frame[np.ix_(rows, cols)]


def _patches(frames, x1, y1, x2, y2):
    """_patch() of every frame, as one float32 stack."""
    first = _patch(frames[0], x1, y1, x2, y2)
    stack = np.empty((len(frames), *first.shape), dtype=np.float32)
    for index, frame in enumerate(frames):
        stack[index] = _patch(frame, x1, y1, x2, y2)
    return stack


def _mirror(index, size):
    period = 2 * size - 2 if size > 1 else 1
    index = np.abs(index) % period
    return np.where(index >= size, period - index, index)


def _centres(patches):
    """(N, 2): the mite's centre (x, y) in each of a stack of grey patches, or
    None for a patch without a mite.

    The centre is that of the darkness of the mite's body, as
    Analyzer._outline_rays() finds it: a pixel's darkness is the share of the
    plate's light it takes away, the plate's light read off the patch's
    outermost pixels frame by frame, so a lamp that flickers changes nothing.
    The body is what is at least BODY_SHARE as dark as the darkest of the mite
    (the mean of its DARKEST_N darkest pixels) in the mean of the frames, the
    piece closest to the middle of the patch (where the mite's box is; another
    piece is a neighbour), and BODY_GROW pixels around it.
    Where the mite moved by a pixel or more, the body is moved along to where it
    is and the centre found again, so none of the mite is left outside it."""
    height, width = patches.shape[1:]
    rim = np.ones((height, width), dtype=bool)
    rim[_RIM:-_RIM, _RIM:-_RIM] = False
    if rim.all():
        return None
    plate = np.median(patches[:, rim], axis=1)
    if plate.min() <= 0:
        return None
    dark = np.clip(1 - patches / plate[:, None, None], 0, None)
    still = dark.mean(axis=0)
    if still[~rim].max() <= 0:
        return None
    darkest = np.sort(still[~rim])[-DARKEST_N:].mean()
    dark_enough = (still > BODY_SHARE * darkest) & ~rim
    pieces = cv2.connectedComponents(dark_enough.astype(np.uint8))[1]
    yy, xx = np.ogrid[:height, :width]
    from_middle = np.hypot(yy - (height - 1) / 2, xx - (width - 1) / 2)
    body = (pieces == pieces.ravel()[np.where(dark_enough, from_middle, np.inf).argmin()]).astype(np.uint8)
    body = cv2.dilate(body, np.ones((3, 3), np.uint8), iterations=BODY_GROW).astype(np.float32)

    middle = _weighted_centres((still * body)[None])
    centres = _weighted_centres(dark * body)
    if middle is None or centres is None:
        return None
    steps = np.round(centres - middle).astype(int)
    if not steps.any():
        return centres
    # each frame's body moved by its whole pixels, cut from the body with room around it
    reach = int(np.abs(steps).max())
    around = np.pad(body, reach)
    moved = np.stack([around[reach - dy:reach - dy + height, reach - dx:reach - dx + width] for dx, dy in steps])
    return _weighted_centres(dark * moved)


def _weighted_centres(weights):
    """(N, 2): the centre (x, y) of each of a stack of (N, h, w) weights, or None
    where one has no weight at all."""
    total = weights.sum(axis=(1, 2), dtype=np.float64)
    if not (total > 0).all():
        return None
    x = weights.sum(axis=1, dtype=np.float64) @ np.arange(weights.shape[2])
    y = weights.sum(axis=2, dtype=np.float64) @ np.arange(weights.shape[1])
    return np.stack([x / total, y / total], axis=1)


def _gray(patches):
    """A stack of patches in grey, float32: (N, h, w) from (N, h, w, C), the
    mean of each pixel's channels."""
    patches = patches.astype(np.float32, copy=False)
    return np.ascontiguousarray(patches.mean(axis=-1) if patches.ndim == 4 else patches)
