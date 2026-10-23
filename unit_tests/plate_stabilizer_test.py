import cv2
import numpy as np

from classes.scoring.analyzer import Analyzer
from classes.app_config import get_default_config
from classes.plate.mite import Mite
from classes.scoring import plate_stabilizer
from classes.scoring.plate_stabilizer import PlateStabilizer

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


def apart(left, right):
    """Frames in which the two halves of the image shake on their own: the
    left by the offsets `left`, the right by `right`."""
    base = plate()
    half = SIZE // 2
    return np.stack([np.hstack([moved(base, *l)[:, :half], moved(base, *r)[:, half:]]) for l, r in zip(left, right)])


class TestShifts:
    def test_every_mite_follows_the_plate_shake(self):
        shifts = PlateStabilizer().shifts(shaken(OFFSETS), BOXES)
        assert shifts.shape == (len(BOXES), len(OFFSETS), 2)
        assert np.abs(shifts - np.array(OFFSETS)[None]).max() < 0.1

    def test_a_still_plate_has_no_shift(self):
        shifts = PlateStabilizer().shifts(shaken([(0, 0)] * 4), BOXES)
        assert np.abs(shifts).max() < 0.01

    def test_plates_that_shake_apart_are_each_followed(self):
        right = [(0, 0), (-0.7, 0.5), (1.1, -0.9), (0.4, 1.3)]
        left = [(0, 0)] + OFFSETS[1:4]
        boxes = [BOXES[0], BOXES[2], BOXES[1], BOXES[3]]  # two on the left half, two on the right
        shifts = PlateStabilizer().shifts(apart(left, right), boxes)
        assert np.abs(shifts - np.array([left, left, right, right])).max() < 0.1

    def test_one_walking_mite_does_not_move_the_others(self):
        frames = shaken([(0, 0)] * 4)
        x1, y1, x2, y2 = BOXES[0]
        for i in range(1, 4):  # the first mite walks 2 px per frame
            frames[i, y1 - 8:y2 + 8, x1 - 8:x2 + 8] = np.roll(frames[0, y1 - 8:y2 + 8, x1 - 8:x2 + 8], 2 * i, axis=1)
        shifts = PlateStabilizer().shifts(frames, BOXES)
        assert np.abs(shifts[1:]).max() < 0.01
        assert shifts[0, 3, 0] > 1  # its own centre went with it

    def test_a_mite_that_leaves_its_patch_takes_the_plates_shift(self):
        frames = shaken(OFFSETS)
        x1, y1, x2, y2 = BOXES[0]
        frames[2:, y1 - 8:y2 + 8, x1 - 8:x2 + 8] = 200  # gone from the third frame on
        shifts = PlateStabilizer().shifts(frames, BOXES)
        assert np.isfinite(shifts).all()
        np.testing.assert_allclose(shifts[0], np.median(shifts[1:], axis=0))

    def test_a_blank_plate_has_no_shift(self):
        frames = np.full((3, SIZE, SIZE), 200, np.uint8)
        np.testing.assert_array_equal(PlateStabilizer().shifts(frames, BOXES), np.zeros((len(BOXES), 3, 2)))

    def test_no_mites_no_shift(self):
        assert PlateStabilizer().shifts(shaken([(0, 0)] * 3), []).shape == (0, 3, 2)

    def test_a_huge_movement_is_followed_no_further_than_the_margin(self):
        frames = shaken([(0, 0), (30, -30), (-25, 40)])  # mites thrown out of their patches
        boxes = BOXES + [(-5, -5, 8, 8), (SIZE - 6, SIZE - 6, SIZE + 4, SIZE + 4)]  # partly off the image
        shifts = PlateStabilizer().shifts(frames, boxes)
        reach = plate_stabilizer.MARGIN - plate_stabilizer._LANCZOS_REACH
        assert np.isfinite(shifts).all() and np.abs(shifts).max() <= reach

    def test_follow_tells_how_far_each_mite_strayed_and_shook(self):
        frames = shaken([(0, 0)] * 4)
        x1, y1, x2, y2 = BOXES[0]
        for i in range(1, 4):
            frames[i, y1 - 8:y2 + 8, x1 - 8:x2 + 8] = np.roll(frames[0, y1 - 8:y2 + 8, x1 - 8:x2 + 8], 2 * i, axis=1)
        followed = PlateStabilizer().follow(frames, BOXES)
        assert followed[0].stray > 1 and followed[0].shake > 1
        assert max(f.stray for f in followed[1:]) < 0.01
        np.testing.assert_array_equal(followed[0].shifts, PlateStabilizer().shifts(frames, BOXES)[0])


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
        steady = PlateStabilizer.cut(frames, BOXES[4], 4, shifts[4])
        shaking = frames[:, 50 - 4:66 + 4, 50 - 4:66 + 4].astype(np.float32)
        assert Analyzer._variability(steady) < 0.05 * Analyzer._variability(shaking)


    def test_a_cut_reads_no_further_than_the_margin(self):
        # what a saved live run keeps: the scored patch and MARGIN round it, nothing else
        pad, margin = 16, plate_stabilizer.MARGIN
        x1, y1, x2, y2 = BOXES[4]
        reach = margin - plate_stabilizer._LANCZOS_REACH
        frames = np.full((3, SIZE, SIZE), np.nan, np.float32)
        frames[:, y1 - pad - margin:y2 + pad + margin, x1 - pad - margin:x2 + pad + margin] = 100
        cut = PlateStabilizer.cut(frames, BOXES[4], pad, [(0, 0), (reach, -reach), (-reach, reach)])
        assert cut.shape[1:3] == (y2 - y1 + 2 * pad, x2 - x1 + 2 * pad) and np.isfinite(cut).all()

    def test_a_box_off_the_image_is_cut_without_error(self):
        frames = shaken(OFFSETS)
        for box in [(-5, -5, 8, 8), (SIZE - 6, SIZE - 6, SIZE + 4, SIZE + 4)]:
            shifts = PlateStabilizer().shifts(frames, [box])[0]
            mite = Mite(*box, config=get_default_config())
            assert PlateStabilizer.cut(frames, box, 16, shifts).shape == mite.get_ROI(frames, 16).shape


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
