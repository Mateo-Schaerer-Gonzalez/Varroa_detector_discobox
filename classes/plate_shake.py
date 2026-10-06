"""Shakes the plate in recorded frames, to see what a shaking plate does to the
scores without having recorded one.

The opposite of classes/plate_stabilizer.py: every frame is moved by a random
offset of its own, the same for the whole plate, as a rigid plate shakes.
"""

import cv2
import numpy as np


class PlateShake:
    """`shake`: the standard deviation of each frame's offset along x and along
    y, in pixels. The same `seed` shakes the same frames the same way."""

    SENSOR_ZOOM = 4   # offsets are whole pixels of the frame enlarged this many times

    def __init__(self, shake, seed=0):
        self.shake = float(shake)
        self.rng = np.random.default_rng(seed)

    def apply(self, frames):
        """The frames with the whole plate moved by a random offset in each.
        Edges are mirrored in, so no black border appears. Unchanged without shake.

        Each frame is moved as a camera would see it: enlarged SENSOR_ZOOM times,
        moved by whole enlarged pixels, and each camera pixel then averaged over
        its area. Moving the frame itself by a fraction of a pixel would instead
        blur it by an amount that changes with every frame, a change no camera
        makes."""
        if not self.shake:
            return frames
        zoom = self.SENSOR_ZOOM
        out = np.empty_like(frames)
        for i, frame in enumerate(frames):
            dx, dy = np.round(self.rng.normal(0, self.shake, 2) * zoom)
            big = cv2.resize(frame, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
            big = cv2.warpAffine(big, np.float32([[1, 0, dx], [0, 1, dy]]), big.shape[1::-1],
                                 flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REFLECT101)
            out[i] = cv2.resize(big, frame.shape[1::-1], interpolation=cv2.INTER_AREA)
        return out
