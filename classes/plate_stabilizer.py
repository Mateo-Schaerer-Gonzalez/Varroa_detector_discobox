"""Takes a shaking plate out of the frames before the mites are scored.

A shake of half a pixel, too small to see, moves every mite's outline across
its pixels and makes a still mite score like a moving one with any metric. Each
mite's shift from the first frame is measured on its patch, and its patch is
cut from each frame moved back by its own shift, then scored as usual
(follow()). A glued mite moves with what it is glued to, so that follows the
plate where the mite is, also where the plate's parts move apart.

A mite's own shift is not always the plate's: the legs of a moving mite pull it
by up to a quarter of a pixel, and another mite walking through its patch pulls
it along (notebooks/per_mite_stabilization.ipynb). Where it strays further than
STRAY_LIMIT from the plate's shift (the median over the mites, which the few
can't pull), the patch is moved back by the plate's shift instead, and the stray
is reported, so that recording can be set aside (classes/unusual_activity.py).
"""

import math
from collections import namedtuple

import cv2
import numpy as np

from classes.workers import side_by_side

# How far beyond the patch the Lanczos interpolation reads, in pixels.
_LANCZOS_REACH = 4
_ECC_CRITERIA = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)
# Pixels a mite's own shift may stray from the plate's before the plate's is used:
# above the 0.26 px the legs of a glued moving mite reach, far above the 0.06 px of a still one.
STRAY_LIMIT = 0.3

# How one mite's patch follows the plate in one recording: `shifts` (N, 2), what
# its frames are moved back by; `stray`, the most its own shift strayed from the
# plate's (px); `shake`, the most its own shift moved from the first frame (px);
# `own`, whether its own shifts were used (else the plate's).
Following = namedtuple("Following", "shifts stray shake own")


class PlateStabilizer:
    """`pad`: pixels around each mite's box used to measure its shift, so the
    whole outline is in it."""

    def __init__(self, pad=8):
        self.pad = pad

    def shifts(self, frames, boxes):
        """(N, 2) array: per frame, how far (dx, dy) the plate moved since the
        first frame, in pixels: the median of the mites' own shifts. `frames` is
        a stack or a list of (H, W, C) frames, `boxes` the mites' (x1, y1, x2,
        y2) in those frames."""
        return self.measure(frames, boxes)[1]

    def measure(self, frames, boxes):
        """(per mite, plate): each mite's own shifts, (mites, N, 2), and the
        plate's, their median, (N, 2)."""
        if not boxes or len(frames) < 2:
            return np.zeros((len(boxes), len(frames), 2)), np.zeros((len(frames), 2))
        # one mite's shifts say nothing of another's: they are measured side by side
        per_mite = np.array(side_by_side(lambda box: self._mite_shifts(frames, box), boxes), dtype=float)
        return per_mite, np.median(per_mite, axis=0)

    def follow(self, frames, boxes):
        """Per mite, a Following: its own shifts, or the plate's where its own
        stray further than STRAY_LIMIT from them."""
        per_mite, plate = self.measure(frames, boxes)
        followed = []
        for own in per_mite:
            stray = float(np.hypot(*(own - plate).T).max()) if len(own) else 0.0
            shake = float(np.hypot(*own.T).max()) if len(own) else 0.0
            keep = stray <= STRAY_LIMIT
            followed.append(Following(own if keep else plate, stray, shake, keep))
        return followed

    def _mite_shifts(self, frames, box):
        """Per frame, how far one mite's patch moved since the first frame."""
        patches = _gray(_patches(frames, box[0] - self.pad, box[1] - self.pad, box[2] + self.pad, box[3] + self.pad))
        window = cv2.createHanningWindow(patches.shape[:0:-1], cv2.CV_32F)  # the same for every frame
        return [self._shift(patches[0], patch, window) for patch in patches]

    @staticmethod
    def _shift(reference, moved, window=None):
        """How far `moved` is shifted from `reference`: phase correlation for a
        first guess, refined by ECC. Phase correlation alone is off by a few
        tenths of a pixel on a patch this small, ECC by a few hundredths, but
        ECC only finds its way from close by. `window`: the Hanning window of
        patches this size, from whoever measures many of them."""
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
        by the plate's shift in it."""
        height, width = frames[0].shape[:2]
        x1, y1 = max(0, box[0] - pad), max(0, box[1] - pad)
        x2, y2 = min(width, box[2] + pad), min(height, box[3] + pad)
        out = None
        for index, (frame, (dx, dy)) in enumerate(zip(frames, np.asarray(shifts, dtype=float).tolist())):
            m = math.ceil(max(abs(dx), abs(dy))) + _LANCZOS_REACH
            patch = _patch(frame, x1 - m, y1 - m, x2 + m, y2 + m).astype(np.float32)
            patch = cv2.warpAffine(patch, _move(-dx, -dy), patch.shape[1::-1], flags=cv2.INTER_LANCZOS4,
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


def _gray(patches):
    """A stack of patches in grey, float32: (N, h, w) from (N, h, w, C), the
    mean of each pixel's channels."""
    patches = patches.astype(np.float32, copy=False)
    return np.ascontiguousarray(patches.mean(axis=-1) if patches.ndim == 4 else patches)
