import cv2
import numpy as np

from classes.analyzer import Analyzer
from classes.app_config import get_default_config
from classes.mite import Mite
from classes.plate_stabilizer import PlateStabilizer

SIZE = 120
# Dark blobs on a light plate, like mites; (x1, y1, x2, y2) boxes around them.
BOXES = [(20, 20, 36, 36), (70, 25, 86, 41), (30, 75, 46, 91), (80, 80, 96, 96), (50, 50, 66, 66)]


def plate():
    image = np.full((SIZE, SIZE), 200, np.float32)
    rng = np.random.default_rng(3)
    for x1, y1, x2, y2 in BOXES:
        cx, cy = (x1 + x2) / 2 + rng.uniform(-1, 1), (y1 + y2) / 2 + rng.uniform(-1, 1)
        cv2.ellipse(image, (int(cx), int(cy)), (5, 4), rng.uniform(0, 180), 0, 360, 60, -1)
    return cv2.GaussianBlur(image, (0, 0), 1.2)


def moved(image, dx, dy):
    return cv2.warpAffine(image, np.float32([[1, 0, dx], [0, 1, dy]]), image.shape[::-1],
                          flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT101)


def shaken(offsets):
    base = plate()
    return np.stack([moved(base, dx, dy) for dx, dy in offsets])[..., None].repeat(3, axis=-1)


OFFSETS = [(0, 0), (0.6, -0.4), (-0.5, 0.7), (1.2, 0.3), (-0.8, -1.1), (0.3, 0.9)]


class TestShifts:
    def test_it_measures_the_plate_shake(self):
        shifts = PlateStabilizer().shifts(shaken(OFFSETS), BOXES)
        assert np.abs(shifts - np.array(OFFSETS)).max() < 0.08

    def test_a_still_plate_has_no_shift(self):
        shifts = PlateStabilizer().shifts(shaken([(0, 0)] * 4), BOXES)
        assert np.abs(shifts).max() < 0.01

    def test_one_walking_mite_does_not_move_the_plate(self):
        frames = shaken([(0, 0)] * 4)
        x1, y1, x2, y2 = BOXES[0]
        for i in range(1, 4):  # the first mite walks 2 px per frame
            frames[i, y1 - 8:y2 + 8, x1 - 8:x2 + 8] = np.roll(frames[0, y1 - 8:y2 + 8, x1 - 8:x2 + 8], 2 * i, axis=1)
        assert np.abs(PlateStabilizer().shifts(frames, BOXES)).max() < 0.05

    def test_no_mites_no_shift(self):
        assert PlateStabilizer().shifts(shaken([(0, 0)] * 3), []).shape == (3, 2)


class TestCut:
    def test_it_cuts_the_same_box_as_get_roi(self):
        frames = shaken([(0, 0)] * 3)
        shifts = np.zeros((3, 2))
        for box in [BOXES[0], (0, 0, 10, 10), (SIZE - 8, SIZE - 8, SIZE, SIZE)]:
            mite = Mite(*box, config=get_default_config())
            expected = mite.get_ROI(frames, 5)
            cut = PlateStabilizer.cut(frames, tuple(mite), 5, shifts)
            assert cut.shape == expected.shape
            np.testing.assert_allclose(cut, expected, atol=0.5)

    def test_a_still_mite_on_a_shaking_plate_stays_still(self):
        frames = shaken(OFFSETS)
        shifts = PlateStabilizer().shifts(frames, BOXES)
        steady = PlateStabilizer.cut(frames, BOXES[4], 4, shifts)
        shaking = frames[:, 50 - 4:66 + 4, 50 - 4:66 + 4].astype(np.float32)
        assert Analyzer._variability(steady) < 0.05 * Analyzer._variability(shaking)


class TestAnalyzerStabilizes:
    def scores(self, stabilize, frames):
        config = get_default_config()
        config.mite.stabilize_plate = stabilize
        try:
            mites = [Mite(*box, config=config) for box in BOXES]
            for mite in mites:
                mite.metric, mite.metric_params = "topN_variability", {"n": 20}
            Analyzer(config).score_pool(mites, list(frames))
        finally:
            config.mite.stabilize_plate = False
        return np.array([mite.motion_scores[0] for mite in mites])

    def test_stabilizing_takes_the_shake_out_of_every_score(self):
        frames = shaken(OFFSETS)
        assert (self.scores(True, frames) < 0.05 * self.scores(False, frames)).all()

    def test_on_a_still_plate_it_changes_nothing(self):
        frames = shaken([(0, 0)] * 4)
        np.testing.assert_allclose(self.scores(True, frames), self.scores(False, frames), atol=0.05)
