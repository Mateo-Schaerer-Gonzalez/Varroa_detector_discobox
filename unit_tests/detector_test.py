import cv2
import numpy as np
import pytest

from classes.app_config import AppConfig, DetectorConfig, get_default_config
from classes.scoring.analyzer import ANGLES, Analyzer, NoNoiseWarning
from classes.scoring.plate_stabilizer import PlateStabilizer
from classes.plate.mite import Mite
from classes.plate.zones import Zone, ZoneManager


class FakeConfig:
    def __init__(self, detector):
        self.detector = detector


class FakeBlobDetector:
    def __init__(self, return_value=()):
        self.received_image = None
        self.return_value = return_value

    def detect(self, image):
        self.received_image = image
        return self.return_value


@pytest.fixture
def custom_detector_config():
    return DetectorConfig(
        min_threshold=10,
        max_threshold=220,
        threshold_step=5,
        filter_by_color=True,
        blob_color=255,
        filter_by_area=True,
        min_area=20,
        max_area=500,
        filter_by_circularity=True,
        min_circularity=0.7,
        filter_by_convexity=True,
        min_convexity=0.9,
        filter_by_inertia=True,
        min_inertia_ratio=0.3,
    )


class TestBuildParams:
    def test_maps_all_fields_from_config(self, custom_detector_config):
        params = Analyzer._build_params(custom_detector_config)

        assert params.minThreshold == pytest.approx(10)
        assert params.maxThreshold == pytest.approx(220)
        assert params.thresholdStep == pytest.approx(5)
        assert params.filterByColor is True
        assert params.blobColor == 255
        assert params.filterByArea is True
        assert params.minArea == pytest.approx(20)
        assert params.maxArea == pytest.approx(500)
        assert params.filterByCircularity is True
        assert params.minCircularity == pytest.approx(0.7)
        assert params.filterByConvexity is True
        assert params.minConvexity == pytest.approx(0.9)
        assert params.filterByInertia is True
        assert params.minInertiaRatio == pytest.approx(0.3)


class TestInit:
    def test_default_config_matches_yaml(self):
        analyzer = Analyzer()
        assert analyzer.config is get_default_config()
        assert analyzer.config.detector == AppConfig().detector

    def test_custom_config_overrides_default(self, custom_detector_config):
        config = FakeConfig(detector=custom_detector_config)
        analyzer = Analyzer(config=config)
        assert analyzer.config is config
        assert analyzer.config.detector == custom_detector_config

    def test_builds_blob_detector_instance(self):
        analyzer = Analyzer()
        assert isinstance(analyzer.blob_detector, cv2.SimpleBlobDetector)


class TestDetect:
    def test_delegates_to_blob_detector(self):
        analyzer = Analyzer()
        fake = FakeBlobDetector(return_value=())
        analyzer.blob_detector = fake
        image = np.zeros((10, 10, 3), dtype=np.uint8)

        result = analyzer.detect(image)

        assert result == []
        assert fake.received_image is image

    def test_no_blobs_on_blank_image(self):
        analyzer = Analyzer()
        image = np.full((100, 100, 3), 255, dtype=np.uint8)

        mites = analyzer.detect(image)

        assert len(mites) == 0

    def test_detects_dark_blob_on_light_background(self):
        analyzer = Analyzer()
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        cv2.circle(image, (100, 100), 12, (0, 0, 0), -1)

        mites = analyzer.detect(image)

        assert len(mites) == 1
        assert isinstance(mites[0], Mite)
        center_x = (mites[0].x1 + mites[0].x2) / 2
        center_y = (mites[0].y1 + mites[0].y2) / 2
        assert center_x == pytest.approx(100, abs=5)
        assert center_y == pytest.approx(100, abs=5)

    def test_detects_multiple_separate_blobs(self):
        analyzer = Analyzer()
        image = np.full((300, 300, 3), 255, dtype=np.uint8)
        cv2.circle(image, (75, 75), 12, (0, 0, 0), -1)
        cv2.circle(image, (220, 220), 12, (0, 0, 0), -1)

        mites = analyzer.detect(image)

        centers = sorted(
            ((m.x1 + m.x2) / 2, (m.y1 + m.y2) / 2) for m in mites
        )
        assert centers[0] == pytest.approx((75, 75), abs=1)
        assert centers[1] == pytest.approx((220, 220), abs=1)

    def test_ignores_blob_below_min_area(self):
        analyzer = Analyzer()
        image = np.full((100, 100, 3), 255, dtype=np.uint8)
        cv2.circle(image, (50, 50), 2, (0, 0, 0), -1)  # area well under min_area=40

        mites = analyzer.detect(image)

        assert len(mites) == 0

    def test_ignores_light_blob_when_configured_for_dark(self):
        analyzer = Analyzer()
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.circle(image, (50, 50), 12, (255, 255, 255), -1)  # light blob, blob_color=0 wants dark

        mites = analyzer.detect(image)

        assert len(mites) == 0

    def test_mite_bounding_box_centered_on_keypoint(self):
        analyzer = Analyzer()
        kp = cv2.KeyPoint(50, 50, 10)
        analyzer.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = analyzer.detect(np.zeros((100, 100, 3), dtype=np.uint8))

        mite = mites[0]
        assert (mite.x1, mite.y1, mite.x2, mite.y2) == (45, 45, 55, 55)

    def test_multiple_keypoints_create_distinct_mites(self):
        analyzer = Analyzer()
        kp1 = cv2.KeyPoint(20, 20, 6)
        kp2 = cv2.KeyPoint(80, 80, 6)
        analyzer.blob_detector = FakeBlobDetector(return_value=[kp1, kp2])

        mites = analyzer.detect(np.zeros((100, 100, 3), dtype=np.uint8))

        assert len(mites) == 2
        assert mites[0] is not mites[1]

    def test_created_mite_uses_detector_config(self):
        analyzer = Analyzer()
        kp = cv2.KeyPoint(50, 50, 10)
        analyzer.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = analyzer.detect(np.zeros((100, 100, 3), dtype=np.uint8))

        mite = mites[0]
        assert mite.radius == analyzer.config.mite.radius
        assert mite.motion_threshold == analyzer.config.mite.motion_threshold
        # no recording scored yet, so it is drawn as still
        assert mite.color == analyzer.config.mite.still_color


class TestDetectAndAssignIntegration:
    """Exercises detect() together with ZoneManager.assign_mites(), the two
    steps that replaced the old Analyzer.process_frame()."""

    def test_keypoint_inside_zone_is_assigned_as_mite(self):
        analyzer = Analyzer()
        zone = Zone(0, 0, 100, 100, type="brood")
        zone_manager = ZoneManager([zone])
        kp = cv2.KeyPoint(50, 50, 10)
        analyzer.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = analyzer.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        assigned = zone_manager.assign_mites(mites)

        assert len(assigned) == 1
        assert isinstance(assigned[0], Mite)
        assert zone.mites == assigned

    def test_keypoint_outside_all_zones_is_ignored(self):
        analyzer = Analyzer()
        zone = Zone(0, 0, 10, 10, type="brood")
        zone_manager = ZoneManager([zone])
        kp = cv2.KeyPoint(50, 50, 4)
        analyzer.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = analyzer.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        assigned = zone_manager.assign_mites(mites)

        assert assigned == []
        assert zone.mites == []

    def test_assigns_to_first_matching_zone_only(self):
        analyzer = Analyzer()
        first_zone = Zone(0, 0, 100, 100, type="brood")
        second_zone = Zone(0, 0, 100, 100, type="entrance")
        zone_manager = ZoneManager([first_zone, second_zone])
        kp = cv2.KeyPoint(50, 50, 10)
        analyzer.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = analyzer.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        zone_manager.assign_mites(mites)

        assert len(first_zone.mites) == 1
        assert second_zone.mites == []


class TestRoiPadding:
    def test_metric_without_pad_is_not_padded(self):
        assert Analyzer.roi_padding("topN_variability", {"n": 5}) == 0

    def test_optical_flow_pads_by_its_pad_parameter(self):
        assert Analyzer.roi_padding("optical_flow") == 0
        assert Analyzer.roi_padding("optical_flow", {"pad": 6}) == 6

    def test_pad_may_be_zero_but_not_negative(self):
        assert Analyzer.check_metric_params("optical_flow", {"pad": 0})["pad"] == 0
        with pytest.raises(ValueError, match="negative"):
            Analyzer.check_metric_params("optical_flow", {"pad": -1})

    def test_other_parameters_must_still_be_positive(self):
        with pytest.raises(ValueError, match="positive"):
            Analyzer.check_metric_params("optical_flow", {"step": 0})

    def test_score_pool_cuts_the_padded_roi(self, monkeypatch):
        config = get_default_config()
        mite = Mite(4, 4, 6, 6, config=config)
        mite.metric, mite.metric_params = "optical_flow", {"pad": 3}
        seen = []
        monkeypatch.setattr(Analyzer, "_motion_score",
                            staticmethod(lambda roi, metric, params=None: seen.append(roi.shape) or 0.0))
        Analyzer(config).score_pool([mite], [np.zeros((12, 12, 3), np.uint8)] * 3)
        assert seen == [(3, 8, 8, 3)]


class TestOpticalFlowShortStacks:
    def test_a_stack_shorter_than_step_still_gets_a_score(self):
        roi = np.random.default_rng(0).uniform(0, 255, (5, 20, 20, 3)).astype(np.float32)
        score = Analyzer._motion_score(roi, "optical_flow", {"step": 10})
        assert np.isfinite(score)

    def test_it_compares_the_first_and_last_frames(self):
        roi = np.random.default_rng(0).uniform(0, 255, (5, 20, 20, 3)).astype(np.float32)
        assert Analyzer._motion_score(roi, "optical_flow", {"step": 10}) == \
            Analyzer._motion_score(roi, "optical_flow", {"step": 4})


def _mite_frames(legs, shifts=None, light=None, size=46):
    """Frames of a dark oval on a bright plate with one leg: `legs` gives, per
    frame, how far the leg sticks out to the left, in pixels."""
    frames = []
    for index, leg in enumerate(legs):
        frame = np.full((size, size), 115, dtype=np.uint8)
        cv2.ellipse(frame, (size // 2, size // 2), (5, 7), 0, 0, 360, 25, -1)
        if leg:
            cv2.line(frame, (size // 2 - 5, size // 2 - 2), (size // 2 - 5 - leg, size // 2 - 3), 60, 1)
        frame = cv2.GaussianBlur(frame, (0, 0), 0.8).astype(np.float32)
        if shifts is not None:
            move = np.float32([[1, 0, shifts[index]], [0, 1, 0]])
            frame = cv2.warpAffine(frame, move, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        if light is not None:
            frame = frame * light[index]
        frames.append(frame)
    return np.stack(frames)[..., None]


class TestOutlineMovement:
    SHAKE = [0, 0.3, -0.3, 0.2, -0.2, 0]

    def test_it_is_padded_by_default(self):
        assert Analyzer.roi_padding("outline_movement") == 16

    def test_a_mite_that_does_nothing_scores_nothing(self):
        assert Analyzer._motion_score(_mite_frames([3] * 6), "outline_movement") == pytest.approx(0, abs=1e-4)

    def test_a_leg_that_moves_scores_in_pixels(self):
        score = Analyzer._motion_score(_mite_frames([3, 3, 4, 5, 4, 3]), "outline_movement")
        assert 0.15 < score < 2

    def test_a_leg_that_moves_further_scores_higher(self):
        short = Analyzer._motion_score(_mite_frames([3, 4, 3, 4]), "outline_movement")
        far = Analyzer._motion_score(_mite_frames([3, 6, 3, 6]), "outline_movement")
        assert far > short

    def test_a_lamp_that_flickers_scores_nothing(self):
        frames = _mite_frames([3] * 6, light=[1.0, 0.97, 1.0, 0.97, 1.03, 1.0])
        assert Analyzer._motion_score(frames, "outline_movement") == pytest.approx(0, abs=1e-3)

    def test_a_shaking_plate_scores_far_less_than_a_leg(self):
        leg = Analyzer._motion_score(_mite_frames([3, 3, 4, 5, 4, 3]), "outline_movement")
        shake = Analyzer._motion_score(_mite_frames([3] * 6, shifts=self.SHAKE), "outline_movement")
        assert shake < leg / 3

    def test_a_patch_without_a_mite_scores_nothing(self):
        assert Analyzer._motion_score(np.full((5, 40, 40, 1), 115, dtype=np.float32), "outline_movement") == 0.0

    def test_a_patch_cut_off_at_the_image_edge_still_gets_a_score(self):
        frames = _mite_frames([3, 3, 4, 5, 4, 3])[:, :, 14:]   # the mite 9 pixels from the left edge
        assert np.isfinite(Analyzer._motion_score(frames, "outline_movement"))


def _neighbour_frames(offsets, size=46):
    """Frames of a still mite with a second one beside it: `offsets` gives,
    per frame, how far down the neighbour is, in pixels."""
    frames = []
    for offset in offsets:
        frame = np.full((size, size), 115, dtype=np.uint8)
        cv2.ellipse(frame, (size // 2, size // 2), (5, 7), 0, 0, 360, 25, -1)
        cv2.ellipse(frame, (size // 2 - 13, size // 2 + offset), (4, 6), 0, 0, 360, 25, -1)
        frames.append(cv2.GaussianBlur(frame, (0, 0), 0.8).astype(np.float32))
    return np.stack(frames)[..., None]


class TestOutlineVariability:
    LEG = [3, 3, 4, 5, 4, 3, 3, 4, 5, 4]
    STILL = [3] * 10
    SHAKE = [0, 0.3, -0.3, 0.2, -0.2, 0]

    @staticmethod
    def _score(frames, **params):
        return Analyzer._motion_score(frames, "outline_variability", params)

    @staticmethod
    def _noisy(frames, sd=1.0):
        """The frames as a camera gives them: with noise in every pixel."""
        return frames + np.random.default_rng(0).normal(0, sd, frames.shape).astype(np.float32)

    @staticmethod
    def _plate(frames, sd=1.0):
        """The frames with fake camera noise on the bare plate at the patch's
        edge alone, where plate_noise() reads it: the score has a noise floor
        to be divided by, and the mite's outline is left as it was."""
        frames = np.array(frames, dtype=np.float32)
        edge = np.ones(frames.shape[1:3], dtype=bool)
        edge[6:-6, 6:-6] = False
        frames[:, edge] += np.random.default_rng(0).normal(0, sd, frames[:, edge].shape).astype(np.float32)
        return frames

    def test_it_is_padded_by_default(self):
        assert Analyzer.roi_padding("outline_variability") == 16

    def test_a_mite_that_does_nothing_scores_nothing(self):
        assert self._score(_mite_frames(self.STILL)) == 0.0

    def test_a_leg_that_moves_scores(self):
        assert self._score(self._plate(_mite_frames(self.LEG))) > 0.05

    def test_a_leg_that_moves_further_scores_higher(self):
        short, far = (self._score(self._plate(_mite_frames(legs))) for legs in ([3, 4] * 5, [3, 6] * 5))
        # 5x with the constants before 2026-10-27; 2.5x with the narrower outline band since
        assert far > 2 * short

    def test_it_is_the_vector_sum_of_the_profile(self):
        frames = self._noisy(_mite_frames(self.LEG))
        profile = Analyzer.outline_variability_profile(frames)
        angle = np.arange(len(profile)) * 2 * np.pi / len(profile)
        length = np.hypot((profile * np.cos(angle)).sum(), (profile * np.sin(angle)).sum())
        assert self._score(frames) == pytest.approx(length / len(profile) / Analyzer.plate_noise(frames))

    def test_the_variance_is_on_the_side_of_the_leg(self):
        profile = Analyzer.outline_variability_profile(_mite_frames(self.LEG))
        assert profile.shape == (ANGLES,)
        # the leg sticks out to the left and a little up: 197° clockwise from the right
        assert 180 <= np.degrees(profile.argmax() * 2 * np.pi / ANGLES) <= 214
        quarter = slice(ANGLES * 27 // 64, ANGLES * 44 // 64)
        assert profile[quarter].sum() > 0.7 * profile.sum()   # a quarter of the outline

    def test_noise_all_round_cancels(self):
        frames = self._noisy(_mite_frames(self.STILL), sd=2.0)
        assert self._score(frames) < Analyzer.outline_variability_profile(frames).mean() / 10

    def test_it_is_in_multiples_of_the_noise_floor(self):
        quiet, loud = (self._noisy(_mite_frames(self.STILL * 3), sd=sd) for sd in (1.0, 3.0))
        assert Analyzer.plate_noise(loud) == pytest.approx(9 * Analyzer.plate_noise(quiet), rel=0.2)
        assert self._score(loud) == pytest.approx(self._score(quiet), rel=0.2)

    def test_frames_without_noise_are_flagged_and_not_divided(self):
        frames = _mite_frames(self.LEG)
        assert Analyzer.plate_noise(frames) == 0
        profile = Analyzer.outline_variability_profile(frames)
        with pytest.warns(NoNoiseWarning):
            score = self._score(frames)
        assert score == pytest.approx(abs((profile * np.exp(2j * np.pi * np.arange(len(profile)) / len(profile))).mean()))

    def test_a_lamp_that_flickers_scores_nothing(self):
        light = [1.0, 0.97, 1.0, 0.97, 1.03, 1.0, 0.98, 1.02, 1.0, 0.99]
        assert self._score(_mite_frames(self.STILL, light=light)) == 0.0

    def _stabilised(self, legs, shifts=None, size=80):
        """The mite's patch as the app scores it: cut from frames moved back by
        the stabilizer, with plate noise on its rim."""
        frames = _mite_frames(legs, shifts=shifts, size=size)[..., 0]
        box = (size // 2 - 8, size // 2 - 8, size // 2 + 8, size // 2 + 8)
        return self._plate(PlateStabilizer.cut(frames, box, 16, PlateStabilizer().shifts(frames, [box])[0]))

    def test_a_shaking_plate_scores_less_than_a_leg(self):
        # Not stabilised, a shake varies the outline all round and scores above a
        # leg (it was divided down by the profile's mean, `relative`, until
        # 2026-10-27); the app always stabilises first, which takes most of it out.
        leg = self._score(self._stabilised(self.LEG))
        for shake in (self.SHAKE, [3 * s for s in self.SHAKE]):
            assert self._score(self._stabilised([3] * 6, shake)) < leg / 2

    def test_two_opposite_sides_cancel(self):
        one = _mite_frames(self.LEG)
        both = np.minimum(one, one[:, ::-1, ::-1])   # the same leg on the other side as well, moving with it
        assert self._score(self._plate(both)) < self._score(self._plate(one)) / 4

    def test_a_neighbour_that_moves_is_not_the_mite(self):
        beside = _neighbour_frames([0, 1, 2, 1, 0, -1, 0, 1, 2, 1])
        assert beside.var(axis=0).mean() > 5   # the neighbour changes the patch far more than a leg does
        assert self._score(self._plate(beside)) < self._score(self._plate(_mite_frames(self.LEG))) / 2

    def test_a_patch_without_a_mite_scores_nothing(self):
        assert self._score(np.full((5, 40, 40, 1), 115, dtype=np.float32)) == 0.0

    def test_a_patch_cut_off_at_the_image_edge_still_gets_a_score(self):
        frames = _mite_frames(self.LEG)[:, :, 14:]   # the mite 9 pixels from the left edge
        assert np.isfinite(self._score(self._plate(frames)))

    def test_one_frame_scores_nothing(self):
        assert self._score(_mite_frames([3])) == 0.0
