"""How a mite looks in one recording, measured while it is scored, for
classes/scoring/unusual_activity.py: its mean image (its patch, moved back as it is
scored, averaged over the frames), where that sits against its mean image in
the first recording, the orientation of its body, and how dark it is.

Kept with the scores (classes/storage/kept_scores.py): a change here scores again.
"""

import cv2
import numpy as np

from classes.scoring.plate_stabilizer import PlateStabilizer

MARGIN = 8  # pixels round a mite's box in the image its look is taken from


class MiteLook:
    """A mite's look in one recording: its mean image, where it sits against its
    image in the first recording, and the orientation of its body."""

    @staticmethod
    def observe(frames, box, shifts, mite, cut=None, pad=0):
        """{dx, dy, angle, elongation, contrast} of `mite` in this recording: its patch
        (`box` grown by MARGIN) cut from `frames` moved back by `shifts`,
        averaged over the frames, against the first one it was observed in,
        which it keeps (mite.reference_look). `cut`: the patch already cut that
        way with a `pad` of MARGIN or more, e.g. the one scored: the image is
        taken out of it, the very same pixels, instead of cut again."""
        if cut is not None and pad >= MARGIN:
            image = MiteLook._inner(cut, frames[0].shape, box, pad)
        else:
            image = PlateStabilizer.cut(frames, box, MARGIN, shifts)
        image = np.ascontiguousarray(image.mean(axis=(0, 3)) if image.ndim == 4 else image.mean(axis=0), dtype=np.float32)
        reference = getattr(mite, "reference_look", None)
        if reference is None or reference.shape != image.shape:
            mite.reference_look = reference = image
        dx, dy = PlateStabilizer._shift(reference, image) if reference is not image else (0.0, 0.0)
        angle, elongation = MiteLook.body(image)
        return {"dx": dx, "dy": dy, "angle": angle, "elongation": elongation, "contrast": MiteLook.contrast(image)}

    @staticmethod
    def _inner(cut, shape, box, pad):
        """The part of `cut`, PlateStabilizer.cut() of `box` grown by `pad` in
        frames of `shape`, that is `box` grown by MARGIN, cut off at the image's
        edge as cut() cuts it."""
        height, width = shape[:2]
        x0, y0 = max(0, box[0] - pad), max(0, box[1] - pad)
        x1, y1 = max(0, box[0] - MARGIN), max(0, box[1] - MARGIN)
        x2, y2 = min(width, box[2] + MARGIN), min(height, box[3] + MARGIN)
        return cut[:, y1 - y0:y2 - y0, x1 - x0:x2 - x0]

    @staticmethod
    def contrast(image):
        """How much darker the middle 5 x 5 pixels of `image` are than the
        median of its outer 2 pixels, in grey levels."""
        h, w = image.shape
        edge = np.concatenate([image[:2].ravel(), image[-2:].ravel(), image[:, :2].ravel(), image[:, -2:].ravel()])
        return round(float(np.median(edge) - image[h // 2 - 2:h // 2 + 3, w // 2 - 2:w // 2 + 3].mean()), 2)

    @staticmethod
    def body(image):
        """(angle, elongation) of the dark blob under the image's centre: the
        direction of its long axis in degrees (0 to 180) and how many times
        longer than its short axis it is; (None, None) without one."""
        grey = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        _, dark = cv2.threshold(grey, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        _, labels = cv2.connectedComponents(dark)
        middle = labels[labels.shape[0] // 2 - 2:labels.shape[0] // 2 + 3, labels.shape[1] // 2 - 2:labels.shape[1] // 2 + 3]
        middle = middle[middle > 0]
        if not middle.size:
            return None, None
        ys, xs = np.nonzero(labels == np.bincount(middle).argmax())
        if len(xs) < 5:
            return None, None
        values, vectors = np.linalg.eigh(np.cov(np.vstack([xs, ys])))
        angle = float(np.degrees(np.arctan2(vectors[1, 1], vectors[0, 1])) % 180)
        return angle, float(np.sqrt(values[1] / max(values[0], 1e-9)))
