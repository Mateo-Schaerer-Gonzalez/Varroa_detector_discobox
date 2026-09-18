import cv2
import numpy as np
import pytest

from classes.app_config import AppConfig, DetectorConfig, get_default_config
from classes.detector import Detector
from classes.mite import Mite
from classes.zones import Zone, ZoneManager


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
        params = Detector._build_params(custom_detector_config)

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
        detector = Detector()
        assert detector.config is get_default_config()
        assert detector.config.detector == AppConfig().detector

    def test_custom_config_overrides_default(self, custom_detector_config):
        config = FakeConfig(detector=custom_detector_config)
        detector = Detector(config=config)
        assert detector.config is config
        assert detector.config.detector == custom_detector_config

    def test_builds_blob_detector_instance(self):
        detector = Detector()
        assert isinstance(detector.blob_detector, cv2.SimpleBlobDetector)


class TestDetect:
    def test_delegates_to_blob_detector(self):
        detector = Detector()
        fake = FakeBlobDetector(return_value=())
        detector.blob_detector = fake
        image = np.zeros((10, 10, 3), dtype=np.uint8)

        result = detector.detect(image)

        assert result == []
        assert fake.received_image is image

    def test_no_blobs_on_blank_image(self):
        detector = Detector()
        image = np.full((100, 100, 3), 255, dtype=np.uint8)

        mites = detector.detect(image)

        assert len(mites) == 0

    def test_detects_dark_blob_on_light_background(self):
        detector = Detector()
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        cv2.circle(image, (100, 100), 12, (0, 0, 0), -1)

        mites = detector.detect(image)

        assert len(mites) == 1
        assert isinstance(mites[0], Mite)
        center_x = (mites[0].x1 + mites[0].x2) / 2
        center_y = (mites[0].y1 + mites[0].y2) / 2
        assert center_x == pytest.approx(100, abs=5)
        assert center_y == pytest.approx(100, abs=5)

    def test_detects_multiple_separate_blobs(self):
        detector = Detector()
        image = np.full((300, 300, 3), 255, dtype=np.uint8)
        cv2.circle(image, (75, 75), 12, (0, 0, 0), -1)
        cv2.circle(image, (220, 220), 12, (0, 0, 0), -1)

        mites = detector.detect(image)

        centers = sorted(
            ((m.x1 + m.x2) / 2, (m.y1 + m.y2) / 2) for m in mites
        )
        assert centers[0] == pytest.approx((75, 75), abs=1)
        assert centers[1] == pytest.approx((220, 220), abs=1)

    def test_ignores_blob_below_min_area(self):
        detector = Detector()
        image = np.full((100, 100, 3), 255, dtype=np.uint8)
        cv2.circle(image, (50, 50), 2, (0, 0, 0), -1)  # area well under min_area=40

        mites = detector.detect(image)

        assert len(mites) == 0

    def test_ignores_light_blob_when_configured_for_dark(self):
        detector = Detector()
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.circle(image, (50, 50), 12, (255, 255, 255), -1)  # light blob, blob_color=0 wants dark

        mites = detector.detect(image)

        assert len(mites) == 0

    def test_mite_bounding_box_centered_on_keypoint(self):
        detector = Detector()
        kp = cv2.KeyPoint(50, 50, 10)
        detector.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

        mite = mites[0]
        assert (mite.x1, mite.y1, mite.x2, mite.y2) == (45, 45, 55, 55)

    def test_multiple_keypoints_create_distinct_mites(self):
        detector = Detector()
        kp1 = cv2.KeyPoint(20, 20, 6)
        kp2 = cv2.KeyPoint(80, 80, 6)
        detector.blob_detector = FakeBlobDetector(return_value=[kp1, kp2])

        mites = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

        assert len(mites) == 2
        assert mites[0] is not mites[1]

    def test_created_mite_uses_detector_config(self):
        detector = Detector()
        kp = cv2.KeyPoint(50, 50, 10)
        detector.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

        mite = mites[0]
        assert mite.radius == detector.config.mite.radius
        assert mite.motion_threshold == detector.config.mite.motion_threshold
        assert mite.color == detector.config.mite.alive_color


class TestDetectAndAssignIntegration:
    """Exercises detect() together with ZoneManager.assign_mites(), the two
    steps that replaced the old Detector.process_frame()."""

    def test_keypoint_inside_zone_is_assigned_as_mite(self):
        detector = Detector()
        zone = Zone(0, 0, 100, 100, type="brood")
        zone_manager = ZoneManager([zone])
        kp = cv2.KeyPoint(50, 50, 10)
        detector.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        assigned = zone_manager.assign_mites(mites)

        assert len(assigned) == 1
        assert isinstance(assigned[0], Mite)
        assert zone.mites == assigned

    def test_keypoint_outside_all_zones_is_ignored(self):
        detector = Detector()
        zone = Zone(0, 0, 10, 10, type="brood")
        zone_manager = ZoneManager([zone])
        kp = cv2.KeyPoint(50, 50, 4)
        detector.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        assigned = zone_manager.assign_mites(mites)

        assert assigned == []
        assert zone.mites == []

    def test_assigns_to_first_matching_zone_only(self):
        detector = Detector()
        first_zone = Zone(0, 0, 100, 100, type="brood")
        second_zone = Zone(0, 0, 100, 100, type="entrance")
        zone_manager = ZoneManager([first_zone, second_zone])
        kp = cv2.KeyPoint(50, 50, 10)
        detector.blob_detector = FakeBlobDetector(return_value=[kp])

        mites = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        zone_manager.assign_mites(mites)

        assert len(first_zone.mites) == 1
        assert second_zone.mites == []
