"""Takes a shaking plate out of the frames before the mites are scored.

A shake of half a pixel, too small to see, moves every mite's outline across
its pixels and makes a still mite score like a moving one with any metric. The
plate is rigid, so in each frame every mite moves by the same shift; a mite that
walks moves by its own. Each mite's shift from the first frame is measured, and
the median over the mites is the plate's: the walking few can't pull it. Each
mite's patch is then cut from its frame moved back by that shift, and scored as
usual.
"""

import math

import cv2
import numpy as np

# How far beyond the patch the Lanczos interpolation reads, in pixels.
_LANCZOS_REACH = 4
_ECC_CRITERIA = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)


class PlateStabilizer:
    """`pad`: pixels around each mite's box used to measure its shift, so the
    whole outline is in it."""

    def __init__(self, pad=8):
        self.pad = pad

    def shifts(self, frames, boxes):
        """(N, 2) array: per frame, how far (dx, dy) the plate moved since the
        first frame, in pixels. `frames` is a stack or a list of (H, W, C)
        frames, `boxes` the mites' (x1, y1, x2, y2) in those frames."""
        if not boxes or len(frames) < 2:
            return np.zeros((len(frames), 2))
        per_mite = []
        for box in boxes:
            x1, y1, x2, y2 = box[0] - self.pad, box[1] - self.pad, box[2] + self.pad, box[3] + self.pad
            patches = [_gray(_patch(frame, x1, y1, x2, y2)) for frame in frames]
            per_mite.append([self._shift(patches[0], patch) for patch in patches])
        return np.median(np.array(per_mite), axis=0)

    @staticmethod
    def _shift(reference, moved):
        """How far `moved` is shifted from `reference`: phase correlation for a
        first guess, refined by ECC. Phase correlation alone is off by a few
        tenths of a pixel on a patch this small, ECC by a few hundredths, but
        ECC only finds its way from close by."""
        # Copies: phaseCorrelate multiplies float32 images by the window in
        # place, which would spoil the reference for every later frame.
        window = cv2.createHanningWindow(reference.shape[::-1], cv2.CV_32F)
        (dx, dy), _response = cv2.phaseCorrelate(reference.copy(), moved.copy(), window)
        warp = np.float32([[1, 0, dx], [0, 1, dy]])
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
        out = []
        for frame, (dx, dy) in zip(frames, shifts):
            m = math.ceil(max(abs(dx), abs(dy))) + _LANCZOS_REACH
            patch = _patch(frame, x1 - m, y1 - m, x2 + m, y2 + m).astype(np.float32)
            back = np.float32([[1, 0, -dx], [0, 1, -dy]])
            patch = cv2.warpAffine(patch, back, patch.shape[1::-1], flags=cv2.INTER_LANCZOS4,
                                   borderMode=cv2.BORDER_REFLECT101)
            out.append(patch[m:patch.shape[0] - m, m:patch.shape[1] - m].reshape(y2 - y1, x2 - x1, -1))
        return np.stack(out)


def _patch(frame, x1, y1, x2, y2):
    """frame[y1:y2, x1:x2], with the image mirrored in where the box reaches past its edge."""
    rows = _mirror(np.arange(y1, y2), frame.shape[0])
    cols = _mirror(np.arange(x1, x2), frame.shape[1])
    return frame[np.ix_(rows, cols)]


def _mirror(index, size):
    period = 2 * size - 2 if size > 1 else 1
    index = np.abs(index) % period
    return np.where(index >= size, period - index, index)


def _gray(patch):
    patch = patch.astype(np.float32)
    return np.ascontiguousarray(patch.mean(axis=-1) if patch.ndim == 3 else patch)
