"""The Discobox's original software as a benchmark for the movement scores.

Abilium's software (github.com/Abilium-GmbH/varroa-discobox, src/processing.py)
never finds the mites. On each recording it denoises every frame, ORs together
the differences of the first frame to each later one, thresholds that at 25,
grows the spots left and counts each as one mite alive.

Here it is asked what the detector is asked: did this mite move in this
recording? It calls a mite moving when one of its spots lies on the mite's box.
Its threshold is fixed, as in the original; nothing is calibrated.
"""

import cv2
import numpy as np


class Benchmark:
    NAME = "Abilium"
    THRESHOLD = 25  # cv2.threshold(differentialImage, 25, 255, cv2.THRESH_BINARY)
    GROW = 5        # cv2.dilate(mask, kernel, iterations=5)
    KERNEL = np.ones((3, 3), np.uint8)
    # Pixels to read around the mites for their calls to be those of the whole
    # frame: the denoising looks 13 past a pixel, growing and closing 6 more.
    MARGIN = 32

    @staticmethod
    def differential(frames):
        """The first frame against every later one, each denoised, OR-ed
        together: diffImg() of the original. `frames` are grayscale."""
        frames = [cv2.fastNlMeansDenoising(frame, templateWindowSize=7, searchWindowSize=21) for frame in frames]
        differential = np.zeros(frames[0].shape, np.uint8)
        for frame in frames[1:]:
            differential = cv2.bitwise_or(cv2.absdiff(frames[0], frame), differential)
        return differential

    @classmethod
    def mask(cls, differential):
        """Where the original sees movement: the differential image above the
        threshold, grown and with its holes closed."""
        _ret, mask = cv2.threshold(differential, cls.THRESHOLD, 255, cv2.THRESH_BINARY)
        mask = cv2.dilate(mask, cls.KERNEL, iterations=cls.GROW)
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cls.KERNEL)

    @classmethod
    def calls(cls, frames, boxes):
        """Whether each mite moved in one recording, by the benchmark: mite id to
        True when movement lies on its box. `frames` are the recording's frames
        in grayscale, `boxes` {mite id: (x1, y1, x2, y2)} in their pixels."""
        mask = cls.mask(cls.differential(frames))
        return {mite_id: bool(mask[max(0, y1):y2, max(0, x1):x2].any())
                for mite_id, (x1, y1, x2, y2) in boxes.items()}
